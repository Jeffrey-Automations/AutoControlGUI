# Automation usage

[README](../../../README.md) · [Documentation](../../README.md)

## Why AutoControl

- **One API, seven platforms.** `wrapper/platform_wrapper.py` picks the backend at import
  time; your script does not change between Windows, macOS, X11, and Wayland.
- **Scriptable without Python.** 911 `AC_*` commands cover the whole feature set, so a
  JSON file can do anything the library can — including loops, branches, try/catch,
  macros, and variables.
- **Headless by default.** `import je_auto_control` never loads Qt. The GUI is an
  optional extra that wraps the same headless core.
  Public exports load their source modules when requested. `__all__` and `dir()` list names
  without loading every feature; wildcard import requests them all. Unresolved names are absent
  from `vars(je_auto_control)`.
  On X11, plain package import opens no display or input device and starts no keyboard listener.
  Desktop operations acquire resources when called. Reading `keyboard_keys_table` or calling
  `get_keyboard_keys_table()` resolves actual server keycodes and requires an X connection.
- **Locate things four ways.** Template matching, OCR, the accessibility tree, and a
  vision-language model — composable through anchor locators and self-healing fallbacks.
- **Light dependency floor.** The REST server, JSON Schema validator, JWT, TOTP,
  WebSocket framing, ACME client, USB/IP protocol, and Prometheus metrics are all
  standard-library implementations. Heavy things are opt-in extras.


## Choosing the right automation layer

AutoControl is not intended to replace every automation tool. Use the smallest layer that matches the interface:

| Need | Good fit |
|---|---|
| Stable browser DOM/API automation | Playwright / Selenium |
| Simple Python mouse and keyboard scripting | PyAutoGUI or AutoControl |
| Native desktop application automation | **AutoControl** |
| Accessibility-tree GUI automation | **AutoControl** |
| OCR-driven GUI automation | **AutoControl** |
| Screenshot / vision-model GUI localization | **AutoControl** |
| Self-healing cross-platform GUI locators | **AutoControl** |
| AI agent controlling a real desktop | **AutoControl + MCP** |
| Deterministic JSON GUI workflows | **AutoControl** |

The differentiator is the combination of **real computer input + semantic/visual discovery + self-healing + agent/MCP integration** behind one cross-platform automation surface.


## 60-second quick start

**1. As a Python library**

```python
import je_auto_control as ac

ac.set_mouse_position(500, 300)
ac.click_mouse("mouse_left")
ac.write("Hello World")
ac.hotkey(["ctrl_l", "s"])

x, y = ac.locate_image_center("save_button.png", detect_threshold=0.9)
ac.click_text("Submit")                       # OCR
ac.click_accessibility_element(name="OK")     # accessibility tree
ac.click_by_description("the green Submit button")   # vision model
ac.screenshot("shot.png", screen_region=[0, 0, 800, 600])
```

**2. As a JSON action file** — `flow.json`

```json
[
    ["AC_set_var", {"name": "user", "value": "alice"}],
    ["AC_locate_and_click", {"image": "login.png", "mouse_keycode": "mouse_left"}],
    ["AC_write", {"write_string": "${user}"}],
    ["AC_retry", {"max_attempts": 3, "body": [
        ["AC_wait_text", {"target": "Welcome", "timeout": 10}]
    ]}],
    ["AC_assert_text", {"text": "Welcome"}],
    ["AC_generate_html_report", {"html_name": "report"}]
]
```

```bash
je_auto_control run flow.json --var user=bob
je_auto_control run flow.json --dry-run     # list the steps without touching the mouse
```

**3. As a desktop app**

```bash
pip install je_auto_control[gui]
python -c "import je_auto_control; je_auto_control.start_autocontrol_gui()"
```

Record a flow, edit it in the visual Script Builder, and save it as the same JSON
format the CLI runs. (`python -m je_auto_control` is the legacy action-file runner — `-e`, `-d`,
`-c`, `--execute_str` — not the GUI.)

---

## Capability overview

Every row works headlessly. "GUI tab" is where the same feature surfaces in the
desktop app; tab commands live in the window's **Actions** menu.

