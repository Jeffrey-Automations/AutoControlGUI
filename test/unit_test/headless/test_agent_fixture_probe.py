"""Exercise static diagnostics, bounded helper ownership and shutdown without native execution."""
from concurrent.futures import CancelledError
from io import BytesIO
import json
from pathlib import Path
import sys
import threading

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime
from je_auto_control.utils.agent_runtime import fixture_probe, fixture_worker
from je_auto_control.utils.agent_runtime.errors import AgentControlBusy, AgentTaskError
from je_auto_control.utils.agent_runtime.fixture_probe import FixtureProbes
from je_auto_control.utils.agent_runtime.fixture_worker import FixtureInspectionWorker
from je_auto_control.utils.agent_runtime.target_config import AgentTargetProfile
from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.rbac.authorization import AuthorizationContext, authorization_scope
from je_auto_control.utils.rbac.deferred import DeferredAuthorization
from je_auto_control.utils.rbac.users import UserStore
from headless.test_agent_fixture_profiles import config


@pytest.fixture
def profile(tmp_path):
    return AgentTargetProfile.from_dict(config(tmp_path))


class Channel:
    def __init__(self, profile):
        self.worker = FixtureInspectionWorker(BytesIO(), BytesIO(), path=profile.settings["config_path"],
                                               expected_sha256=profile.settings["config_sha256"])
        self.retired = False
        self.fail_close = False
        self.operations = []

    def request(self, operation, payload, *, check, **_kwargs):
        check()
        self.operations.append(operation)
        return self.worker._dispatch(operation, payload)

    def close(self):
        if self.fail_close:
            raise AgentTaskError("injected retirement failure")
        self.retired = True


def test_worker_bootstrap_is_inert_and_only_inspection_reads_files(profile, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("native target constructed")

    monkeypatch.setattr(fixture_worker, "create_target", forbidden)
    channel = Channel(profile)
    path = profile.settings["config_path"]
    saved = Path(path).read_bytes()
    Path(path).unlink()
    assert channel.worker._dispatch("bootstrap", {}) == {"protocol": 1, "fixture_inspection": 1}
    with pytest.raises(AgentTaskError, match="deployment is invalid"):
        channel.worker._dispatch("inspect_fixture", {})
    Path(path).write_bytes(saved)
    report = channel.worker._dispatch("inspect_fixture", {})
    assert report["status"] == "static_artifacts_ready"
    assert report["native_evidence"] == "not_recorded" and report["fixture_execution"] == "not_run"
    assert not any(key in json.dumps(report) for key in (path, "baseline", "challenge"))


@pytest.mark.parametrize("operation,payload", [
    ("configure", {}), ("observe", {}), ("cleanup", {}), ("perform", {}), ("probe_browser", {}),
    ("bootstrap", {"path": "other"}), ("inspect_fixture", {"pid": 1}), ("inspect_fixture", []),
])
def test_worker_rejects_mutation_and_task_selected_inputs(profile, operation, payload):
    with pytest.raises(AgentTaskError):
        Channel(profile).worker._dispatch(operation, payload)


def test_real_hidden_packaged_helper_reports_only_static_evidence(profile, tmp_path, monkeypatch):
    original = fixture_probe.owned_channel
    channels = []

    def launch(argv):
        channel = original(argv)
        channels.append(channel)
        return channel

    monkeypatch.setattr(fixture_probe, "owned_channel", launch)
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={})
    try:
        runtime.target_profiles.control("register", profile.to_dict())
        result = runtime.target_profiles.control("probe", {"name": "fixture"})
        assert result["probe"]["status"] == "static_artifacts_ready"
        assert result["probe"]["checked_bytes"] > 0
        assert result["probe"]["native_evidence"] == "not_recorded"
        assert result["probe"]["fixture_execution"] == "not_run"
        assert channels[0].retired and runtime._targets["fixture"]._channel is None
        assert not runtime._leases
        assert runtime.target_profiles.describe()["targets"][0]["readiness"] == "not_probed"
    finally:
        runtime.close()
    assert channels[0].retired


@pytest.mark.parametrize("change", [
    {"checked_bytes": True}, {"checked_bytes": 1.0}, {"checked_bytes": 0}, {"checked_bytes": 1 << 20},
    {"target": "other"}, {"config_sha256": "0" * 64}, {"native_evidence": "passed"},
    {"fixture_execution": "passed"}, {"extra": "forbidden"},
])
def test_host_rejects_false_or_unbound_evidence_and_retires(profile, monkeypatch, change):
    channel = Channel(profile)
    original = channel.request

    def request(operation, payload, **kwargs):
        report = original(operation, payload, **kwargs)
        return report | change if operation == "inspect_fixture" else report

    channel.request = request
    monkeypatch.setattr(fixture_probe, "owned_channel", lambda _argv: channel)
    probes = FixtureProbes()
    with pytest.raises(AgentTaskError, match="inspection response"):
        probes.probe(profile, DeferredAuthorization())
    assert channel.retired
    probes.close()


