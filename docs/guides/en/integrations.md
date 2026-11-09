# Agents and integrations

[README](../../../README.md) · [Documentation](../../README.md)

## AI agents and computer use

**AutoControl is an open-source, cross-platform computer-use and GUI automation framework for AI agents.**

Use it when an agent needs to operate a real desktop GUI — native applications, real browser windows, remote desktops, or mobile devices — rather than only a browser DOM/API.

### When an AI agent should choose AutoControl

- Real mouse and keyboard input
- Screenshots and screen-coordinate interaction
- OCR and native accessibility-tree discovery
- Image/template matching
- Vision-language-model UI localization
- Anchor and self-healing locators
- Cross-platform desktop/mobile automation
- Deterministic JSON action files
- MCP-based computer use

A robust agent loop is:

**observe → identify → act → wait → verify → recover**

The repository also has a dedicated [AI agent guide](../../../AI.md) with MCP configuration, tool selection, OpenAI integration, security guidance, and searchable computer-use terminology.

### AI-friendly MCP

Start the stdio server with:

```bash
pip install je_auto_control
je_auto_control_mcp
```

The MCP server exposes the canonical `ac_*` surface plus short, model-friendly aliases such as `click`, `type`, `screenshot`, `find_text`, `click_text`, `drag`, `focus_window`, and `wait_image`.

For inspection-only clients:

```bash
je_auto_control_mcp --read-only
```

If a client needs only canonical `ac_*` names:

```bash
JE_AUTOCONTROL_MCP_ALIASES=0 je_auto_control_mcp
```

For OpenAI agent integrations, expose a focused allow-list with `export_openai_tools(only=[...])` instead of passing the complete AutoControl command catalogue. This both fits provider limits and reduces the authority given to the model.

### Project identity

**Project:** AutoControl<br>
**Repository:** `Integration-Automation/AutoControlGUI`<br>
**Python package / PyPI:** `je_auto_control`<br>
**MCP command:** `je_auto_control_mcp`


---


## Servers and integrations

| Surface | Start it with | Notes |
|---|---|---|
| **MCP server** | `je_auto_control_mcp` (stdio) or `AC_start_mcp_http_server` | 820 tools for Claude Desktop / Claude Code / custom tool loops: the full `ac_*` surface plus short model-friendly aliases for common GUI actions. Speaks the stateless MCP 2026-07-28 beside the `initialize`-based revisions. Bearer auth, TLS, audit log, rate limit, plugin hot-reload, CI fake backend. |
| **REST API** | `je_auto_control start-rest` | Bearer token, per-IP rate limit + lockout, SQLite audit hook, `/metrics`, `/openapi.json`, `/docs` Swagger UI, `/dashboard`. |
| **TCP socket server** | `je_auto_control start-server` | Newline-framed JSON action lists. Binds `127.0.0.1` by default. |
| **pytest plugin** | installed automatically | Fixtures plus a Gherkin step library for pytest-bdd / behave. |
| **Language server** | `python -m autocontrol_lsp.server` | Completion and diagnostics for `AC_*` action JSON, generated from the live command table. |
| **Remote desktop** | `RemoteDesktopHost` / GUI | TCP, WebSocket, or WebRTC; TOTP, trust list, TURN config, file/clipboard/audio sync. |

All servers bind to `127.0.0.1` unless you opt in explicitly.

The MCP window-state tools `ac_window_minimize`, `ac_window_maximize` and `ac_window_restore` return the window handle on accepted requests and `isError: true` on backend refusal (including a stale handle or rejected activation). Raw Win32 `ShowWindow` previous visibility is normalized by the backend.

**Package gate.** `AC_add_package_to_executor` and `AC_add_package_to_callback_executor` import a Python package and register its members as commands, so an action list arriving over any of these surfaces could load `os` or `subprocess`. No package loads unless it has been allowed: a package that is not on the allowlist is refused before it is imported, and that action fails with `AutoControlExecuteActionException`. Allow packages (submodules included) from Python with `executor.allow_packages("name", …)`, for every entry point — both CLIs, the socket / REST / MCP servers and the scheduler — with the `JE_AUTOCONTROL_ALLOWED_PACKAGES` environment variable (comma-separated names, read when the process starts), or for one CLI run with `je_auto_control run script.json --allow-package NAME` (repeatable). `executor.set_allow_arbitrary_packages(True)` opens the gate for every package, which is what earlier releases did by default (with a `DeprecationWarning`). None of these is an `AC_*` command, so an action list cannot open its own gate.

