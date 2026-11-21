"""Stage 4: drive the installed helper on an emulator through the host provider stack.

Run by ``.github/workflows/android-helper.yml`` after the instrumentation is started. It uses the
package's own ``ManagedAdbServer``, ``AndroidHelperClient`` and ``GeteventSource`` against the
emulator, and checks, on the device: the helper's boot identity, a tap begun under a fresh epoch
that settles ``completed`` with input released, a stale epoch refused at ``begin``, a long swipe
stopped by a fence, and that injected input (through the helper or ``adb shell input``) never
reaches the physical-input stream while a key written to evdev (emulator console, else
``sendevent``) does. This is emulator
evidence only; it is not real-device acceptance.
"""
from __future__ import annotations

import json
import secrets
import subprocess  # nosec B404  # reason: the fixed adb CLI sends an emulator console event in CI
import sys
import threading
import time

from je_auto_control.utils.agent_runtime.android_getevent import getevent_source
from je_auto_control.utils.agent_runtime.android_helper_client import AndroidHelperClient
from je_auto_control.utils.agent_runtime.android_transport import ManagedAdbServer

_CHECK = lambda: None  # noqa: E731  # reason: the CI script has no cancellation scope


def _transport(server: ManagedAdbServer) -> int:
    rows = [row for row in server.list_devices(timeout=10) if row.state == "device"]
    if len(rows) != 1:
        raise SystemExit(f"expected one emulator, found {len(rows)}")
    return int(rows[0].transport_id)


def _hello(client: AndroidHelperClient) -> object:
    deadline = time.monotonic() + 60
    while True:
        try:
            return client.hello(timeout=5, check=_CHECK)
        except Exception:  # noqa: BLE001  # reason: the instrumentation may still be starting; retried
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


def _settle(client: AndroidHelperClient, request_id: str, wanted: set[str], seconds: float = 20) -> object:
    deadline = time.monotonic() + seconds
    while True:
        value = client.settle(request_id, timeout=5, check=_CHECK)
        if value.status in wanted:
            return value
        if time.monotonic() > deadline:
            raise SystemExit(f"{request_id} stayed {value.status}")
        time.sleep(0.1)


def _quiet(activity: threading.Event, seconds: float) -> bool:
    activity.clear()
    return not activity.wait(seconds)


def _evdev_key(server: ManagedAdbServer, transport: int, activity: threading.Event) -> bool:
    """A key that does go through evdev must be seen: first via the emulator console, then via sendevent."""
    activity.clear()
    for value in ("1", "0"):
        subprocess.run(["adb", "emu", "event", "send", f"EV_KEY:KEY_VOLUMEDOWN:{value}"],
                       check=False, timeout=10)  # nosec B603 B607  # reason: fixed CI command
    if activity.wait(5):
        print("evdev key: emulator console event seen")
        return True
    listing = server.shell(transport, "/system/bin/getevent -lp", timeout=10).stdout.decode(errors="replace")
    print("--- getevent -lp")
    print(listing[:4000])
    nodes = server.shell(transport, "/system/bin/ls /dev/input", timeout=10).stdout.decode().split()
    for node in (name for name in nodes if name.startswith("event") and name[5:].isdigit()):
        # EV_KEY KEY_VOLUMEDOWN down/up with SYN_REPORT; a device without the key drops the code.
        script = "; ".join(f"/system/bin/sendevent /dev/input/{node} {event}"
                           for event in ("1 114 1", "0 0 0", "1 114 0", "0 0 0"))
        server.shell(transport, script, timeout=10)
    seen = activity.wait(5)
    print(f"evdev key: sendevent seen={seen}")
    return seen


def main() -> int:
    server = ManagedAdbServer("127.0.0.1", 5037)
    transport = _transport(server)
    client = AndroidHelperClient(server, lambda timeout, check: transport)
    hello = _hello(client)
    boot = server.shell(transport, "/system/bin/cat /proc/sys/kernel/random/boot_id", timeout=10)
    report: dict[str, object] = {"boot_matches": boot.stdout.decode().strip() == hello.boot_id}

    activity = threading.Event()
    source = getevent_source(server, transport)
    source.set_handler(activity.set)
    source.start()
    try:
        time.sleep(3)  # let getevent list its devices; those lines are not events
        epoch = secrets.token_hex(16)
        fence = client.fence(epoch, timeout=5, check=_CHECK)
        report["fence_clean"] = fence.inflight is None and fence.queue_empty
        tap = secrets.token_hex(16)
        report["tap_accepted"] = client.begin(tap, epoch, {"kind": "tap", "x": 100, "y": 100},
                                              timeout=5, check=_CHECK)[0]
        settled = _settle(client, tap, {"completed", "failed", "fenced"})
        report["tap_completed"] = (settled.status == "completed" and settled.input_released
                                   and settled.queue_empty and settled.epoch == epoch)
        report["helper_input_not_physical"] = _quiet(activity, 3)
        report["stale_epoch_refused"] = not client.begin(secrets.token_hex(16), "0" * 32,
                                                         {"kind": "tap", "x": 1, "y": 1},
                                                         timeout=5, check=_CHECK)[0]

        swipe = secrets.token_hex(16)
        client.begin(swipe, epoch, {"kind": "swipe", "x": 100, "y": 600, "to_x": 100, "to_y": 100,
                                    "duration_ms": 8000}, timeout=5, check=_CHECK)
        _settle(client, swipe, {"injecting"})
        client.fence(secrets.token_hex(16), timeout=5, check=_CHECK)
        stopped = _settle(client, swipe, {"fenced", "completed", "failed"})
        report["swipe_fenced"] = stopped.status == "fenced" and stopped.input_released

        activity.clear()
        server.shell(transport, "/system/bin/input tap 50 50", timeout=10)
        report["adb_input_not_physical"] = _quiet(activity, 3)

        report["evdev_key_is_physical"] = _evdev_key(server, transport, activity)
        report["source_healthy"] = source.healthy
    finally:
        source.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if all(report.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
