// VSCode extension entry — launches the Python LSP server, registers
// Run / Screenshot / Preview commands that hit the AutoControl REST API,
// and exposes a tree view of the current script's steps.

import * as vscode from "vscode";
import * as fs from "node:fs/promises";
import * as http from "node:http";
import * as https from "node:https";
import * as os from "node:os";
import * as nodePath from "node:path";
import { URL } from "node:url";
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
    TransportKind,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;
let stepProvider: ScriptStepProvider | undefined;

export function activate(context: vscode.ExtensionContext): void {
    client = startLanguageClient();
    stepProvider = new ScriptStepProvider();
    // Consolidate every subscription into a single push() call (S7778):
    // VS Code accepts a varargs subscriber list, so building the array
    // up front keeps the call site flat and avoids repeated diffs.
    context.subscriptions.push(
        { dispose: () => client?.stop() },
        vscode.window.registerTreeDataProvider(
            "autocontrolScriptSteps", stepProvider,
        ),
        vscode.window.onDidChangeActiveTextEditor(() => stepProvider?.refresh()),
        vscode.workspace.onDidChangeTextDocument(() => stepProvider?.refresh()),
        vscode.commands.registerCommand(
            "autocontrol.runScript", runCurrentScript,
        ),
        vscode.commands.registerCommand(
            "autocontrol.takeScreenshot", takeScreenshot,
        ),
        vscode.commands.registerCommand(
            "autocontrol.previewScript", () => stepProvider?.refresh(),
        ),
    );
}

export function deactivate(): Thenable<void> | undefined {
    return client?.stop();
}

// --- LSP client --------------------------------------------------

// Keep in step with package.json's autocontrolLsp.actionFiles default and
// DEFAULT_ACTION_FILE_GLOBS in autocontrol_lsp/server/action_files.py.
const DEFAULT_ACTION_FILES: string[] = ["**/*.ac.json", "**/actions/**/*.json"];

function startLanguageClient(): LanguageClient {
    const config = vscode.workspace.getConfiguration("autocontrolLsp");
    const pythonPath = config.get<string>("python.path", "python");
    const serverModule = config.get<string>(
        "server.module", "autocontrol_lsp.server",
    );
    const serverOptions: ServerOptions = {
        command: pythonPath,
        args: ["-m", serverModule],
        transport: TransportKind.stdio,
    };
    // Only action files, never every JSON document: a package.json is not
    // an action list. The server applies the same globs as a guard.
    const actionFiles = config.get<string[]>(
        "actionFiles", DEFAULT_ACTION_FILES,
    );
    const clientOptions: LanguageClientOptions = {
        documentSelector: actionFiles.map(
            (pattern) => ({ scheme: "file", pattern }),
        ),
        initializationOptions: { actionFiles },
    };
    const lc = new LanguageClient(
        "autocontrolLsp", "AutoControl LSP",
        serverOptions, clientOptions,
    );
    lc.start();
    return lc;
}

// --- REST helpers -------------------------------------------------

function restConfig(): { url: string; token: string } {
    const config = vscode.workspace.getConfiguration("autocontrolLsp");
    return {
        url: config.get<string>("rest.url", "http://127.0.0.1:9939"),
        token: config.get<string>("rest.token", "")
            || process.env.AC_TOKEN || "",
    };
}

interface RestReply {
    statusCode: number;
    body: string;
}

// The REST server routes each path for one method only; /screenshot is GET.
function restRequest(
    method: "GET" | "POST", path: string, payload?: unknown,
): Promise<RestReply> {
    return new Promise((resolve, reject) => {
        const { url, token } = restConfig();
        let parsed: URL;
        try {
            parsed = new URL(path, url);
        } catch (error) {
            reject(error instanceof Error
                ? error
                : new Error(String(error)));
            return;
        }
        const isHttps = parsed.protocol === "https:";
        const body = payload === undefined
            ? undefined
            : Buffer.from(JSON.stringify(payload), "utf-8");
        const headers: http.OutgoingHttpHeaders = {
            "Authorization": token ? `Bearer ${token}` : "",
        };
        if (body !== undefined) {
            headers["Content-Type"] = "application/json";
            headers["Content-Length"] = body.length;
        }
        const requestOptions: http.RequestOptions = {
            hostname: parsed.hostname,
            port: parsed.port || (isHttps ? 443 : 80),
            path: parsed.pathname + parsed.search,
            method,
            headers,
        };
        const httpModule = isHttps ? https : http;
        const request = httpModule.request(requestOptions, (response) => {
            const chunks: Buffer[] = [];
            response.on("data", (chunk: Buffer) => chunks.push(chunk));
            response.on("end", () => {
                resolve({
                    statusCode: response.statusCode || 0,
                    body: Buffer.concat(chunks).toString("utf-8"),
                });
            });
        });
        request.on("error", reject);
        if (body !== undefined) {
            request.write(body);
        }
        request.end();
    });
}

