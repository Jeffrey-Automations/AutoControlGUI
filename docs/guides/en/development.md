# Development and resources

[README](../../../README.md) · [Documentation](../../README.md)

## Documentation and examples

| Resource | What's in it |
|---|---|
| [`examples/`](../../../examples) | 45 self-contained scripts: screenshot + click, OCR, scheduler, remote desktop, agent loop, observability, recording, variables, hotkeys, triggers, reports, MCP, REST, secrets, plugins, computer use, Wayland, cross-host DAGs, chat-ops, pytest/BDD, anchor locators, action journals. |
| [Read the Docs](https://autocontrol.readthedocs.io/en/latest/) | Full API reference, English and 中文. |
| [architecture_explore.md](../../../architecture_explore.md) | Every module's responsibility, layer by layer. |
| [docs/CAPABILITY_MATRIX.md](../../CAPABILITY_MATRIX.md) | Capability × platform matrix. |
| [docs/API_LIFECYCLE.md](../../API_LIFECYCLE.md) | Stable-API and deprecation policy. |
| [docs/updates/](../../updates/README.md) | Update log: release notes and finished work, one file per month (formerly `WHATS_NEW.md`). |
| [CHANGELOG.md](../../../CHANGELOG.md) | Compatibility changelog. |
| [SECURITY.md](../../../SECURITY.md) | Security policy and reporting. |

---

## Development

```bash
git clone https://github.com/Integration-Automation/AutoControlGUI.git
cd AutoControl
pip install -r dev_requirements.txt
uv sync                 # or: reproducible install from the committed uv.lock
```

```bash
python -m pytest test/unit_test/headless      # headless unit tests
python -m pytest test/integrated_test/        # cross-module workflows

ruff check je_auto_control/
pylint je_auto_control/
bandit -c pyproject.toml -r je_auto_control/

python test/verify/typing_contract_verify.py            # mypy, whole package, three target platforms
python test/verify/typing_contract_verify.py --extras   # the same against the real PySide6 / aiortc types
python -m sphinx -b html -W docs/source docs/_build/html  # the docs, warnings as errors
```

The dev/main headless jobs retain `native-<os>-<python>` artifacts for seven
days: merged process output, package/runtime versions and exit status. Linux
runs under GDB to retain all-thread native backtraces; other platforms retain
Python faulthandler output. Test failures remain failures. From a repository
checkout, reproduce collection with `python scripts/ci_native_diagnostics.py
--artifact-dir test-artifacts -- python -m pytest -v --tb=short --timeout=120`
(one command); add `--native` before `--` on Linux with GDB installed.
Literal argv (including whitespace/quotes) and handled `SIGINT` reach the
child unchanged. Linux first verifies the runner outside the suite's debugger;
its preflight logs are included in the same artifact.

Selected dev pushes run `.github/workflows/ei-lifecycle.yml` in an isolated
libei/libeis container, retaining versions and both native logs for 14 days in
`ei-lifecycle-<run>-<attempt>` artifacts. Half-open and live cleanup children
have 10/60-second deadlines and faulthandler. Unrelated child failures fail CI;
successful cleanup requires begin/end markers. The half-open probe also requires
equal integer descriptor counts; live cleanup releases owned device refs first.
Run 39507190704 on libei/libeis 1.3.901-1 passes 9/9 and 20/20 checks, including
native out-of-region refusal without CLI fallback. Half-open `ei_unref` still
segfaults, so runtime protection remains and helper isolation is pending.
Device pause and sequence readback remain unverified. These controlled socket
peers do not establish compositor consent, physical or multi-monitor acceptance.

Contributions are welcome — see [CONTRIBUTING.md](../../../CONTRIBUTING.md) and
[CODE_OF_CONDUCT.md](../../../CODE_OF_CONDUCT.md). Two rules the CI enforces: `import
je_auto_control` must never pull in PySide6, and every feature needs both a headless
API and a GUI surface.

---

## License

[MIT License](../../../LICENSE) © JE-Chen.
See [Third_Party_License.md](../../../Third_Party_License.md) for the licenses of bundled and
optional third-party components.

- **Homepage**: https://github.com/Integration-Automation/AutoControlGUI
- **PyPI**: https://pypi.org/project/je_auto_control/
- **Documentation**: https://autocontrol.readthedocs.io/en/latest/

Legacy MCP action wrappers, parallel branches and local DAG workers retain the same origin ceilings.

Managed point actions accept observation-local element indices or thumbnail image points. The host checks the current frame and resolves native coordinates, including scaling and negative monitor origins. Receipts retain geometry provenance without image bytes. `AgentObservationStale` identifies rejection before dispatch; local agents reobserve only within their retry budget when the adapter confirms no held or pending input.

Emergency stop returns compact snapshots with metadata.details_deferred; fetch individual task details for full artifact links.

Managed mouse presses normalize button ownership and confirm the actual cursor before input. Windows pointer checks reject foreign overlays. Vision renders the exact scoped window into cleared private GDI storage, rejects geometry changes and releases resources even on rendering/read failure. There is no desktop-crop fallback. Fake-native tests cover these paths; native acceptance remains unverified.

The Agent tasks view groups task scope, workflow settings, triggers, skills and recovery into separate pages. Its observation page lists read-only elements and shows a validated, strictly masked JPEG at one rendered pixel per logical widget pixel. Selecting a row or image point only edits a frame-bound action request; Actions -> Perform observed action sends it through the shared task API. Switching tasks clears the preview, and late replies cannot replace the selected task. A new frame requires reselection before an old reference can be sent. Closing the view only detaches its requests.

Managed workflow waits (workflow_wait / AC_workflow_wait) poll only exact scoped control values or states, with cancellation and a deadline capped by the action budget (default five seconds, maximum sixty). They never replay a write or submit. Fixed skills require all previous receipts to match the pinned sequence before continuing, including after resume; autonomous model loops retain stuck detection. New form/transfer drafts refuse an already-matching confirmation before submit and wait for a fresh transition afterward. Batch configurations may provide new_record_selector to reset each record; confirmations prove the configured UI transition, and transaction-specific receipt values should be used when available. Archive drafts also re-read the exact reviewed manifest and current file digests at finish (one-megabyte manifest and sixty-four-megabyte total evidence limit).

AgentHumanReview identifies an unsaved-content or unknown-dialog gate. It persists waiting_user and retires input ownership, including for external observe requests; explicit resume still rechecks the gate. Windows detection uses native dialog/disabled-owner evidence and known English/Chinese/Japanese unsaved labels. Workspace tasks also pause for leading/trailing asterisks in document titles; a window entry may supply unsaved_selector and unsaved_value for an application-specific indicator before layout changes. These checks do not infer every application's dirty state. Recognized standard file pickers use a context-local driver on the existing AC_handle_file_dialog executor: exact unique title, same PID, confirmed foreground and canonical rooted absolute paths. UIA control patterns must belong to the actual owned root window, even when another window shares its PID. All behavior has fake-native/loopback coverage; actual platform acceptance remains unverified.

Host-reviewed targets use AgentTargetProfile and manage_agent_target (AC_agent_target; register/get/disable/enable/probe). Names and configuration are immutable; desktop/file/browser adapters are currently supported; unimplemented kinds are rejected and optional browser helper_python is host-reviewed. Tasks pin the host profile digest and cannot expand its tools, applications, roots or network origins. Availability persists across restart and is checked at dispatch; disabling requests pause/cleanup, while enabling requires explicit task resume. list_agent_targets / AC_agent_target_list / CLI agent-task targets expose passive metadata with readiness=not_probed and native_evidence=not_recorded. Full configuration requires manage_hosts; CLI agent-task target and the GUI Host targets page use the same service. Live anonymous MCP tool sessions have operator authority across direct and legacy wrapper calls; MCP host management requires an authenticated administrator. Trusted direct Python callers remain unchanged. Browser automation belongs to WebRunner (je_web_runner), with D:/Codes/WebRunner as the development source; browser profiles use the managed je_web_runner SDK contract, and dependency probes do not establish native readiness.

Existing browser automation, including open_path(URL) and AC_open_path, delegates to WebRunner (Python package je_web_runner). URL plans now report backend=je_web_runner; callers inspecting the previous webbrowser descriptor should use the new value. Signatures and local-file opening stay compatible. URL execution requires the configured WebRunner project and propagates WebRunnerBridgeError when unavailable, without opening an OS browser as a fallback. The development source is D:/Codes/WebRunner. Planning and injected-opener tests remain usable without that package; browser protocol support is determined by WebRunner and its selected browser. Existing dedicated browser GUI/MCP/AC paths and recorded WR_* actions share the same bridge.
