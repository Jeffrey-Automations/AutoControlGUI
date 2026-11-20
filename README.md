# AutoControl

[English](README.md) | [繁體中文](README/README_zh-TW.md) | [简体中文](README/README_zh-CN.md)

AutoControl is a Python framework for automating desktop applications. Control the mouse and keyboard, capture screens, and find interface elements with images, OCR or accessibility APIs. Use it from Python, JSON action files, the desktop GUI or an MCP client.

## Get started

Requires Python 3.11 or later.

```bash
python -m pip install je_auto_control
```

Read the screen dimensions without sending input:

```python
import je_auto_control as ac

print(ac.screen_size())
```

To use the desktop app:

```bash
python -m pip install "je_auto_control[gui]"
python -c "import je_auto_control; je_auto_control.start_autocontrol_gui()"
```

While the window is open, the app collects Python's cyclic garbage on the GUI thread, from a timer, with automatic collection switched off; it is switched back on when the app quits. This keeps a worker thread from reaching a Qt object that PySide6 6.12 would then delete late, which has aborted the process on Windows. Scripts that only `import je_auto_control` are unaffected.

## What you can do

- Automate mouse, keyboard and window operations.
- Locate controls with image matching, OCR, accessibility APIs or optional vision models.
- Save repeatable workflows as JSON action files.
- Connect AI clients through MCP, or integrate through REST and Python.
- Use recording, scheduling and remote-desktop tools through the optional GUI.

The Image Detection page runs matching in the background and owns its mouse-button selection.
Its Actions menu can stop a pending search; closing the page discards late results and reopening resets its inputs.
Cancellation prevents later move/click steps, but cannot interrupt a native call already in progress.

Auto Click, Record and Script Executor own their controls and background tasks. Closing them stops local work; reopening creates fresh inputs. The shared recorder continues after its page closes, and a reopened page reads backend status (unknown when unsupported). This status does not verify native hook health. Ctrl+4 still stops scripts and auto-clicking.

Of the three tabs open at start, only Record is built then; Script Builder and Remote Desktop are built the first time they are selected, which roughly halves start-up time and memory.

View → Execution details (Ctrl+Shift+D) opens a collapsible right pane. Diagnostics publishes its actual progress, stop, result and error state there, and so does every other page that runs work in the background (a model request, a USB listing, a broadcast, a DAG run, a journal read): running, stopping, then completed, cancelled or the error, with progress where the work reports it. A page that has run nothing yet says details are unavailable. A background stop that fails (a session, recorder or host a page let go of) is kept rather than only logged: Diagnostics lists each one with its error, and Actions › Retry failed stops runs them again under the authority they were queued with. Switching or closing a page disconnects its updates. Embedders can supply a TabRegistry to WorkspaceShell; AutoControlGUIWidget(parent) remains supported.

Every page opens with a title and a one-line description, groups its controls on cards, and draws check boxes and radio buttons in the theme's accent so they stay visible in the dark theme. Controls shrink with the window instead of forcing it wide: long drop-down entries no longer set a page's width, form labels move above their fields when both do not fit, and long notes wrap. An empty table, list or tree says *Nothing to show yet* until its first row arrives, instead of showing a blank grid. A banner under the page title says when the page's last run failed (the next run clears it) and, when the GUI runs inside an RBAC scope, which of the page's commands the active role cannot run; it has a Dismiss link. The window rearranges itself by width: from 1,200 px the navigation and the execution details sit beside the tabs; below that the details open as a drawer over them; below 800 px the navigation becomes a narrow rail, and its menu button or Ctrl+K opens the feature list as a drawer (Escape or a click beside it closes it). Hiding the navigation for width does not change the saved preference.

WebRTC statistics polling starts in the background and discards late samples after it stops.

Windows, macOS, X11 and Wayland use different backends. Available features depend on system permissions and optional dependencies; Windows ARM64 has additional limitations. See the installation guide before choosing a deployment target.

Wayland NORMAL input runs libei and portal calls in an owned helper process. Timeouts, cancellation and uncertain replies retire that helper without replay or automatic provider fallback. The direct `LibeiBackend` API remains in-process. Helper retirement is not proof that a compositor released input; native acceptance remains pending.

Managed agent tasks and cross-host transfers include experimental features. See the implementation notes and project progress before relying on them in production.

