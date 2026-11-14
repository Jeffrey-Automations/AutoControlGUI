# Installation and configuration

[README](../../../README.md) · [Documentation](../../README.md)

## Installation

```bash
pip install je_auto_control            # core
pip install je_auto_control[gui]       # + PySide6 desktop app
```

Optional extras, installed only when you need them:

| Extra | Enables |
|---|---|
| `gui` | PySide6 desktop application (51 tabs): a searchable navigation panel (`Ctrl+K`) lists every feature by category, tabs are built the first time they are opened (of the three open at start, only Record is built then; Script Builder and Remote Desktop are built when first selected), and **View → Theme** switches dark / light. Pages scroll in narrow windows; theme, text size, navigation visibility (`Ctrl+B`) and width are saved in `~/.je_auto_control/gui.ini` on close. Themes use Qt directly; `qt-material` is not required. |
| `webrtc` | WebRTC remote desktop, USB passthrough (`aiortc`, `av`) |
| `signaling` | Standalone signaling / rendezvous server (`fastapi`, `uvicorn`) |
| `discovery` | mDNS / Zeroconf LAN host discovery |
| `pdf` / `office` | PDF and Excel / Word / PowerPoint reading |
| `fuzzy` / `locale` | `rapidfuzz` matching, `babel` locale parsing |
| `s3` / `audio` | S3 artifact store, system volume control |

Closing a factory-built feature with the tab cross releases its widget, subscriptions and timers on the next Qt event-loop turn; reopening starts a new panel. **View → Tabs** and the embedding `hide_tab` API only hide it and preserve state. `tab_registry.open/close` and `close_tab` expose explicit lifecycle operations. Core pages and Remote Desktop also release on close. Shared TCP/WebSocket registry sessions remain available to scripts; page-owned WebRTC sessions are stopped in the background. Reopening creates fresh controls without reattaching an existing session. Pending approvals and late page callbacks are rejected. Widgets explicitly supplied by embedders retain their existing ownership contract.

**Windows on arm64** installs and runs, minus what upstream cannot ship
there: neither `opencv-python` nor `cryptography` publishes a `win_arm64`
wheel. So `find_image*`, `screenshot()` (the OpenCV/BGR one — the Pillow
capture still works), the secret vault, action-file encryption, ACME/TLS
and encrypted recording each raise a message naming the missing wheel
instead of failing obscurely. Mouse, keyboard, screen size, window
management, the accessibility tree, the action executor, the MCP/REST/TCP
servers and the GUI all work — measured, not assumed. Every other platform
is unaffected.

**Requirements:** Python ≥ 3.11. On Linux, install build
prerequisites first:

```bash
sudo apt-get install cmake libssl-dev
```