@pytest.mark.parametrize("bootstrap", [None, {"protocol": True, "fixture_inspection": 1},
                                     {"protocol": 1, "fixture_inspection": 1.0},
                                     {"protocol": 1, "fixture_inspection": 1, "semantic": 1}])
def test_incompatible_bootstrap_never_inspects(profile, monkeypatch, bootstrap):
    channel = Channel(profile)
    channel.request = lambda *_args, **_kwargs: bootstrap
    monkeypatch.setattr(fixture_probe, "owned_channel", lambda _argv: channel)
    probes = FixtureProbes()
    with pytest.raises(AgentTaskError, match="bootstrap"):
        probes.probe(profile, DeferredAuthorization())
    assert channel.retired
    probes.close()


def test_failed_retirement_retains_capacity_until_retry(profile, monkeypatch):
    capacity = threading.BoundedSemaphore(1)
    monkeypatch.setattr(fixture_probe, "_CAPACITY", capacity)
    channel = Channel(profile)
    channel.fail_close = True
    monkeypatch.setattr(fixture_probe, "owned_channel", lambda _argv: channel)
    probes = FixtureProbes()
    with pytest.raises(AgentTaskError, match="retirement failure"):
        probes.probe(profile, DeferredAuthorization())
    assert not capacity.acquire(blocking=False)
    with pytest.raises(AgentControlBusy):
        probes.close()
    channel.fail_close = False
    probes.close()
    probes.close()
    assert channel.retired and capacity.acquire(blocking=False)
    assert not capacity.acquire(blocking=False)
    capacity.release()


def test_runtime_shutdown_during_construction_retains_database_and_retires_late_channel(profile, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    channel = Channel(profile)
    errors = []

    def launch(_argv):
        entered.set()
        if not release.wait(5):
            raise RuntimeError("test constructor was not released")
        return channel

    monkeypatch.setattr(fixture_probe, "owned_channel", launch)
    database = tmp_path / "runtime.sqlite"
    runtime = AgentRuntime(database, targets={})
    runtime.target_profiles.control("register", profile.to_dict())

    def probe():
        try:
            runtime.target_profiles.control("probe", {"name": "fixture"})
        except AgentTaskError as error:
            errors.append(error)

    thread = threading.Thread(target=probe)
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(AgentControlBusy):
            runtime.close()
        with pytest.raises(AgentControlBusy):
            AgentRuntime(database, targets={})
        assert not runtime._closed
    finally:
        release.set()
        thread.join(5)
        runtime.close()
    assert not thread.is_alive() and len(errors) == 1
    assert channel.retired and not channel.operations
    assert not runtime.target_profiles._last_probes
    reopened = AgentRuntime(database, targets={})
    reopened.close()


def test_runtime_shutdown_after_inspection_prevents_late_publication(profile, tmp_path, monkeypatch):
    channel = Channel(profile)
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={})
    runtime.target_profiles.control("register", profile.to_dict())
    monkeypatch.setattr(fixture_probe, "owned_channel", lambda _argv: channel)
    original = runtime.target_profiles._fixture_probes.probe

    def probe(*args):
        report = original(*args)
        runtime.close()
        return report

    monkeypatch.setattr(runtime.target_profiles._fixture_probes, "probe", probe)
    with pytest.raises(AgentTaskError, match="runtime is closed"):
        runtime.target_profiles.control("probe", {"name": "fixture"})
    assert not runtime.target_profiles._last_probes and channel.retired


@pytest.mark.parametrize("fault", ["input", "cancel"])
def test_no_input_acknowledgement_and_cancellation_survives_cleanup_failure(profile, monkeypatch, fault):
    channel = Channel(profile)
    token = CancellationToken(1)

    def request(_operation, _payload, *, on_event, check, **_kwargs):
        if fault == "input":
            on_event({"kind": "mouse_press"})
        token.cancel()
        check()

    channel.request = request
    channel.fail_close = True
    monkeypatch.setattr(fixture_probe, "owned_channel", lambda _argv: channel)
    probes = FixtureProbes()
    error_type = CancelledError if fault == "cancel" else AgentTaskError
    with cancellation_scope(token), pytest.raises(error_type) as failure:
        probes.probe(profile, DeferredAuthorization())
    assert isinstance(failure.value.__cause__, AgentTaskError)
    channel.fail_close = False
    probes.close()