Host-selected semantic targets support a `semantic` completion condition that compares fresh state with the recorded target identity and expected fields. It does not grant memory access or enable a native target. See [semantic completion](docs/process_memory_contract.md#semantic-completion).

## Documentation

- [Installation, platform support and configuration](docs/guides/en/setup.md)
- [Python, JSON and command-line usage](docs/guides/en/usage.md)
- [AI agents, MCP and server integrations](docs/guides/en/integrations.md)
- [Completion verification and evidence handoffs](docs/guides/en/evidence.md)
- [Development and resources](docs/guides/en/development.md)
- [Implementation notes](docs/guides/en/implementation-notes.md)
- [Documentation index](docs/README.md)
- [Examples](examples/README.md)
- [Progress](Progress.md)

## License

[MIT](LICENSE) © JE-Chen. [Third-party licenses](Third_Party_License.md).

Closing Remote Desktop releases its page. Reopening creates fresh controls without reattaching shared sessions. Registry TCP/WebSocket sessions remain available to scripts; page-owned WebRTC sessions and audio retire in the background. Pending approvals are denied, and late callbacks are discarded. A file transfer already sending stops at its next chunk when the page closes, the session is dropped or the upload is cancelled, and the host discards the partial file (TCP, WebSocket and WebRTC alike).

WebRTC host/viewer `stop()` waits up to three seconds for software teardown. `PeerStopPending` retains the same running attempt; explicit retry waits on it. `PeerStopFailed` retains failed resources for explicit retry, and restarting is blocked until cleanup succeeds. Multi-viewer hosts retain failed sessions and their shared source. `FolderSyncEngine.stop_confirmed()` returns `False` while the original worker remains alive. These outcomes do not prove native device release; recovery after page destruction still needs durable ownership and retry integration.

Host-requested file sends remain owned until their sender worker exits, including after repeated stop requests. Stop signals cancellation and waits for that original worker; an uninterruptible backend operation can still leave stop pending.

MCP read-only hints do not grant viewer access. Reviewed live-screen and caller-data tools use `read_screen`; stored files, device data and unknown tools require `read_data`. Aliases share canonical policy and stronger overrides take precedence. Optional image sources, environment-backed config fields and file open plans require `read_data`. Anchor locators permit live accessibility/OCR; image templates require `read_data` and VLM requests require `drive_input`. Read-only invocation rejects capture artifacts and VLM branches, and its catalogue excludes caller-selected ADB executables. MCP CI annotations return formatted lines without writing to stdout. Unreviewed plugin and WebRunner initialization tools are omitted from read-only catalogues and require dependency-specific review.

An MCP `tools/call` runs as a stoppable run listed as `mcp-…`. `notifications/cancelled` stops it: an action list from `ac_execute_actions` halts before its next action, and `ac_wait_for_image` / `ac_wait_for_pixel` wake mid-poll; the call is answered with `-32800`. `ac_stop_execution` and other stop requests end it the same way, reported as a tool error. A command already inside a backend still finishes first, except a captured shell command (`ac_shell`, `AC_shell_to_var`), whose process tree is killed, an HTTP request (`AC_http_request`, `ac_http_request`, and the other clients built on the shared HTTP client), whose sockets are shut, and a template-match or OCR pass, which the call stops waiting for (the native pass finishes in the background and its result is discarded); in each case the call ends. Pacing inside one gesture also wakes: the interval between `click_mouse` clicks, the step and settle rests of a tween drag (the button is released where the pointer stopped), and the per-step and per-key delays of humanized motion and typing.

REST host-data reads now follow the matching MCP authority: jobs, remote sessions, USB passthrough status and loopback/remote inventories, and diagnostics require `read_data`. The corresponding registered status commands, `AC_probe_capabilities` and `AC_diagnose` enforce it before providers run. A read-only hint is not viewer access; operator/admin callers retain access. USB enumeration/events, retained inspector statistics and process metrics also require `read_data`, as do `AC_list_usb_devices`, `AC_usb_recent_events`, `AC_inspector_recent` and `AC_inspector_summary`. Dashboard panels report missing capabilities independently and clear stale rows. A successful session refresh also clears its previous error status. Unlisted executor-command authorization remains a separate audit scope.

Host read-only mode applies the same restrictions to explicitly supplied registries and later registrations. Both admission and refreshed invocation check mixed arguments. Configured MCP failure screenshots require a writable tool and a refreshed caller with drive authority; readonly calls and viewers never trigger them. This does not promise that every dependency or diagnostic read has no initialization side effects.

Internal Windows process-memory preparation can now measure a selected process image file through retained read-only handles, with bounded hashing and retryable cleanup. This is observed file evidence, not loaded-code or fixture attestation; native acceptance remains incomplete and arbitrary-address memory tools remain unavailable. See [the contract](docs/process_memory_contract.md).

A host-managed fixture profile binds a fixed packaged worker to a reviewed config path and digest through the existing target-management API and GUI JSON editor. Registration is inert; bootstrap and configure both verify the deployment binding. The explicit probe checks static artifacts in a bounded background helper and reports `static_artifacts_ready`, `fixture_execution=not_run` and `native_evidence=not_recorded`. Runtime shutdown retains ownership until inspection helpers retire. The fixture is acquired only during managed readiness. Config/image checks do not attest Python source or DLLs. Native execution remains paused; the private delivery format and limits are documented in the same contract.

WebRTC peers also retain failed media constructors and children, observe live disable completion, and bind deferred renegotiation to its original peer. Media producer shutdown now reports pending or uncertain cleanup and retains original resources. Audio and recorder failures are never turned into success by unsafe close or flush replay. LAN close supports explicit retry; application caretaker and GUI integration remain pending. See [the retirement contract](docs/media_retirement_contract.md).

HostBrowser also rejects late publications and retains unfinished thread/close ownership; dialog integration remains pending.

MultiViewerHost can return an owned offer or capture an original-session retirement receipt, so delayed cleanup cannot stop a replacement peer or screen source. GUI adoption remains pending.

Host-selected semantic adapters can return multi-source reports through the existing observation API. The fixture combines reviewed memory reads with its owned read-only IPC snapshot and rechecks both before commit. Report version 3 fixes the required fields in host code and preserves valid fields separately from per-field failures. Missing sources, conflicts and best-effort captures cannot authorize actions or completion. Versions 1 and 2 are rejected.

A separate owned UI observation fixture can be built with `test/fixtures/native_memory/build_fixture.py --kind uia`; its static manifest remains schema 2. The internal launcher binds startup to the retained process and window owner. The scoped UIA reader checks that window, process and root identity, limits tree traversal, and protects password fields. Its read-only managed adapter creates COM lazily and preserves partial fields through the shared observation API.

Injected calls and hidden Python helpers cover scoped reads, reporting and timeout retirement. Native deployment trust, DOM integration and desktop acceptance remain pending. No native UI fixture execution or desktop noninterference is claimed.

The internal owned UI target retains its launcher and both image leases before
attestation, attempts every owner during cleanup, and retains failed cleanup for
retry. A publication lock prevents late source installation after shutdown. The
native factory only constructs owners; native deployment trust
and native acceptance remain pending.

Host management can register a `uia_fixture` profile with empty `allowed_tools`,
`roots` and `apps`, and only `config_path`/`config_sha256` settings. It uses a fixed
isolated worker and validates deployment, profile and target pins before acquisition.
Both endpoints refuse commands. External tasks may use an empty tool scope only
without planned actions; completion criteria remain required and an empty plan
cannot prove completion. UI partial/best-effort reports remain diagnostic.
Registration and probe acquire nothing; probe reports `not_supported` and
`native_evidence=not_recorded`. The existing target API, CLI and GUI JSON editor
carry this profile. Injected and hidden-helper tests do not establish native trust.

Host-selected in-process service adapters can use the closed `service_state` criterion:
`{"kind":"service_state","tool":"AC_service_start","state":"running"}` or STOP/stopped.
It requires the matching confirmed acceptance and a new SCM report from the same
retained owner after acceptance. A passing result reports SCM state, not atomic
completion, health or desktop noninterference. These tool names are adapter-scoped,
not global executor commands. Existing task APIs and the GUI JSON editor carry the
criterion. The host-reviewed `service` profile pins `config_path`, `config_sha256`
and a `service_key`. Non-ASCII keys are case-folded with Windows' own NT upcase table,
never Python's case mapping, so every spelling SCM treats as one service shares one lock.
Its fixed worker checks the deployment's service and
operation ceiling before accepting task scope. Registration, reload and probe do
not read the deployment or access SCM; native acceptance remains pending.
Every pinned path (each profile's `config_path` and the image a deployment names) must be
a local drive path: UNC shares, `\\.\pipe\` names, `\\?\` device paths and `..` segments are
refused, so registering a profile cannot make the host send its credentials to another machine.
Before a fixture image runs, its lease also refuses a location another account could change:
every directory from the drive root down must be a real directory (no junction or symlink) that
only SYSTEM, Administrators, TrustedInstaller and the running user may rename, delete, re-ACL or
add files to, and the leased file's final path must be the configured one. Deploy fixtures under
a protected directory such as `%LOCALAPPDATA%`; a drive root that grants Authenticated Users Modify
(common on secondary drives) or a shared `%TEMP%` is refused. The fixture starts in its own
directory with a minimal environment: a system-only `PATH` and none of the host's tokens or keys.