OCR, VLM, and LLM backends (`pytesseract`, `easyocr`, `paddleocr`, `anthropic`,
`openai`) are loaded on demand — install whichever you actually use. For Tesseract,
`find_tesseract_cmd()` locates the executable (`$TESSERACT_CMD`, then `PATH`, then the
installers' default folders), `set_tessdata_dir()` points it at a language-data folder,
and `ocr_status()` / `ocr_languages()` say what is missing before the first OCR call.

**Log file:** the library logs to `~/.je_auto_control/logs/AutoControlGUI.log`,
created on the first record (importing alone writes nothing) and shared by every
process on the account (appended to, one process id per line, moved to `.1`
past 10 MB). Set `JE_AUTOCONTROL_LOG_FILE` to write elsewhere, or to
`os.devnull` to turn the file off.

---

## Platform support

| Platform | Backend | Input | Screen capture | Recording | Window management |
|---|---|:---:|:---:|:---:|:---:|
| Windows 10 / 11 | Win32 ctypes (+ optional Interception driver) | ✅ | ✅ | ✅ | ✅ |
| macOS 10.15+ | pyobjc / Quartz | ✅ | ✅ | ✅¹ | ✅ |
| Linux X11 | python-Xlib (+ optional `uinput`) | ✅ | ✅ | ✅ | ✅ |
| Linux Wayland | libei via the desktop portal, or ydotool / wtype + a capture tool | ✅ | ✅ | ❌ | ❌ |
| FreeBSD / OpenBSD / NetBSD | python-Xlib, the same X11 backend as Linux | ✅² | ⚠️² | ✅² | ✅² |
| Android | adb + uiautomator2 | ✅ | ✅ | — | — |
| iOS | WebDriverAgent / facebook-wda | ✅ | ✅ | — | — |

¹ macOS recording captures through a Quartz event tap and needs
**Accessibility** permission (System Settings → Privacy & Security →
Accessibility). Without it recording raises and names the permission
rather than returning an empty session.

² The BSDs run the X11 backend unchanged — the same X server, the same
`python-Xlib`, which is the only dependency input, recording and window
management have. A `freebsd` CI job drives real input on a real FreeBSD 14 and
reads it back off the X server; OpenBSD and NetBSD take the same code path but
have no CI runner. Screen capture is the exception, and the reason is
packaging rather than the platform: it goes through Pillow/mss and OpenCV, and
`opencv-python`, `pillow` and `cryptography` publish no FreeBSD wheels. Build
those from ports and capture, image matching, OCR and action encryption work
too — `import je_auto_control` no longer requires any of them.

Wayland key/button/pointer input in `auto` mode uses CLI when the optional native
backend is absent. Once a portal request starts, refusal, timeout, handshake
failure, device pause or revocation stops input; it never silently switches
providers. Repeated refused calls retain inert failure state without reopening
consent. `JE_AUTOCONTROL_WAYLAND_INPUT_BACKEND=libei` requires native input;
`=cli` explicitly selects CLI. After resolving permission, an explicit
`je_auto_control.linux_wayland.libei.reset_default_backend()` allows a fresh
request. Interrupted native chords attempt all owned key releases on the same
backend and preserve the original cancellation. This does not change the
explicit wtype text path or screen-capture selection.

The `ydotool` fallback needs **ydotool 1.0 or newer**. Every argument
AutoControl builds arrived in that release; 0.1.x — which is what Debian
bookworm and every current Ubuntu still ship under that name, and Debian
trixie ships not at all — answers the same arguments with exit code 0 and no
events. AutoControl detects it and refuses rather than reporting success for
input it never sent. Arch, Fedora and Debian unstable package 1.0.

That fallback also positions the pointer accurately **only where the
compositor's pointer acceleration is off**. `ydotool mousemove --absolute`
sends no absolute event: it drives the cursor into the corner the compositor
clamps to and then moves relative to it, so the compositor accelerates the
move — measured against a real wlroots session, libinput's default profile
travels exactly twice the distance asked for. ydotool's own `--help` says the
same; AutoControl logs it once per process rather than mispositioning in
silence. Turn acceleration off for the ydotoold device (sway: `input
type:pointer accel_profile flat` and `pointer_accel 0`), or install
`liboeffis` so the libei path — absolute at the protocol level — is used.

The factor is the compositor's own setting and no client can read it back, so
only you know whether it is off. `JE_AUTOCONTROL_WAYLAND_POINTER_ACCEL=flat`
says it is, and moves silently; `=strict` refuses the move rather than let a
click land somewhere else; leaving it unset keeps the warn-and-move default.

Wayland screen capture needs the tool your compositor supports, because no
single one covers them all: `grim` on wlroots compositors (sway, Hyprland,
river), `gnome-screenshot` on GNOME, `spectacle` on KDE. Install one and every
capture path — screenshots, image and anchor locators, OCR, screen recording,
remote desktop — goes through it. With none installed, a session bus is
enough: the built-in D-Bus client tries `xdg-desktop-portal` last, though it may ask for consent the
first time. Failing that, capture fails loudly with an install hint rather than
returning the blank XWayland root. The `screen_capture` check in
`je_auto_control.api.run_diagnostics()` (and the GUI Diagnostics tab) reports
which tier is in use.

A native Wayland pointer coordinate outside every granted EIS region, after
raw-coordinate and layout-origin mapping, raises `LibeiUnavailable` with
`state="failed"` and disables automatic CLI fallback. A rejected move emits
no motion/frame or subsequent click. Valid coordinates, devices without
regions, later valid requests on the same sender and explicit CLI selection
retain their existing behavior.

Passive **input/capture capabilities** use `BackendContext`, `CapabilityStatus`,
`CapabilitySnapshot` and `probe_capabilities` from `je_auto_control.api` (also
exported at the package root). Call
`probe_capabilities(BackendContext.current()).to_dict()`, use no-argument
`AC_probe_capabilities` / read-only `ac_probe_capabilities`, or choose
**Diagnostics → Actions → Inspect input and capture capabilities**. Builder
provides the same no-argument command. `python -m examples.capabilities` prints
live prerequisites and a deterministic XWayland scope example without desktop operations.

Input describes key/pointer events; the existing wtype text path is separate.
The probe reads environment/PATH and nonblocking cached native state; it never
loads optional native libraries, connects, polls events, captures or requests
permission. Installed tools or a bus address mean `unverified`, not readiness.
Cached libei readiness requires a completed handshake and active keyboard,
absolute pointer, button and scroll families. A partial grant remains
unverified; paused families and removed required devices report paused/revoked.
The eight states are `available`, `unverified`, `needs_permission`,
`needs_dependency`, `unsupported`, `paused`, `revoked` and `failed`.
`available` is only the last local observation and may be stale; every real
operation rechecks authority. XWayland always has `desktop_wide=False` and cannot
cover native Wayland windows. Other scope flags remain subject to granted
regions/permissions and do not verify every monitor.

Contexts detach environment/executable facts and may carry an owner's inert
input/capture observations. They grant no authority. Default live results omit
environment values, command arguments, executable paths and native error text;
AC/MCP accept no supplied observations. Explicit CLI configuration remains
distinct from automatic fallback after observed optional native absence;
permission/pause/revocation/failure metadata cannot imply CLI fallback.
Capture helper and portal selection are diagnosed independently. Rendering and
language changes reuse the snapshot without probing. Native portal restore,
compositor restart, capture-result/context integration and native session
controls remain in `Progress.md`.

The GUI task infrastructure provides `gui.task_controller.TaskController`:
`submit(work, owner=widget)` returns a caller-owned `TaskHandle` with
typed `TaskOutcome` and `TaskProgress` observations. Work receives a
Qt-free `CancellationToken` with checkpoints, bounded interruptible waits
and progress reporting. Submission captures context; dispatch refreshes
store-backed identity. Work must receive plain data, avoid widget references
and authorize its own operation. Existing
`DeferredAuthorization.scope()` still requires input privilege, while
`context_scope()` only refreshes/binds identity for independently authorized work.

Owner/handle/controller destruction requests cooperative stop and drops
late delivery. Each task has a separate ID/token; callbacks run on the GUI
thread. Cancellation does not forcibly interrupt an uncooperative call
or relabel a successful committed return. Errors/progress use the captured
secret scope; terminal errors retain no exception traceback. Failed thread
starts roll back both registries and preserve the original failure.
Diagnostics now adopts this controller. Remaining panel/backend migrations
and native session operations stay in `Progress.md`.

Active **Diagnostics → Actions → Run diagnostics** uses the shared task
controller off the GUI thread. **Stop diagnostics** requests cooperative stop;
the view distinguishes running, stopping, canceled and failed states in four
languages. Progress counts completed checks. Duplicate runs are ignored, close
abandons late progress/results, and a deliberate retry starts a new owned run.
GUI cancellation is a typed outcome without retained exception tracebacks;
headless core/SDK/CLI and the MCP handler preserve original direct/wrapped controls.
Ordinary probe failures still become report rows and allow remaining checks.

`CancellationToken`, `TaskProgress` and `cancellation_scope` are exported by both
SDK namespaces. Bind `with cancellation_scope(token): report = run_diagnostics()`;
the owning caller can call `token.cancel()` from another thread. The existing
no-argument diagnostics signature remains. Scope binding grants no authority;
`cancellation_scope(None)` only suspends cancellation for bounded owned cleanup.
`AC_diagnose` and the new read-only `ac_diagnose` share the report. The MCP tool
accepts no arguments, uses request cancellation/progress and requires
`read_screen`, as does the explicit GUI action. Caller-supplied tokens or
authority metadata are rejected. These are active checks: capture may request
consent. `ac_probe_capabilities` remains the separate passive alternative.

Scoped Wayland D-Bus connect/read/partial-write waits poll at intervals capped
at 0.1s within the original total deadline. Cancellation attempts Request.Close
on the originating bus with its separate 0.25s budget, then releases that
connection; a canceled returned image is discarded. Scoped CLI captures stop
and reap their newly owned helper/process group with bounded cleanup, preserving
the original control even if pipe close fails; reaped numeric PIDs are never
signaled. liboeffis acquisition observes scoped stop and releases its own context.
Uncooperative/native calls are not forcibly preempted; the GUI remains responsive
while cleanup completes. Restore/restart, native session controls, capture-owner
metadata and remaining panel/backend migrations stay in `Progress.md`.

`python -m examples.cancellable_diagnostics` runs a controlled cancellation demo
without providers. `--active --cancel-after 2` explicitly runs diagnostics and
requests stop after two seconds; native/device/API acceptance remains separate.

Opening Diagnostics displays a localized not-run state and performs no checks.
Choose **Actions → Run diagnostics** to start the existing active checks, which
can capture the screen or require portal consent. Changing the display language
does not start checks. The explicit `run_diagnostics`, `AC_diagnose` and MCP
diagnostic calls retain their active behavior. Passive capability inspection is a separate action below.

Abandoned screenshot portal requests attempt `Request.Close` on the originating
bus before disconnect, using a separate 0.25-second D-Bus I/O budget. A returned
alternate handle is followed; after an uncertain method reply, the predicted
handle is used. Completed responses are not closed again. Ordinary cleanup
errors do not replace the primary capture failure; original cancellation and
hard-control objects survive wrappers and cleanup. D-Bus writes and reply waits
share the call budget, connection setup has an explicit timeout, and interrupted
connect/authentication/Hello releases its owned descriptor even when `__enter__`
fails. Actual compositor/dialog cancellation remains platform acceptance work.

One Wayland-only difference to plan around: **a capture may contain the mouse
cursor.** Nothing here asks for it, but wlroots composites a *software* cursor
into the output buffer whenever the backend has no cursor plane — which
includes any session run with `WLR_NO_HARDWARE_CURSORS=1` — and that buffer is
what screen capture hands back. Windows and X11 never include the pointer, so a
locator, a template match or an OCR read can find a pointer-shaped hole in the
middle of its target here and nowhere else. Wayland does not let a client read
the cursor position, so there is nothing to reliably mask or move around it:
park the pointer away from what you are about to capture. The `screen_capture`
check reports this as `cursor_may_be_captured`.

For a setup none of that fits, name your own command — it wins over every
detected tool, and `{output}` is replaced with a temporary PNG path:

```bash
export JE_AUTOCONTROL_WAYLAND_CAPTURE_COMMAND="mycapture --png {output}"
```

Wayland forbids global input recording for unprivileged clients — set
`JE_AUTOCONTROL_LINUX_DISPLAY_SERVER=x11` to record on an X11 session. Window
management works on Windows, macOS (pyobjc) and X11, including XWayland; on a pure
Wayland session, whose protocol hides other clients' windows, `list_windows()` returns
an empty list and every window action raises `AutoControlUnsupportedOperationException`
saying why. Opt-in driver-level backends (`JE_AUTOCONTROL_WIN32_BACKEND=interception`,
`JE_AUTOCONTROL_LINUX_BACKEND=uinput`, ViGEm virtual gamepad) exist for apps that
ignore synthetic input, and fall back silently when the driver is absent.

---

## Configuration

Every environment variable AutoControl reads. Nothing here is required: with no variable set, AutoControl picks the platform backend by itself, servers bind `127.0.0.1`, and every opt-in feature (signature enforcement, RBAC, USB passthrough, tool-path roots) is off. The [configuration reference](https://autocontrol.readthedocs.io/en/latest/Eng/doc/configuration/configuration_doc.html) ([source](../../source/Eng/doc/configuration/configuration_doc.rst)) has the accepted values in full and links each variable to the page that explains the feature; CI compares it, and the tables below, with the code.

### Platform backends

| Variable | Default | Effect |
|---|---|---|
| `JE_AUTOCONTROL_WIN32_BACKEND` | `sendinput` | `interception` sends keyboard and mouse through the Interception driver; falls back to `SendInput` with a warning when the driver or DLL is missing. |
| `JE_AUTOCONTROL_LINUX_BACKEND` | `x11` | `uinput` writes kernel input events; falls back to XTest with a warning when `/dev/uinput` is not writable. |
| `JE_AUTOCONTROL_LINUX_DISPLAY_SERVER` | `auto` | Which Linux backend loads: `auto` reads `XDG_SESSION_TYPE` and `WAYLAND_DISPLAY`; `wayland` or `x11` forces one (`x11` on a Wayland session drives XWayland windows only). |

### Windows Interception driver

| Variable | Default | Effect |
|---|---|---|
| `JE_AUTOCONTROL_INTERCEPTION_DLL` | unset: `PATH`, then next to the package | Full path of `interception.dll`. |
| `JE_AUTOCONTROL_INTERCEPTION_KEYBOARD` | `1` | Interception device id (`1`–`10`) keyboard events are sent to. |
| `JE_AUTOCONTROL_INTERCEPTION_MOUSE` | `11` | Interception device id (`11`–`20`) mouse events are sent to. |

### Wayland

| Variable | Default | Effect |
|---|---|---|
| `JE_AUTOCONTROL_WAYLAND_INPUT_BACKEND` | `auto` | `cli` sends input through `ydotool` and never asks the desktop portal. Chosen before starting: after a refused consent AutoControl does not switch to it by itself. |
| `JE_AUTOCONTROL_WAYLAND_POINTER_ACCEL` | `warn` | Absolute moves on the `ydotool` path only (relative motion the compositor accelerates): `warn` warns once and moves, `flat` declares acceleration off and moves silently, `strict` refuses the move. |
| `JE_AUTOCONTROL_WAYLAND_CAPTURE_COMMAND` | unset | Your own screenshot command line, with `{output}` where the PNG path goes. Takes precedence over `grim`, `gnome-screenshot`, `spectacle` and the portal. |
| `JE_AUTOCONTROL_WAYLAND_RECORD_DEVICES` | unset: none | Comma-separated `/dev/input/event*` devices `PhysicalRecorder` may read; physical recording is opt-in per device. |

### MCP server

| Variable | Default | Effect |
|---|---|---|
| `JE_AUTOCONTROL_MCP_READONLY` | unset | `1`: only tools marked read-only are offered and callable. |
| `JE_AUTOCONTROL_MCP_TOOL_PROFILE` | unset | Comma-separated tool names and `category:<name>` entries of the `static` profile. |
| `JE_AUTOCONTROL_MCP_ALIASES` | `1` | `0` leaves out the short aliases (`click`, `screenshot`, …) registered beside the `ac_*` tools. |
| `JE_AUTOCONTROL_MCP_TOKEN` | unset | Bearer token of the HTTP transport. Not accepted once RBAC is on. |
| `JE_AUTOCONTROL_MCP_ALLOWED_ORIGINS` | unset: loopback origins only | Comma-separated extra browser origins (exact, e.g. `https://example.test:8443`) the HTTP transport accepts. |
| `JE_AUTOCONTROL_MCP_CONFIRM_DESTRUCTIVE` | unset | `1`: destructive tools ask the client for confirmation (MCP elicitation) before they run. |
| `JE_AUTOCONTROL_MCP_PATH_ROOTS` | unset: no confinement | Directories (separated by the OS path separator) every file argument of a tool must stay inside. |
| `JE_AUTOCONTROL_MCP_PATH_ROOTS_FROM_CLIENT` | unset | `1`: also accept the roots the MCP client reports through `roots/list`. |
| `JE_AUTOCONTROL_MCP_ENV_REF_ALLOW` | unset: no restriction | Comma-separated environment variable names (`fnmatch` patterns allowed) `ac_resolve_ref` may read; a value that names nothing allows none. |
| `JE_AUTOCONTROL_MCP_AUDIT` | unset | Path of a JSON-lines file that receives one record per `tools/call`. |
| `JE_AUTOCONTROL_MCP_ERROR_SHOTS` | unset | Directory a screenshot is saved to each time a tool fails. |
| `JE_AUTOCONTROL_FAKE_BACKEND` | unset | `1`: the MCP server records mouse, keyboard and clipboard calls in memory instead of performing them, for CI without a display. |

### REST / RBAC and chat-ops

| Variable | Default | Effect |
|---|---|---|
| `JE_AUTOCONTROL_RBAC_USERS` | unset: shared token | Path of the user store file. Setting it is what switches roles on for the REST API and the MCP HTTP transport. |
| `JE_AUTOCONTROL_CHATOPS_SCRIPT_ROOT` | unset: `run` is refused | The only directory the chat-ops `run` command may load action files from. |

### Executing and signing action files

| Variable | Default | Effect |
|---|---|---|
| `JE_AUTOCONTROL_ALLOWED_PACKAGES` | unset: none | Comma-separated packages `AC_add_package_to_executor` may load (submodules included), for every entry point. Read once, when the process starts. |
| `JE_AUTOCONTROL_REQUIRE_SIGNED_ACTIONS` | unset | `1`: every path that runs an action file refuses one without a valid signature sidecar. |
| `JE_AUTOCONTROL_ACTION_SIGNING_PRIVATE_KEY` | unset | Path of the Ed25519 private key (PEM). Set it on the signing machine only; signing then writes a version-2 sidecar. |
| `JE_AUTOCONTROL_ACTION_SIGNING_PUBLIC_KEY` | unset | Path of the matching public key. Set it on every machine that executes: it verifies and cannot sign. |
| `JE_AUTOCONTROL_ACTION_SIGNING_PASSPHRASE` | unset | Passphrase of the private key, when it was created with one. |
| `JE_AUTOCONTROL_ACCEPT_LEGACY_ACTION_SIGNATURES` | unset | `1` is migration mode: once a public key is configured, HMAC sidecars written before version 2 are refused unless this is set. Switch it off again when every file has been re-signed. |

### Remote desktop and signaling

| Variable | Default | Effect |
|---|---|---|
| `JE_AUTOCONTROL_REMOTE_DOWNLOAD_DIR` | `~/Downloads/AutoControl` | Directory a remote-desktop viewer stores files its host sends in. A received path is confined to it. |
| `JE_AUTOCONTROL_USB_PASSTHROUGH` | unset | `1` enables USB passthrough opcodes on the remote-desktop channel. |
| `AC_SIGNALING_SECRET` | unset | Shared secret of the signaling / config-sync server (`X-Signaling-Secret`). Read by the server when `--shared-secret` is not given. |

### GUI

| Variable | Default | Effect |
|---|---|---|

### Logging, data and testing

| Variable | Default | Effect |
|---|---|---|
| `JE_AUTOCONTROL_LOG_FILE` | `~/.je_auto_control/logs/AutoControlGUI.log` | Where the log file is written. The null device (`/dev/null`, `NUL`) switches the file off. Read when the first record is written, not at import. |
| `JE_AUTOCONTROL_ENV` | `default` | The active environment of the asset store (`active_environment()`), so one script reads different values in `dev` and `prod`. |
| `JE_AUTOCONTROL_REDACTION` | `off` | Default screenshot redaction policy: `off`, `moderate` or `strict`. An unknown name is an error, not `off`. |
| `JE_AUTOCONTROL_PYTEST_ARTIFACTS` | `./autocontrol_screenshots` | Directory the pytest plugin writes failure screenshots to when a test did not request the `autocontrol_screenshot_dir` fixture. |

---

The Report page is created when first opened. Closing it releases its controls and local result view; reopening creates a fresh page and reads the current recording status. Closing the page does not disable the shared recorder.

Report generation runs in the background and shows a running status. A page accepts one generation at a time and captures the name when you start it. Closing drops late results; an already-running file write may still finish.

The Screenshot page is also created on first open and released on close. Screen-size queries, captures and pixel reads run in the background with a running status and one operation at a time. Inputs are captured when the operation starts. Closing discards late results; a capture already in progress may still write its file. Hiding preserves the page. Region picking and file browsing remain explicit interactive actions.
