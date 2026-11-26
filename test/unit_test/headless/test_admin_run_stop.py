"""A stopped run stops ``AC_admin_poll`` and ``AC_admin_broadcast_execute`` between hosts.

The admin console skipped hosts not reached yet when its ``stop_event`` was
set or its cancellation scope cancelled, but a stoppable run's stop was not
looked at: a stopped script went on to probe, or send its actions to, every
remaining host. The HTTP calls are fakes; nothing leaves the machine.
"""
import pytest

from je_auto_control.utils.admin.admin_client import NOT_SENT_STOPPED, AdminConsoleClient
from je_auto_control.utils.executor.run_control import ExecutionStopped, StopToken, shielded, stoppable_run

_HOSTS = ("alpha", "beta", "gamma")


@pytest.fixture
def console(tmp_path):
    client = AdminConsoleClient(persist_path=tmp_path / "hosts.json", max_parallel=1)
    for label in _HOSTS:
        client.add_host(label, f"http://{label}.example", "tok")  # NOSONAR python:S5332  # reason: never contacted
    return client


def test_a_run_stop_during_a_broadcast_skips_the_hosts_not_sent_to(console, monkeypatch):
    token = StopToken("admin-broadcast")
    posted = []

    def post(host, _path, _body):
        posted.append(host.label)
        token.stop("test")
        return {"result": host.label}

    monkeypatch.setattr(console, "_http_post", post)
    with stoppable_run(token=token):
        rows = console.broadcast_execute([["AC_x"]])
    assert posted == ["alpha"]
    assert [(row["label"], row["sent"]) for row in rows] == [("alpha", True), ("beta", False), ("gamma", False)]
    assert rows[1]["error"] == NOT_SENT_STOPPED


def test_a_run_stop_during_a_poll_skips_the_rest_and_raises(console, monkeypatch):
    token = StopToken("admin-poll")
    probed = []

    def get(host, _path):
        probed.append(host.label)
        token.stop("test")
        return {}

    monkeypatch.setattr(console, "_http_get", get)
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        console.poll_all()
    assert probed == ["alpha", "alpha"]           # /sessions then /jobs of the first host only


def test_cleanup_under_a_shield_still_reaches_every_host(console, monkeypatch):
    token = StopToken("admin-shield")
    token.stop("once")
    posted = []
    monkeypatch.setattr(console, "_http_post", lambda host, _p, _b: posted.append(host.label) or {})
    with stoppable_run(token=token), shielded():
        rows = console.broadcast_execute([["AC_cleanup"]])
    assert posted == list(_HOSTS)
    assert all(row["sent"] for row in rows)
