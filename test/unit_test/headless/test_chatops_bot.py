"""Tests for the chat-ops router, default handlers, and Slack adapter."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from je_auto_control.utils.chatops import (
    ChatOpsError, CommandResult, CommandRouter, SlackBot, SlackError,
)
from je_auto_control.utils.chatops.handlers import (
    cmd_run, cmd_scripts, cmd_screenshot, cmd_status,
)


# === router =================================================================

@pytest.fixture
def router() -> CommandRouter:
    return CommandRouter()


def test_router_rejects_blank_prefix():
    with pytest.raises(ChatOpsError):
        CommandRouter(prefix="")


def test_router_register_normalises_name(router):
    spec = router.register("ECHO", lambda argv, ctx: CommandResult(text="x"))
    assert spec.name == "echo"


def test_router_register_rejects_whitespace(router):
    with pytest.raises(ChatOpsError):
        router.register("bad name", lambda argv, ctx: CommandResult(text=""))


def test_router_register_rejects_blank_name(router):
    with pytest.raises(ChatOpsError):
        router.register("   ", lambda argv, ctx: CommandResult(text=""))


def test_parse_returns_none_for_non_command(router):
    assert router.parse("hello world") is None


def test_parse_returns_none_for_bare_prefix(router):
    assert router.parse("/") is None


def test_parse_tokenises_quoted_args(router):
    assert router.parse('/run "two words"') == ["run", "two words"]


def test_parse_raises_chatops_error_on_bad_quotes(router):
    with pytest.raises(ChatOpsError):
        router.parse('/run "unterminated')


def test_dispatch_returns_none_for_non_command(router):
    assert router.dispatch("hello") is None


def test_dispatch_routes_to_registered_handler(router):
    router.register(
        "ping", lambda argv, ctx: CommandResult(text="pong"),
    )
    result = router.dispatch("/ping")
    assert result is not None
    assert result.text == "pong"


def test_dispatch_unknown_command_returns_failure(router):
    result = router.dispatch("/garbage")
    assert result is not None
    assert result.succeeded is False
    assert "unknown command" in result.text


def test_dispatch_help_lists_registered_commands(router):
    router.register(
        "ping", lambda argv, ctx: CommandResult(text="pong"),
        description="reply with pong",
    )
    result = router.dispatch("/help")
    assert result is not None
    assert "/ping" in result.text


def test_dispatch_handler_chatops_error_returns_failure(router):
    def bad(_argv, _ctx):
        raise ChatOpsError("forced bad input")

    router.register("bad", bad)
    result = router.dispatch("/bad")
    assert result is not None
    assert result.succeeded is False
    assert "forced bad input" in result.text


def test_dispatch_handler_runtime_error_returns_failure(router):
    def boom(_argv, _ctx):
        raise RuntimeError("kaboom")

    router.register("boom", boom)
    result = router.dispatch("/boom")
    assert result is not None
    assert result.succeeded is False
    assert "kaboom" in result.text


def test_role_required_blocks_without_role(router):
    router.register(
        "ops", lambda argv, ctx: CommandResult(text="ok"),
        required_role="admin",
    )
    result = router.dispatch("/ops")
    assert result is not None
    assert result.succeeded is False


def test_role_required_allows_when_context_matches(router):
    router.register(
        "ops", lambda argv, ctx: CommandResult(text="ok"),
        required_role="admin",
    )
    result = router.dispatch("/ops", context={"user_role": "Admin"})
    assert result is not None
    assert result.succeeded is True


def test_unregister_drops_handler(router):
    router.register("ping", lambda argv, ctx: CommandResult(text="x"))
    assert router.unregister("ping") is True
    assert router.dispatch("/ping").succeeded is False


# === default handlers ====================================================

def _write_script(root: Path, name: str) -> Path:
    path = root / name
    path.write_text("[]", encoding="utf-8")
    return path


def test_cmd_scripts_lists_files(tmp_path):
    _write_script(tmp_path, "alpha.json")
    _write_script(tmp_path, "beta.json")
    result = cmd_scripts([], {"script_root": str(tmp_path)})
    assert "alpha.json" in result.text
    assert "beta.json" in result.text


def test_cmd_scripts_reports_empty(tmp_path):
    result = cmd_scripts([], {"script_root": str(tmp_path)})
    assert "no scripts" in result.text


def test_cmd_scripts_requires_root():
    with pytest.raises(ChatOpsError):
        cmd_scripts([], {})


def test_cmd_run_rejects_missing_arg(tmp_path):
    with pytest.raises(ChatOpsError):
        cmd_run([], {"script_root": str(tmp_path)})


def test_cmd_run_rejects_too_many_args(tmp_path):
    with pytest.raises(ChatOpsError):
        cmd_run(["a", "b"], {"script_root": str(tmp_path)})


def test_cmd_run_rejects_path_traversal(tmp_path):
    with pytest.raises(ChatOpsError):
        cmd_run(["../escape.json"], {"script_root": str(tmp_path)})


def test_cmd_run_rejects_missing_file(tmp_path):
    with pytest.raises(ChatOpsError):
        cmd_run(["nope.json"], {"script_root": str(tmp_path)})


def test_cmd_run_invokes_executor(tmp_path):
    script = _write_script(tmp_path, "do.json")
    with patch(
        "je_auto_control.utils.executor.action_executor.execute_files",
        return_value=[{"ok": True}],
    ) as mocked:
        result = cmd_run(["do.json"],
                          {"script_root": str(tmp_path)})
    mocked.assert_called_once_with([str(script)])
    assert "do.json" in result.text


def test_cmd_screenshot_invokes_screen_helper(tmp_path):
    target = tmp_path / "shot.png"
    with patch(
        "je_auto_control.wrapper.auto_control_screen.screenshot",
    ) as mocked:
        result = cmd_screenshot(["shot.png"], {"screenshot_dir": str(tmp_path)})
    mocked.assert_called_once_with(file_path=str(target))
    assert result.artifact_path == str(target)


def test_cmd_status_renders_recent_runs():
    class _FakeRow:
        status = "succeeded"
        source_type = "scheduler"
        source_id = "job-1"
        started_at = "2026-01-01T00:00:00"
        duration_seconds = 1.25

    with patch(
        "je_auto_control.utils.run_history.history_store"
        ".default_history_store.list_runs",
        return_value=[_FakeRow()],
    ):
        result = cmd_status([], {})
    assert "scheduler:job-1" in result.text


def test_cmd_status_handles_empty_history():
    with patch(
        "je_auto_control.utils.run_history.history_store"
        ".default_history_store.list_runs",
        return_value=[],
    ):
        result = cmd_status([], {})
    assert "no recent runs" in result.text


# === Slack adapter =======================================================

def test_slack_bot_rejects_bad_token():
    router = CommandRouter()
    with pytest.raises(SlackError):
        SlackBot(token="bad", channel_id="C1", router=router)


def test_slack_bot_rejects_blank_channel():
    router = CommandRouter()
    with pytest.raises(SlackError):
        SlackBot(token="xoxb-abc", channel_id="", router=router)


def test_slack_bot_rejects_short_poll_interval():
    router = CommandRouter()
    with pytest.raises(SlackError):
        SlackBot(token="xoxb-abc", channel_id="C1",
                  router=router, poll_interval_s=0.1)


def test_slack_bot_request_refuses_non_slack_url():
    bot = SlackBot(token="xoxb-abc", channel_id="C1",
                    router=CommandRouter())
    with pytest.raises(SlackError):
        bot._request("https://attacker.example/api", method="GET")


def test_slack_poll_once_dispatches_new_messages(tmp_path):
    router = CommandRouter()
    captured: list = []
    router.register(
        "ping", lambda argv, ctx: captured.append(ctx) or CommandResult(
            text="pong",
        ),
    )
    # A position is given: a bot with none runs nothing on its first poll.
    bot = SlackBot(token="xoxb-abc", channel_id="C1", router=router,
                   last_seen_ts="0", state_path=str(tmp_path / "slack.json"))

    def fake_get(method, params):
        if method == "auth.test":
            return {"ok": True, "user_id": "U_BOT"}
        return {
            "ok": True,
            "messages": [
                {"ts": "100.5", "user": "U2", "text": "/ping"},
            ],
        }

    posts: list = []

    def fake_post(method, payload):
        posts.append((method, payload))
        return {"ok": True}

    with patch.object(bot, "_api_get", side_effect=fake_get), \
         patch.object(bot, "_api_post", side_effect=fake_post):
        count = bot.poll_once()
    assert count == 1
    assert captured
    assert captured[0]["slack_user"] == "U2"
    assert posts
    assert posts[0][0] == "chat.postMessage"
    assert posts[0][1]["text"] == "pong"
    assert bot.last_seen_ts == "100.5"


def test_slack_poll_once_skips_bot_messages(tmp_path):
    router = CommandRouter()
    bot = SlackBot(token="xoxb-abc", channel_id="C1", router=router,
                   last_seen_ts="0", state_path=str(tmp_path / "slack.json"))

    def fake_get(method, params):
        return {
            "ok": True,
            "messages": [
                {"ts": "1", "subtype": "bot_message", "text": "/ping"},
            ],
        }

    with patch.object(bot, "_api_get", side_effect=fake_get), \
         patch.object(bot, "_api_post", return_value={"ok": True}):
        assert bot.poll_once() == 0


# === executor / MCP / façade ============================================

def test_executor_registers_chatops_dispatch():
    from je_auto_control.utils.executor.action_executor import executor
    assert "AC_chatops_dispatch" in executor.known_commands()


def test_executor_chatops_dispatch_round_trips(tmp_path):
    _write_script(tmp_path, "demo.json")
    from je_auto_control.utils.executor.action_executor import executor
    handler = executor.event_dict["AC_chatops_dispatch"]
    result = handler("/scripts", script_root=str(tmp_path))
    assert result["matched"] is True
    assert "demo.json" in result["text"]


def test_executor_chatops_dispatch_no_match():
    from je_auto_control.utils.executor.action_executor import executor
    handler = executor.event_dict["AC_chatops_dispatch"]
    assert handler("plain text", script_root=None) == {"matched": False}


def test_mcp_factory_registers_chatops_tool():
    from je_auto_control.utils.mcp_server.tools import (
        build_default_tool_registry,
    )
    names = {tool.name for tool in build_default_tool_registry()}
    assert "ac_chatops_dispatch" in names


def test_facade_exports_chatops_api():
    import je_auto_control as ac
    for name in ("CommandRouter", "SlackBot", "ChatOpsError",
                  "register_chatops_default_commands"):
        assert hasattr(ac, name)


def test_command_result_to_dict_round_trips():
    result = CommandResult(text="ok", succeeded=True,
                            metadata={"k": [1, 2, 3]})
    data = result.to_dict()
    assert json.dumps(data)  # JSON-safe
    assert data["text"] == "ok"


# === Slack: never replay the channel history =============================
# A bot started with no position read up to ~1,000 old messages and ran
# every command in them, so each restart re-ran the channel's past /run's.

class _History:
    """``conversations.history`` from memory; honours ``oldest`` and ``limit``."""

    def __init__(self, *messages):
        self.messages = [dict(message) for message in messages]
        self.calls: list = []

    def say(self, ts, text, user="U2"):
        self.messages.append({"ts": ts, "user": user, "text": text})

    def api_get(self, method, params):
        if method == "auth.test":
            return {"ok": True, "user_id": "U_BOT"}
        self.calls.append(dict(params))
        newest_first = sorted(self.messages, key=lambda m: float(m["ts"]), reverse=True)
        if "oldest" in params:
            newest_first = [m for m in newest_first if float(m["ts"]) > float(params["oldest"])]
        return {"ok": True, "messages": newest_first[:int(params.get("limit", 100))]}


def _ping_bot(state_path, history, ran, handler=None, **options):
    router = CommandRouter()
    router.register("ping", handler or (
        lambda argv, ctx: ran.append(ctx["slack_ts"]) or CommandResult(text="pong")))
    bot = SlackBot(token="xoxb-abc", channel_id="C1", router=router,
                   state_path=str(state_path), **options)
    bot._api_get = history.api_get
    bot._api_post = lambda method, payload: {"ok": True}
    return bot


def _saved_ts(state_path):
    return json.loads(Path(state_path).read_text(encoding="utf-8"))["last_seen_ts"]


def test_slack_first_start_runs_none_of_the_history(tmp_path):
    history = _History({"ts": "100.1", "user": "U2", "text": "/ping old"},
                       {"ts": "100.2", "user": "U2", "text": "/ping older"})
    ran: list = []
    state = tmp_path / "slack.json"
    bot = _ping_bot(state, history, ran)
    assert bot.poll_once() == 0
    assert ran == []
    assert bot.last_seen_ts == "100.2"
    assert _saved_ts(state) == "100.2"
    assert history.calls[0]["limit"] == 1, "the start position needs one message, not the history"
    history.say("100.3", "/ping new")
    assert bot.poll_once() == 1
    assert ran == ["100.3"]


def test_slack_first_start_on_an_empty_channel_starts_from_now(tmp_path):
    state = tmp_path / "slack.json"
    bot = _ping_bot(state, _History(), [])
    assert bot.poll_once() == 0
    assert float(_saved_ts(state)) > 1_000_000_000


def test_slack_restart_resumes_after_the_saved_position(tmp_path):
    history = _History({"ts": "5", "user": "U2", "text": "/ping"})
    ran: list = []
    state = tmp_path / "slack.json"
    first = _ping_bot(state, history, ran, last_seen_ts="0")
    assert first.poll_once() == 1
    history.say("6", "/ping")
    restarted = _ping_bot(state, history, ran)
    assert restarted.poll_once() == 1
    assert ran == ["5", "6"], "the restart ran message 5 again"
    assert history.calls[-1]["oldest"] == "5"


def test_slack_a_message_is_recorded_before_its_command_runs(tmp_path):
    history = _History({"ts": "7", "user": "U2", "text": "/ping"})
    state = tmp_path / "slack.json"
    seen_by_handler: list = []

    def handler(_argv, _ctx):
        seen_by_handler.append(_saved_ts(state))
        return CommandResult(text="pong")

    bot = _ping_bot(state, history, [], handler, last_seen_ts="0")
    assert bot.poll_once() == 1
    assert seen_by_handler == ["7"]


def test_slack_a_position_that_cannot_be_saved_runs_nothing(tmp_path, monkeypatch):
    from je_auto_control.utils.chatops import slack_bot as module
    history = _History({"ts": "7", "user": "U2", "text": "/ping"})
    ran: list = []
    bot = _ping_bot(tmp_path / "slack.json", history, ran, last_seen_ts="0")

    def refuse(*_args, **_kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(module, "write_json_dict", refuse)
    with pytest.raises(SlackError):
        bot.poll_once()
    assert ran == []
    assert bot.last_seen_ts == "0"


def test_slack_messages_at_or_before_the_position_are_skipped(tmp_path):
    # Slack's `oldest` is exclusive, but an answer that still includes the
    # boundary (or older messages) must not run them again.
    history = _History({"ts": "9", "user": "U2", "text": "/ping"},
                       {"ts": "10", "user": "U2", "text": "/ping"})
    ran: list = []
    bot = _ping_bot(tmp_path / "slack.json", history, ran, last_seen_ts="9")
    bot._fetch_messages = lambda: list(reversed(history.messages))
    assert bot.poll_once() == 1
    assert ran == ["10"]


def test_slack_a_damaged_state_file_is_moved_aside_and_replays_nothing(tmp_path):
    state = tmp_path / "slack.json"
    state.write_text("{not json", encoding="utf-8")
    history = _History({"ts": "3", "user": "U2", "text": "/ping"})
    ran: list = []
    bot = _ping_bot(state, history, ran)
    assert bot.poll_once() == 0
    assert ran == []
    assert list(tmp_path.glob("slack.json.corrupt-*"))
    assert _saved_ts(state) == "3"


def test_slack_a_state_file_of_another_channel_is_not_used(tmp_path):
    state = tmp_path / "slack.json"
    state.write_text(json.dumps({"channel_id": "C_OTHER", "last_seen_ts": "1"}), encoding="utf-8")
    history = _History({"ts": "2", "user": "U2", "text": "/ping"})
    ran: list = []
    assert _ping_bot(state, history, ran).poll_once() == 0
    assert ran == []


def test_slack_state_defaults_to_the_user_folder():
    bot = SlackBot(token="xoxb-abc", channel_id="C1/x", router=CommandRouter())
    assert bot.state_file == Path.home() / ".je_auto_control" / "chatops" / "slack_C1_x.json"