| Capability | Python API | `AC_*` command | GUI tab |
|---|---|---|---|
| Mouse | `click_mouse` (`clicks=2` double-clicks), `set_mouse_position`, `mouse_scroll`, `tween_drag` / `drag_path` (paced by `step_delay_s`, `settle_s`) | `AC_click_mouse`, `AC_tween_drag`, `AC_drag_path` | Auto Click |
| Keyboard | `write`, `write_secret`, `hotkey`, `type_keyboard`, `keyboard_key_name` (code → canonical name; Windows also takes aliases such as `ctrl`, `esc`, `enter`) | `AC_write`, `AC_write_secret`, `AC_hotkey` | Auto Click |
| Screen & pixels | `screenshot`, `screen_size`, `get_pixel` | `AC_screenshot` | Screenshot |
| Image matching | `locate_image_center`, `locate_and_click` | `AC_locate_and_click` | Image Detect |
| OCR text | `click_text`, `wait_for_text`, `read_text_in_region`, `ocr_status` | `AC_click_text`, `AC_wait_text`, `AC_ocr_status` | OCR Reader |
| Accessibility tree | `find_accessibility_element`, `click_accessibility_element` | `AC_a11y_find`, `AC_a11y_click` | Accessibility |
| Vision-model locator | `locate_by_description`, `click_by_description` | `AC_vlm_locate`, `AC_vlm_click` | VLM |
| Anchor locator | — | `AC_anchor_click`, `AC_anchor_locate` | — |
| Self-healing locators | `self_heal_run`, `self_heal_locate`, `self_heal_click` | `AC_self_heal_click` | Self-Healing |
| Natural-language planner | `plan_actions`, `run_from_description` | `AC_llm_plan` | LLM Planner |
| Computer-use agent | `AgentLoop`, `run_agent` | `AC_run_agent` | Computer Use |
| Record & replay | `record`, `stop_record` | `AC_record`, `AC_stop_record` | Record |
| JSON scripting | `execute_action`, `execute_files` | all 911 commands | Script, Script Builder |
| Variables & flow control | `execute_action_with_vars` | `AC_set_var`, `AC_loop`, `AC_for_each`, `AC_try`, `AC_retry` | Variables |
| Data-driven runs | — | `AC_for_each_row` (CSV / JSON / SQLite / Excel) | Data Sources |
| Assertions | `assert_text`, `assert_image` | `AC_assert_text` + 20 more | Assertions |
| Test suites | `run_suite` | `AC_run_suite` | Test Suites |
| Scheduler (interval + cron) | `default_scheduler` | — | Scheduler |
| Global hotkeys | `default_hotkey_daemon` | — | Hotkeys |
| Event triggers | `default_trigger_engine` | `AC_email_trigger_add` | Triggers, Webhooks, Email |
| Window management *(Windows, macOS, X11)* | `list_windows`, `focus_window` | `AC_focus_window`, `AC_snap_window` | Window Manager |
| Clipboard (text + image) | `get_clipboard`, `set_clipboard`, `get_clipboard_image`, `set_clipboard_image` | `AC_clipboard_get`, `AC_clipboard_set`, `AC_clipboard_get_image`, `AC_clipboard_set_image` | — |
| Remote desktop | `RemoteDesktopHost`, `RemoteDesktopViewer` | `AC_start_remote_host`, `AC_remote_connect` | Remote Desktop |
| USB enumeration & passthrough | `list_usb_devices`, `enable_usb_passthrough` | `AC_usb_*` (16 commands) | USB Devices, USB Share |
| Secrets vault | `default_secret_manager` | `AC_secret_set` + `${secrets.NAME}` | Secrets |
| Reports (HTML / JSON / XML) | `generate_html_report` | `AC_generate_html_report` | Report |
| Run history | `HistoryStore`, `manual_history_scope` | `AC_history_list`, `AC_history_capture` | Run History, Script Executor, Script Builder |
| Action journals | `execute_journal_run`, `inspect_journal` | `AC_journal_capture`, `AC_journal_read` | Run History, Script Builder |
| Metrics & tracing | `default_metric_registry`, `render_metrics_text` | — | — |
| Diagnostics | `run_diagnostics` | `AC_diagnose` | Diagnostics |
| Test-code generation | `generate_code` | — | — |