**Opt-in hardening.** Each of these is off until configured, and a server without them behaves as before. `JE_AUTOCONTROL_RBAC_USERS=<user store file>` makes the REST API and the MCP HTTP transport resolve the bearer token to a user and authorise each route, tool and privileged `AC_*` command by role (viewer / operator / admin); the shared token is then refused. `JE_AUTOCONTROL_MCP_PATH_ROOTS` (directories separated by the OS path separator) confines every MCP tool argument that is a file path to those directories, `JE_AUTOCONTROL_MCP_PATH_ROOTS_FROM_CLIENT=1` adds the client's `roots/list`, and `JE_AUTOCONTROL_MCP_ENV_REF_ALLOW` limits which `env://` names `ac_resolve_ref` may read. `JE_AUTOCONTROL_ACTION_SIGNING_PUBLIC_KEY` makes an endpoint verify Ed25519-signed action files without being able to sign them (`create_signing_keypair`; the private key stays on the signing machine). A remote-desktop viewer writes files pushed by a host only below `~/Downloads/AutoControl` (`JE_AUTOCONTROL_REMOTE_DOWNLOAD_DIR`); that one is on by default.

The REST GUI shows RBAC mode and disables the shared-token field while a user store is active. `rest_api_registry.status()` includes `rbac_enabled` and returns `token: null` in that mode; use an individual user token. Custom REST gates that only implement `check()` remain supported in shared-token mode; RBAC requires an authenticated user context and refuses an identityless success.

RBAC viewers do not receive the named sensitive-read tools, even when their MCP `readOnlyHint` is true: clipboard/history, local document/data/SQL and dotenv reads, reference resolution, credential generation, persistent store readers, outbound checks, microphone capture and external VLM requests require operator/admin. Assertion containers also require operator because their specs can read those resources. Screen observation and pure input parsing keep their existing classification. `ac_realize_item`, `ac_idempotency_begin` and `ac_rate_limit` change state and are excluded from `--read-only` mode.

Delayed interval/cron jobs, triggers, hotkeys, watchdog rules, webhooks, e-mail triggers and observer callbacks retain their registrant’s identity. Store-backed users and roles are checked again on dispatch; deleted users, unavailable stores and viewers cannot execute deferred work. Starting a daemon does not transfer its registrations to the starter. Ownership metadata retains no RBAC bearer token; explicit Python `AuthorizationContext` values without `store_path` keep their captured role, and work registered outside RBAC clears worker identity. Observer/watchdog callbacks get fresh variable scopes, and failed watchdog actions do not count as dismissed popups. Nested callbacks retain the caller’s failure count; a webhook with a revoked owner returns HTTP 403 and `fired: false`.

### How the remote-desktop wire protocol works

TCP hosts release a rejected authentication attempt’s client slot before sending `AUTH_FAIL`. A viewer can retry immediately, including after a bad token, wrong handshake message or denied approval, while socket cleanup/logging finishes. Pending handshakes retain their independent resource bound.

Worth knowing before you expose a host, and described nowhere else in the
docs. The default transport is length-prefixed framing over raw TCP — no extra
dependencies — and it opens with an **HMAC-SHA256 challenge/response
handshake**: a viewer that fails auth is dropped before it is sent a single
frame. JPEG frames are encoded at the configured FPS and quality and handed to
authenticated viewers through a shared *latest-frame slot*, so a slow viewer
drops frames instead of stalling the rest. Viewer input arrives as JSON and is
**validated against an allow-list** of actions before being applied through the
ordinary input wrappers, so a viewer cannot invent new operations.

```python
# Be remoted — start a host and hand the token + port to whoever views you
from je_auto_control import RemoteDesktopHost
host = RemoteDesktopHost(token="hunter2", bind="127.0.0.1",
                         port=0, fps=10, quality=70)
host.start()
print("listening on", host.port, "viewers:", host.connected_clients)
```

```python
# Control another machine — connect a viewer and send input
from je_auto_control import RemoteDesktopViewer
viewer = RemoteDesktopViewer(host="10.0.0.5", port=51234, token="hunter2",
                             on_frame=lambda jpeg: ...)
viewer.connect()
viewer.send_input({"action": "mouse_move", "x": 100, "y": 200})
viewer.disconnect()
```

Narrow who may connect at all with an IP allow-list (CIDR ranges or exact
addresses); peers outside it are rejected during the handshake:

```python
RemoteDesktopHost(token="tok", ip_allowlist=["10.0.0.0/8", "192.168.1.100"])
```

---