// --- Commands -----------------------------------------------------

async function runCurrentScript(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage(
            "AutoControl: open a JSON action file first.",
        );
        return;
    }
    let actions: unknown;
    try {
        actions = JSON.parse(editor.document.getText());
    } catch (error) {
        vscode.window.showErrorMessage(
            `AutoControl: cannot run — invalid JSON (${(error as Error).message})`,
        );
        return;
    }
    try {
        const reply = await restRequest("POST", "/execute", { actions });
        if (reply.statusCode >= 200 && reply.statusCode < 300) {
            vscode.window.showInformationMessage(
                `AutoControl: ran ${editor.document.fileName}`,
            );
            return;
        }
        vscode.window.showErrorMessage(
            `AutoControl: REST ${reply.statusCode}: ${reply.body.slice(0, 240)}`,
        );
    } catch (error) {
        vscode.window.showErrorMessage(
            `AutoControl: REST call failed (${(error as Error).message})`,
        );
    }
}

async function takeScreenshot(): Promise<void> {
    let reply: RestReply;
    try {
        reply = await restRequest("GET", "/screenshot");
    } catch (error) {
        vscode.window.showErrorMessage(
            `AutoControl: REST call failed (${(error as Error).message})`,
        );
        return;
    }
    if (reply.statusCode < 200 || reply.statusCode >= 300) {
        vscode.window.showErrorMessage(
            `AutoControl: REST ${reply.statusCode}: ${reply.body.slice(0, 240)}`,
        );
        return;
    }
    const png = decodeScreenshot(reply.body);
    if (png === undefined) {
        vscode.window.showErrorMessage(
            "AutoControl: the screenshot reply did not hold a base64 PNG.",
        );
        return;
    }
    const file = nodePath.join(
        os.tmpdir(), `autocontrol-screenshot-${Date.now()}.png`,
    );
    try {
        await fs.writeFile(file, png);
        await vscode.commands.executeCommand(
            "vscode.open", vscode.Uri.file(file),
        );
    } catch (error) {
        vscode.window.showErrorMessage(
            `AutoControl: cannot show the screenshot (${(error as Error).message})`,
        );
    }
}

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

// GET /screenshot answers {"format": "png", "encoding": "base64", "data": ...}.
function decodeScreenshot(body: string): Buffer | undefined {
    let parsed: unknown;
    try {
        parsed = JSON.parse(body);
    } catch {
        return undefined;
    }
    if (typeof parsed !== "object" || parsed === null) {
        return undefined;
    }
    const reply = parsed as { format?: unknown; encoding?: unknown; data?: unknown };
    if (reply.format !== "png" || reply.encoding !== "base64"
        || typeof reply.data !== "string") {
        return undefined;
    }
    const png = Buffer.from(reply.data, "base64");
    return PNG_SIGNATURE.equals(png.subarray(0, 8)) ? png : undefined;
}

// --- Tree view ----------------------------------------------------

class ScriptStepProvider implements vscode.TreeDataProvider<StepItem> {
    private readonly emitter = new vscode.EventEmitter<StepItem | undefined>();
    readonly onDidChangeTreeData = this.emitter.event;

    refresh(): void { this.emitter.fire(undefined); }

    getTreeItem(element: StepItem): vscode.TreeItem { return element; }

    getChildren(): vscode.ProviderResult<StepItem[]> {
        const editor = vscode.window.activeTextEditor;
        if (editor?.document.languageId !== "json") {
            return [];
        }
        let parsed: unknown;
        try {
            parsed = JSON.parse(editor.document.getText());
        } catch {
            return [];
        }
        if (!Array.isArray(parsed)) { return []; }
        return parsed.map((entry, index) => {
            if (Array.isArray(entry) && typeof entry[0] === "string") {
                return new StepItem(`${index + 1}. ${entry[0]}`,
                    entry.length > 1 ? JSON.stringify(entry[1]) : "");
            }
            return new StepItem(`${index + 1}. (malformed)`,
                JSON.stringify(entry));
        });
    }
}

class StepItem extends vscode.TreeItem {
    constructor(label: string, description: string) {
        super(label, vscode.TreeItemCollapsibleState.None);
        this.description = description;
        this.tooltip = description;
    }
}