Self-healing propagates cancellation before fallback or clicking. Its audit log masks secrets already resolved in the current run before writing or returning records; returned locator outcomes retain their original values. Legacy log files are not rewritten.

Live image/VLM self-healing now shares one lazy logical capture, including its actual clipped origin. `screen_region` is `[left, top, right, bottom]` for both strategies. Schema-v2 audit records add run/step identity, content/configuration version, frame hash, strategy/capture timing and resolved backend/model; old records still load. Click dispatch without a verifier is recorded as issued or failed, with verification left unknown. The GUI exposes region input and selected-record evidence; Script Builder keeps region JSON structured. Historical `healed`/`heal_rate` count located candidates; separate operation metrics require explicit verification.

Experimental `self_heal_run(SelfHealRequest(...))` defaults to locating. Choose `operation="click"` and `VerificationRequest(verifier=...)` (a Python bool callback) or `VerificationRequest(description=...)` (a configured VLM) to check the post-condition after input dispatch. VLM verification obtains a fresh logical frame and may incur API cost. `verified` is true, false or unknown; `found` and `issued` alone do not verify the operation. Exceptions and cancellation propagate without retrying the click. `AC_self_heal_run` and MCP `ac_self_heal_run` accept a nested `request`; explicit false verification fails the command/CLI or returns MCP `isError` with the structured result. GUI **Self-Healing** offers an optional post-condition field, and Script Builder edits the JSON request. Standalone VLM capture now uses the same logical origin/Retina normalization in memory. Framework assertions stop lookup recovery.

Captured self-healing rows now include an optional `journal_path` alongside run/step IDs. Experimental `inspect_heal_source(path, run_id, step_id)`, `AC_self_heal_source` and MCP `ac_self_heal_source` read only the original step’s sanitized lifecycle snapshots. In **Self-Healing**, select a row and choose **Actions → Inspect original step** to open the background reader. Switching targets waits for the older reader to stop and retains the requester’s context; closing cancels pending work. Run History’s reader also accepts an optional step ID. Run/step filtering precedes the output limit, the whole file is validated, current path roots are rechecked around progress callbacks, and cancellation returns no partial result. Legacy or uncaptured rows have no original-source link; inspection never replays a command.

Experimental causal synchronization provides `CausalBucket`, `CausalConfigStore`, `SyncActor`, conflict-preserving entry versions and a durable local `SyncOutbox`. The dedicated authenticated `GET/PUT /config/{user_id}/causal` protocol (version 3) validates peer registration, acknowledgements, retirement/full-sync epochs and collection in the same CAS transaction as retry receipts. Collected deletions retain permanent minimal fences; legacy writers cannot overwrite upgraded accounts. Private `AC_config_store_get` / `AC_config_store_commit` and matching MCP/Builder commands read and commit causal JSON with an explicit `_actor`. Pure merge/peer commands and private outbox commands remain available. The explicit `CausalSyncClient` and `AC_config_causal_fetch`, `AC_config_causal_commit`, `AC_sync_outbox_flush` (matching MCP/Builder commands) now deliver v3 HTTP requests: uncertain sends reuse the frozen request; only definite stale-base errors rebase within a bounded budget. `CausalReceipt` confirms the original receipt and latest complete snapshot atomically in the outbox. Command credentials use a live `options.secret_env` reference. `CausalSyncClient.control` and private `AC_sync_peer_control` / `ac_sync_peer_control` / Builder Data commands durably register, acknowledge, collect, retire and perform full resync. `SyncControlRequest(operation_id=...)` makes completed RPC retries idempotent; full resync requires explicit `discard_pending=True` before atomically adopting a new generation and archiving pending old edits. Local `status` reads no credential or network. Run `python -m examples.causal_peer_control` for the temporary loopback workflow; explicit local asset generations are available through `AssetManifest`, `DirectoryAssetTransport`, `build_asset_manifest`, `sync_assets` and private `AC_sync_asset_manifest` / `AC_sync_assets` (MCP/Builder). All assets stage and pass SHA-256/size checks before one directory publication; damaged caches are refused and scripts stay inert. `python -m examples.sync_assets` uses temporary directories only. Seven experimental adapters now capture selected scripts, locators, hotkeys, triggers, address-book entries, JSON settings and saved native GUI preferences into durable causal profiles. `SyncBindings` replaces explicit secrets and machine values with named references; `materialize_sync_profile` publishes a complete inert native-format generation. Private `AC_sync_adapter_snapshot`, `AC_sync_adapter_apply`, `AC_sync_adapter_resolve`, `AC_sync_profile_materialize` and matching MCP/Builder commands share the workflow. `python -m examples.sync_adapters` uses temporary files only. Private absolute path bindings accept high-entropy directory names while recognized credential formats remain refused. Native numeric definitions reject out-of-range values, including extreme JSON integers, with typed errors before storage. `WorkspaceSettingsSyncAdapter` captures only theme, font size, navigation visibility/width from native GUI INI files and publishes an inert `workspace.ini`; explicitly copy it to a separate working file before opening a new GUI. `python -m examples.sync_workspace` stays Qt-free. `SyncWorkspace` now coordinates selected sources, durable offline capture, causal HTTP, exact conflict review and full-resync source baselines. Private `AC_sync_workspace` / `ac_sync_workspace` / Builder Data share status/capture/sync/review/resolve/preferences/materialize and explicit peer controls; all require DRIVE. Runtime network credentials use `options.secret_env`. `python -m examples.sync_workspace_http` demonstrates two temporary sources over loopback, conflict resolution, restart and no replay of retired edits. Received definitions remain inert. Referenced asset transport is described below; explicit native working-copy loading is described below; `ConfigSyncClient` retains its timestamp merge. See the [causal/outbox guide](../../source/Eng/doc/causal_sync/causal_sync_doc.rst) and `python -m examples.causal_sync`.

