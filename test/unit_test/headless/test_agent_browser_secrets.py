"""Text a page marks as secret stays out of a browser observation. No browser, no Qt."""
import pytest

from je_auto_control.utils.agent_runtime.browser_target import BrowserTarget
from je_auto_control.utils.agent_runtime.errors import AgentTaskError

PAGE = {"url": "https://app.example/a", "title": "A", "text": "public secret-note",
        "elements": [{"selector": "#reveal", "text": "secret-button", "tag": "button"},
                     {"selector": "#save", "text": "Save", "tag": "button"}],
        "frames": [{"selector": "#f", "text": "frame secret", "elements": [
                        {"selector": "#g", "text": "secret-link", "tag": "a"},
                        {"selector": "#h", "text": "Help", "tag": "a"}]},
                   {"selector": "#gone", "error": "Error"}]}


class Session:
    """``marked``: the documents showing marked text, per probe round; ``touched``: the marked selectors."""

    def __init__(self, marked, touched=("#reveal", "#g")):
        self.marked, self.touched, self.probes, self.rounds = list(marked), touched, [], 0

    def observe(self):
        return PAGE

    def visible(self, selector, frame=""):
        self.probes.append((selector, frame))
        if selector.startswith("[data-secret]"):
            if not frame:
                self.rounds += 1
            return frame in self.marked[min(self.rounds, len(self.marked)) - 1]
        assert selector.endswith(">> visible=true >> nth=0")  # several matches would fault the session
        return any(f":is({item})" in selector for item in self.touched)


def observed(session):
    target = BrowserTarget()
    target._session = session
    return target.observe()


def names(observation):
    return [element["name"] for element in observation["elements"]]


def test_a_page_that_marks_nothing_is_published_unchanged_with_one_probe_per_document():
    session = Session([set()])
    observation = observed(session)
    assert observation["text"] == "public secret-note"
    assert names(observation) == ["secret-button", "Save", "secret-link", "Help"]
    assert [frame for _selector, frame in session.probes] == ["", "", "#f"]


def test_marked_text_withholds_the_page_text_and_only_the_touched_names():
    observation = observed(Session([{"", "#f"}]))
    assert observation["text"] == "" and names(observation) == ["", "Save", "", "Help"]
    assert "secret" not in str(observation)
    assert [element["selector"] for element in observation["elements"]] == ["#reveal", "#save", "#g", "#h"]


def test_a_marked_frame_does_not_withhold_the_main_page():
    observation = observed(Session([{"#f"}]))
    assert observation["text"] == "public secret-note"
    assert names(observation) == ["secret-button", "Save", "", "Help"]


@pytest.mark.parametrize("rounds", [[{""}, set()], [set(), {""}]])
def test_marked_text_that_appears_or_disappears_around_the_observation_is_withheld(rounds):
    assert observed(Session(rounds))["text"] == ""


def test_an_unreadable_probe_never_publishes_the_page():
    session = Session([set()])

    def broken(_selector, _frame=""):
        raise RuntimeError("SECRET driver detail")
    session.visible = broken
    with pytest.raises(AgentTaskError, match="observation failed") as error:
        observed(session)
    assert "SECRET" not in str(error.value)