def test_store_revocation_is_refreshed_during_request(profile, tmp_path, monkeypatch):
    store = UserStore(tmp_path / "users.json")
    store.add_user(user_id="manager", display_name="Manager", role="admin")
    owner = AuthorizationContext("manager", "admin", store_path=str(store.path))
    channel = Channel(profile)

    def request(_operation, _payload, *, check, **_kwargs):
        store.remove_user("manager")
        check()

    channel.request = request
    monkeypatch.setattr(fixture_probe, "owned_channel", lambda _argv: channel)
    probes = FixtureProbes()
    with authorization_scope(owner), pytest.raises(AgentTaskError, match="authority is unavailable"):
        probes.probe(profile, DeferredAuthorization.capture())
    assert channel.retired
    probes.close()


def test_real_hidden_blocked_reader_is_timed_out_and_reaped(profile, tmp_path, monkeypatch):
    helper = tmp_path / "blocked_inspection.py"
    helper.write_text('''import sys
import threading
from je_auto_control.utils.agent_runtime.fixture_worker import FixtureInspectionWorker
from je_auto_control.utils.agent_runtime.parent_watch import start_parent_watch

class Blocked(FixtureInspectionWorker):
    def _dispatch(self, operation, payload):
        if operation == "inspect_fixture":
            threading.Event().wait(60)
        return super()._dispatch(operation, payload)

start_parent_watch()
Blocked(sys.stdin.buffer, sys.stdout.buffer, path=sys.argv[1], expected_sha256=sys.argv[2]).run()
''', encoding="utf-8")
    original = fixture_probe.owned_channel
    channels = []

    def launch(_argv):
        channel = original((sys.executable, "-I", "-u", str(helper), profile.settings["config_path"],
                            profile.settings["config_sha256"]))
        channels.append(channel)
        return channel

    monkeypatch.setattr(fixture_probe, "owned_channel", launch)
    monkeypatch.setattr(fixture_probe, "_INSPECTION_TIMEOUT", 0.05)
    probes = FixtureProbes()
    try:
        with pytest.raises(AgentTaskError, match="deadline"):
            probes.probe(profile, DeferredAuthorization())
        assert channels[0].retired
    finally:
        probes.close()


def test_failed_helper_cleanup_retains_runtime_database_owner(profile, tmp_path, monkeypatch):
    channel = Channel(profile)
    channel.fail_close = True
    monkeypatch.setattr(fixture_probe, "owned_channel", lambda _argv: channel)
    database = tmp_path / "runtime.sqlite"
    runtime = AgentRuntime(database, targets={})
    runtime.target_profiles.control("register", profile.to_dict())
    try:
        with pytest.raises(AgentTaskError, match="retirement failure"):
            runtime.target_profiles.control("probe", {"name": "fixture"})
        assert not runtime.target_profiles._last_probes
        with pytest.raises(AgentControlBusy):
            runtime.close()
        with pytest.raises(AgentControlBusy):
            AgentRuntime(database, targets={})
    finally:
        channel.fail_close = False
        runtime.close()
    assert channel.retired
    reopened = AgentRuntime(database, targets={})
    reopened.close()


def test_failed_constructor_releases_capacity_without_publishing(profile, monkeypatch):
    capacity = threading.BoundedSemaphore(1)
    monkeypatch.setattr(fixture_probe, "_CAPACITY", capacity)

    def launch(_argv):
        raise AgentTaskError("construction failed")

    monkeypatch.setattr(fixture_probe, "owned_channel", launch)
    probes = FixtureProbes()
    with pytest.raises(AgentTaskError, match="construction failed"):
        probes.probe(profile, DeferredAuthorization())
    probes.close()
    assert capacity.acquire(blocking=False)
    capacity.release()


def test_authority_is_rechecked_after_helper_retirement_before_publication(profile, tmp_path, monkeypatch):
    store = UserStore(tmp_path / "users.json")
    store.add_user(user_id="manager", display_name="Manager", role="admin")
    owner = AuthorizationContext("manager", "admin", store_path=str(store.path))
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={})
    runtime.target_profiles.control("register", profile.to_dict())
    channel = Channel(profile)
    monkeypatch.setattr(fixture_probe, "owned_channel", lambda _argv: channel)
    original = runtime.target_profiles._fixture_probes.probe

    def probe(*args):
        report = original(*args)
        store.remove_user("manager")
        return report

    monkeypatch.setattr(runtime.target_profiles._fixture_probes, "probe", probe)
    try:
        with authorization_scope(owner), pytest.raises(AgentTaskError, match="authority is unavailable"):
            runtime.target_profiles.control("probe", {"name": "fixture"})
        assert not runtime.target_profiles._last_probes and channel.retired
    finally:
        runtime.close()