The lazy **Workspace Sync** tab exposes local status/capture, network synchronization and peer controls, exact causal review/resolution, and complete inert publication through **Actions**. Paste an explicit private workspace descriptor; credentials are environment variable names. Sync never applies received preferences automatically. Select `workspace`, review its current heads, then choose **Apply reviewed GUI preferences** to update theme, font and navigation in the running window. `SyncWorkspace.preferences(observed=change_ids)` and the existing AC/MCP/Builder `preferences` operation return four canonical values only when the exact reviewed heads remain conflict-free; missing/deleted values use safe defaults. Workers preserve caller context, refresh DRIVE authority, support cancellation and discard stale results on close. The view shows revision/pending/conflict/reference counts and the last successful sync revision; no connection starts when opened.

Explicit native loading uses `load_sync_profile(directory, target_root, expected_digest=...)` and `LoadedSyncProfile`, with private `AC_sync_profile_load` / `ac_sync_profile_load` / Builder Data equivalents. The published `files` directory and exact reviewed manifest digest create a fresh editable workspace. Full verified bytes, canonical native files and sealed heads must agree before atomic publication. Loaded hotkeys and every trigger node are disabled native objects; locator and address-book handles use the working files. Typed asset references and native hotkey/trigger paths resolve against that working root, while literal script strings keep their meaning and secrets stay placeholders. In **Workspace Sync**, materialization fills the directory/digest fields; choose a working-copy container and **Load reviewed native profile**. Separate Actions inspect the selected native kind, open a loaded script snapshot in Builder, or apply its preference snapshot. These actions recheck both the current caller and captured owner; opening a script keeps Run explicit. Builder renders imported command names and positional data as literal text. `python -m examples.sync_profile_load` uses seven temporary domains and a real PNG with no network or device calls.

Folder mirroring now compares SHA-256 content instead of increasing modification times: metadata-only touches do not resend, while same-time/older-time edits do. FolderSyncEngine retains pending/offline edits across restarts, checks stop between files, and owns a blocked sender until it exits. Transport owners can explicitly call record_received(path) after publication to prevent echoing received bytes. Native GUI frozen-receipt handling is described below.

File sends now wait for each DataChannel callback, bound buffered data to 1 MiB and propagate channel failures to the caller. Optional `cancelled` predicates stop queued writes; announced byte counts detect source truncation/growth. Native folder jobs capture their authorization, engine, viewer and peer connection, and stop when ownership changes. Inbox downloads run outside the event loop through a per-channel queue capped at 32 requests. Default manual-mode channel acceptance is not publication acknowledgement; confirmed mode is described below. GUI reconnect handoff is described below.

