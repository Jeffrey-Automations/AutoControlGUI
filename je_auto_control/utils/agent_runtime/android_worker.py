"""Owned Android remote worker for one host-reviewed profile, driven through the device helper.

Started only by ``target_factory`` with the profile's settings as its single argument. It selects
the reviewed ADB endpoint, starts the ``getevent`` physical-input source on that transport, and
serves the shared remote worker with an ``AndroidRemoteAdapter`` whose control provider is the
helper-backed ``HelperControlProvider``. The device helper itself must already be installed and
running (``am instrument -w je.autocontrol.helper/.HelperInstrumentation``); this worker never
installs or starts anything on the device, so a missing helper fails readiness instead.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from je_auto_control.utils.agent_runtime.android_adapter import AndroidRemoteAdapter
from je_auto_control.utils.agent_runtime.android_getevent import getevent_source
from je_auto_control.utils.agent_runtime.android_helper_client import AndroidHelperClient
from je_auto_control.utils.agent_runtime.android_helper_provider import HelperControlProvider
from je_auto_control.utils.agent_runtime.android_profile import android_settings
from je_auto_control.utils.agent_runtime.android_session import AndroidDeviceSession
from je_auto_control.utils.agent_runtime.android_transport import ManagedAdbServer
from je_auto_control.utils.agent_runtime.remote_worker import serve_remote_worker
from je_auto_control.utils.exception.cancellation import cancellation_checkpoint


def build_adapter(config: Any, *, server: Any = None) -> AndroidRemoteAdapter:
    """Construct the adapter for one reviewed profile; the physical source starts before any request."""
    settings = android_settings(config)
    server = server if server is not None else ManagedAdbServer("127.0.0.1", settings["adb_port"])
    session = AndroidDeviceSession(server, serial=settings["serial"], physical_id=settings["physical_id"],
                                   package=settings["package"], user=settings["user"])
    source = getevent_source(server, session.transport(5, cancellation_checkpoint))
    source.start()
    try:
        provider = HelperControlProvider(AndroidHelperClient(server, session.transport), source,
                                         idle_seconds=settings["idle_seconds"])
    except BaseException:
        source.close()
        raise
    return AndroidRemoteAdapter(session, control=provider)


def main() -> None:
    """Serve the remote worker for the settings given as the only argument."""
    if len(sys.argv) != 2:
        raise SystemExit("android_worker takes exactly one settings argument")
    config = json.loads(sys.argv[1])
    serve_remote_worker(lambda: build_adapter(config))


if __name__ == "__main__":
    main()
