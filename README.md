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

Windows, macOS, X11 and Wayland use different backends. Available features depend on system permissions and optional dependencies; Windows ARM64 has additional limitations. See the installation guide before choosing a deployment target.

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