Native file receivers now discard unfinished bytes on shutdown, files/control channel close, terminal connection state, replacement channel or revoked file permission. Closed receivers reject late frames; current peer/channel and authentication checks protect replacement transfers, including viewer receives before authentication. State cleanup precedes user callbacks so callback-driven reconnection survives an old failure. File/audit/state callbacks preserve original cancellation and hard-interruption objects. Filesystem cleanup failures are logged after both close and unlink are attempted. Existing Remote Desktop controls use this lifecycle automatically; completed targets and the legacy wire format remain available.

Local `FileReceiveReceipt(path, sha256, size)` metadata now freezes the original received bytes after atomic publication. `FileTransferReceiver.handle_message(on_receipt=...)` and native host/viewer `set_file_receipt_callback()` expose it without rereading the published file. `FolderSyncEngine.record_receipt()` prevents echo while retaining later local edits; legacy `record_received(path)` explicitly snapshots current content. The GUI folder toggle captures its engine and viewer for receipt delivery and refreshes its original authorization before touching the watch. Relative inbox/watch paths bind to their creation working directory; existing path notices use absolute paths. These local receipts feed the confirmed native mode below; GUI reconnect handoff is described below.

Native `FileTransferSender.send`, viewer `send_file` and host `push_file` now accept keyword-only `require_commit=True`. Confirmed mode probes an authenticated native peer before source metadata/content reads, sends version-2 begin/end metadata and verifies the matching transfer ID, unpredictable end nonce, SHA-256 and byte size after atomic publication. Relative source paths bind before the exchange. Each file rechecks peer support/permission; waits are bounded and cancellation, channel/loop replacement or permission loss retain failure. GUI folder sends always require this mode, so accepted-but-dropped bytes do not advance delivery state and uncertain sends retry on the same engine. Legacy manual mode remains the default and sends its original envelopes. Both peers need confirmed-transfer support for GUI folder delivery; unsupported peers fail before file content is sent. Explicit GUI reconnect/resume is described below.

GUI reconnect retains one in-memory folder baseline per panel. After reconnecting, press Start sync again: the same authenticated host fingerprint, absolute watch path and local principal resume failed/offline edits through a new authorised sender. A missing/changed host fingerprint, different root or principal starts a fresh baseline; a still-running old worker blocks handoff until it exits. Explicitly disabling folder sync resets the baseline, while stopping/reconnecting the viewer retains it. Closing the application clears it. The fingerprint follows the existing authenticated host-metadata trust model, not a new cryptographic identity guarantee. SDK callers can stop a FolderSyncEngine, export checkpoint() after actual worker retirement and pass that immutable FolderSyncCheckpoint to a replacement engine with the same path/recursion mode and an explicitly authorised sender. The baseline includes initially ignored files and received bytes; it is not a list of remote acknowledgements.

TCP/WebSocket clipboard transfers use the existing explicit SDK methods and GUI Push clipboard button. Received text/images do not automatically send or broadcast onward; deliberate repeated sends of identical content remain valid. Buffered viewer/host reads recheck the original connection, authentication and full-control permission before applying clipboard data. Viewer sends pin the original channel before encoding and refuse replacement. Queued GUI deliveries retain their concrete viewer and connecting user; permissions and ownership are refreshed before native clipboard writes, before explicit clipboard reads and again before sending. Stale/revoked work is discarded or reports its permission error. Ordinary provider/callback errors stay contained; original cancellation and hard-control objects propagate. Text/image JSON envelopes and existing APIs remain unchanged. Callback registration binds the original viewer weakly once, so a disconnected viewer does not keep itself and its Qt panel alive until cyclic GC. Actual queued deliveries still retain the original peer and authority until consumed or discarded. Controlled local protocol, loopback and offscreen tests replace native clipboard providers; real-device and paid-API acceptance remain deferred.

