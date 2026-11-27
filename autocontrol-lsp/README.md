# autocontrol-lsp

Language server + VSCode extension for AutoControl action-JSON files
(`AC_*` commands).

This is a scaffold — the LSP server delivers **completion** for every
known `AC_*` command name and **hover** for the command's docstring.
Diagnostics (parameter validation), go-to-definition, and signature
help are wired but stubbed; flesh them out in follow-up PRs.

## Layout

```
autocontrol-lsp/
├── README.md                — this file
├── server/                  — Python LSP server (stdlib JSON-RPC over stdio)
│   ├── server.py            — entry point: ``python -m server``
│   ├── handlers.py          — initialize / completion / hover handlers
│   └── commands.py          — AC_* discovery via importlib
└── vscode/                  — VSCode extension manifest
    ├── package.json         — extension metadata + activation events
    └── src/extension.ts     — extension entry, launches the LSP server
```

## Running the LSP server standalone

```bash
python -m autocontrol_lsp.server  # JSON-RPC over stdio
```

Editors that speak LSP (VSCode, Neovim, Helix, Emacs) can be pointed
at that command via their own client config.

## Building the VSCode extension

```bash
cd autocontrol-lsp/vscode
npm install
npm run build          # esbuild → dist/extension.js
vsce package           # produces a .vsix
code --install-extension autocontrol-lsp-0.1.0.vsix
```

The language server only diagnoses **action files**: documents whose
absolute path matches one of the `autocontrolLsp.actionFiles` globs
(default `**/*.ac.json` and `**/actions/**/*.json`). Other JSON and
JSONC files such as `package.json`, `tsconfig.json` or a commented
`settings.json` are left alone. Add your own patterns (for example
`**/keyword/*.json`) and reload the window. The extension sends the
setting as the `actionFiles` initialization option, and the server
applies the same globs as a guard, so other LSP clients can pass
`{"actionFiles": [...]}` too; without it the server uses the defaults.

## Why a sibling project

The LSP server only needs `je_auto_control` to introspect the list of
commands; it doesn't pull in PyQt or the platform mouse / keyboard
backends. Keeping it in `autocontrol-lsp/` rather than
`je_auto_control/utils/lsp/` keeps the import surface clean (the LSP
process doesn't load the GUI, the GUI doesn't load the LSP).

When the scaffold matures, this directory can be lifted into a
standalone Git repo (`autocontrol-lsp`) and published as both a
PyPI package (`pip install autocontrol-lsp`) and a VSCode extension
on the Marketplace.
