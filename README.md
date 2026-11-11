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

View → Execution details (Ctrl+Shift+D) opens a collapsible right pane. Diagnostics publishes its actual progress, stop, result and error state there; other pages explicitly say when details are unavailable. Switching or closing a page disconnects its updates. Embedders can supply a TabRegistry to WorkspaceShell; AutoControlGUIWidget(parent) remains supported.

WebRTC statistics polling starts in the background and discards late samples after it stops.

Windows, macOS, X11 and Wayland use different backends. Available features depend on system permissions and optional dependencies; Windows ARM64 has additional limitations. See the installation guide before choosing a deployment target.

Wayland NORMAL input runs libei and portal calls in an owned helper process. Timeouts, cancellation and uncertain replies retire that helper without replay or automatic provider fallback. The direct `LibeiBackend` API remains in-process. Helper retirement is not proof that a compositor released input; native acceptance remains pending.

Managed agent tasks and cross-host transfers include experimental features. See the implementation notes and project progress before relying on them in production.

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

Closing Remote Desktop releases its page. Reopening creates fresh controls without reattaching shared sessions. Registry TCP/WebSocket sessions remain available to scripts; page-owned WebRTC sessions and audio retire in the background. Pending approvals are denied, and late callbacks are discarded. An already-entered file transfer is not interrupted by closing the page.

MCP read-only hints do not grant viewer access. Reviewed live-screen and caller-data tools use `read_screen`; stored files, device data and unknown tools require `read_data`. Aliases share canonical policy and stronger overrides take precedence. Optional image sources, environment-backed config fields and file open plans require `read_data`. Anchor locators permit live accessibility/OCR; image templates require `read_data` and VLM requests require `drive_input`. Read-only invocation rejects capture artifacts and VLM branches, and its catalogue excludes caller-selected ADB executables. MCP CI annotations return formatted lines without writing to stdout. Unreviewed plugin and WebRunner initialization tools are omitted from read-only catalogues and require dependency-specific review.

Host read-only mode applies the same restrictions to explicitly supplied registries and later registrations. Both admission and refreshed invocation check mixed arguments. Configured MCP failure screenshots require a writable tool and a refreshed caller with drive authority; readonly calls and viewers never trigger them. This does not promise that every dependency or diagnostic read has no initialization side effects.