Experimental referenced assets use `SyncAssetBlob`, `SyncAssetReference`, `SyncAssetStore` and `SyncAssetHTTPClient`. Explicit `SyncBindings.assets` aliases freeze selected files into immutable SHA-256 references; asset-only changes create new causal versions. `SyncWorkspace` uploads verified chunks before preparing new definition requests, resumes interrupted transfers and downloads referenced bytes before complete inert publication. Existing private AC/MCP/Builder workspace/profile commands share these fields. `asset_cache_path` selects the client cache; signaling `--asset-store` / `AUTOCONTROL_SYNC_ASSET_STORE` select the separate server database. Authenticated version-one asset routes use 256-KiB chunks, a 64-MiB per-file bound and default per-account limits of 256 MiB, 8,192 chunks and 4,096 blob receipts. Quota exhaustion fails explicitly; immutable history has no automatic garbage collection. Paths in native output are relative to the generation root. `python -m examples.sync_referenced_assets` sends a real PNG and script through temporary loopback HTTP with no execution or active workspace change.

Experimental persistent configuration uses `ConfigStore.commit(..., base_revision=..., operation_id=...)` and a version-two signaling PUT envelope. SQLite transactions preserve buckets and retry receipts across restart; stale revisions or changed operation identities conflict. `ConfigSyncClient` defaults to conditional writes; blind legacy writes require explicit client/server opt-in. `--config-store` selects the lazy database. Private `AC_config_store_get` / `AC_config_store_commit` and matching MCP tools share explicit Script Builder Data commands. This stores data without running scripts or enabling triggers; causal merge and offline outbox remain separate. See the [persistent config guide](../../source/Eng/doc/config_store/config_store_doc.rst) and `python -m examples.config_store`.

Experimental journal-to-code candidates use `generate_candidate_from_log(path, run_id=...)`, `AC_generate_candidate_from_log`, and MCP `ac_generate_candidate_from_log`. They reconcile lifecycle snapshots, retain recorded control sources and retry evidence, and mark partial reconstructions as observed paths. Failed/incomplete invocations and unknown or redacted inputs remain explicit exclusions; parallel order is never invented. Generated Python/pytest/Robot source passes static, command and non-dispatching dry-run checks. `codegen --from-log run.jsonl --run-id selected` prints a JSON review bundle; `-o review.zip` or `write_candidate_archive` atomically exports code, actions and provenance together. **Actions → Review journal candidate** in Recording Editor or Script Builder opens source/diff/manifest/warnings; Builder import is separate and refuses intervening editor changes. Neither generation nor import runs the candidate. See the [journal candidate guide](../../source/Eng/doc/journal_candidates/journal_candidates_doc.rst) and `python -m examples.journal_candidates`.

Experimental template-candidate revisions use `create_template_candidate`, `preview_template_candidate`, `verify_template_candidate`, `accept_template_candidate` and `revert_template_candidate`, with matching `AC_template_candidate_*` / `ac_template_candidate_*` operations. A new immutable JSON bundle retains original bytes and the candidate encoded in the target’s PNG/JPEG/BMP format. Preview returns bounded thumbnails. Verification compares both frozen versions on a local sample manifest; acceptance requires a labelled hit, an expected miss and every labelled case correct, plus the reviewed bundle SHA-256. Acceptance rechecks the dataset and atomically replaces only matching original bytes; revert restores exact original bytes and refuses later edits. Unknowns and native-operation success remain separate. The recorded threshold applies to verification; activating image bytes does not edit script thresholds. **Self-Healing → Template candidates** offers all five Actions, background work, cancellation and JSON evidence. Run `python -m examples.template_candidates` for a temporary-file-only example.

Experimental fixed-frame comparisons use `evaluate_locators` or `evaluate_healing_manifest`, `AC_self_heal_evaluate`, MCP `ac_self_heal_evaluate`, and **Self-Healing → Version comparison**. Reports separate labelled accuracy, wrong predictions, unknowns and verified recovery, include p50/p95 and provenance, and export JSON/HTML through `write_healing_report` or GUI Actions. The local manifest operation never captures, clicks or selects a network backend. See the [dataset, populations and limits](../../../benchmarks/self_healing/README.md).

Beyond this table, `utils/` holds 311 headless packages covering assertions, resilience,
data quality, i18n auditing, redaction, governance, observability, and more. The full
per-module map is in **[architecture_explore.md](../../../architecture_explore.md)**.

---

Experimental structured journal capture is exported from `je_auto_control` (also available in `utils.action_journal`): `journal_scope` captures existing executor calls, and `execute_action_with_journal` isolates one run. Local loop/parallel/DAG steps retain parent IDs; failures, cancellation and dry-runs are distinct. Existing history owners automatically link explicit captures, including captures opened by local parallel/DAG workers; `HistoryStore.journals_for_run` returns the non-owning links. Clearing/pruning history leaves journal files intact. The CLI supports `run script.json --journal run.jsonl [--journal-run-id ID]` and `journal run.jsonl [--run-id ID] [--limit 100]`. Journal reads show sanitized lifecycle snapshots in append order; output defaults to 100 snapshots (maximum 10,000). `AC_journal_capture` accepts named parameters and runs a nested `body` on the owning executor without replacing its variables; `AC_journal_read` shares sanitized, bounded inspection with the CLI and public `inspect_journal`. Both commands are editable in Script Builder. Capture rejects identifiers or destinations containing secrets known to the run before history linking, file creation or action effects. MCP `ac_journal_capture` and `ac_journal_read` provide structured results, progress and cooperative cancellation. Captured journal roots and observers survive nested captures and local workers; reads can cancel between validated records. `JournalRunOptions` and `execute_journal_run` expose the same controls in Python.

Manual runs can opt into history with `manual_history_scope`, `AC_history_capture`, CLI `run --history [--history-db PATH]`, or **Record in Run History** in Script Executor / Script Builder. An optional GUI journal path also works independently of history. GUI/CLI result JSON and existing variable scopes are preserved; the command returns `history_id`, `record` and `failed_actions`. Existing and nested captures link to the new manual row. CLI previews use the `cli.preview` source label; ordinary runs use `cli.run`.

Run History includes a read-only journal browser. Use **Actions → Use Journals from Selected Run** to select a provenance link, or **Choose Journal** for an external file. Set a run ID and snapshot limit, then **Read Journal**; start/completion snapshots stay separate and their full sanitized data appears on selection. **Cancel Journal Read** and closing the view request cancellation between records. File parsing runs in a background worker; selecting a link opens no file.

Values resolved from `${secrets.NAME}` are masked in application diagnostics during executor runs, including nested actions and local parallel/DAG workers. CLI/REST/MCP requests and scheduled, trigger, hotkey and email runs retain the mask through error handling and audit/history writes; report records capture redacted snapshots. DAG calls retain the owner mask through complete node diagnostics, including standalone calls and custom local runners. Watchdog, observer and callback-executor calls also retain it through final diagnostics; independent rules have separate masks. CLI stderr is masked, while API outcomes, raised exceptions and CLI result payloads retain their original values. Masks are discarded when the owning request or run exits. Interrupted history runs are recorded as `error`, while journal steps remain `cancelled`; no error screenshot is taken. Cancellation propagates through non-strict execution, recovery/retry, callbacks and local workers. Hard exits retain their original signal even if history completion fails.

## Command-line interface

Each `je_auto_control run` invocation, including `--dry-run` and runs without `--var`, gets a fresh variable scope. Top-level `run_from_description` and `StateMachine.run()` also isolate variables while sharing them across their own actions and states; nested calls reuse an existing execution scope. A caller-owned `Executor()` keeps its own variables.

```bash
je_auto_control run script.json [--var name=value] [--dry-run] [--allow-package NAME]
je_auto_control validate script.json          # alias: lint
je_auto_control fmt script.json [--check]
je_auto_control list-commands [--filter mouse] [--json]
je_auto_control record out.json [--duration 5]
je_auto_control codegen script.json --target pytest -o test_flow.py
je_auto_control failure-bundle failure.zip --error "login timed out"
je_auto_control list-jobs
je_auto_control start-server --port 9938      # TCP socket server
je_auto_control start-rest   --port 9939      # REST API
je_auto_control version
```

`--var name=value` is parsed as JSON when possible (`count=10` becomes an int),
otherwise kept as a string. `run` exits 1 when any action failed (the run
still goes on to the end), so a CI step fails with it. The legacy
`python -m je_auto_control -e file.json` entry point still works, and its
`-e`, `-d` and `--execute_str` flags exit 1 the same way. Under
[TestPioneer](https://github.com/Integration-Automation/TestPioneer), which
sets `TEST_PIONEER_ARTIFACT_DIR`, the HTML, JSON and XML reports asked for
under a relative name are written below that directory.

---
