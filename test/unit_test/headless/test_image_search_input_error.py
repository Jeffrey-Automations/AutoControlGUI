"""An image search that could not run is not an image that is absent.

``ImageNotFoundException`` used to mean both "searched, not there" and "could
not search" (a missing or unreadable template, a single-colour one, a threshold
outside 0-1 or NaN). Every absence check caught it as "not there", so
``AC_assert_image(present=False)``, ``AC_wait_image_gone`` and the else branch
of ``AC_if_image_found`` succeeded on a misspelled template path. Unusable input
now raises ``ImageSearchInputException``, a sibling in the framework family,
and those consumers let it through. The screen is a synthetic frame.
"""
import math

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("cv2")
pytest.importorskip("je_open_cv")

from je_auto_control.utils.cv2_utils import template_detection  # noqa: E402
from je_auto_control.utils.exception.exceptions import (  # noqa: E402
    AutoControlAssertionException, AutoControlException, ImageNotFoundException,
    ImageSearchInputException,
)
from je_auto_control.wrapper import auto_control_image  # noqa: E402

_MISSING = "C:/nope/no_such_template.png"


@pytest.fixture
def screen(monkeypatch):
    """A smooth blob on a 300x200 frame, standing in for the real screen grab."""
    yy, xx = np.mgrid[0:200, 0:300]
    blob = (255 * np.exp(-(((xx - 150) ** 2) / 400 + ((yy - 100) ** 2) / 300))).astype(np.uint8)
    frame = Image.fromarray(np.stack([blob] * 3, axis=-1))
    monkeypatch.setattr(template_detection, "grab_logical",
                        lambda region, all_screens=True: (frame.copy(), 0, 0))
    return frame


def _absent_template():
    """A patterned template that is not on the synthetic screen."""
    rng = np.random.default_rng(7)
    return rng.integers(0, 255, (20, 20), dtype=np.uint8)


def test_the_new_type_is_a_sibling_in_the_family():
    assert issubclass(ImageSearchInputException, AutoControlException)
    assert not issubclass(ImageSearchInputException, ImageNotFoundException)
    assert not issubclass(ImageNotFoundException, ImageSearchInputException)
    # Not a builtin either: absence checks catch ValueError/TypeError as "not there".
    assert not issubclass(ImageSearchInputException, (ValueError, TypeError, OSError, RuntimeError))


@pytest.mark.parametrize("threshold", [-0.1, 1.5, 85, math.nan, "high"])
def test_an_unusable_threshold_is_input_not_absence(screen, threshold):
    with pytest.raises(ImageSearchInputException):
        auto_control_image.locate_image_center(screen.crop((130, 80, 170, 120)), threshold)


@pytest.mark.parametrize("template", [
    _MISSING,
    np.full((12, 12), 77, np.uint8),          # single colour: scores 1.0 everywhere
    np.zeros((5, 5, 2), dtype=np.uint8),       # no such colour layout
    np.zeros((2, 2, 2, 2), dtype=np.uint8),
])
def test_an_unusable_template_is_input_not_absence(screen, template):
    for find in (template_detection.find_image, template_detection.find_image_multi):
        with pytest.raises(ImageSearchInputException):
            find(template, 0.9)


def test_an_unreadable_file_is_input_not_absence(screen, tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    with pytest.raises(ImageSearchInputException, match="broken.png"):
        auto_control_image.locate_image_center(str(broken))


def test_a_template_that_is_not_there_is_still_not_found(screen):
    with pytest.raises(ImageNotFoundException):
        auto_control_image.locate_image_center(_absent_template(), 0.99)


def test_assert_absent_fails_on_a_missing_template(screen):
    from je_auto_control.utils.assertion import assert_image
    result = assert_image(_MISSING, threshold=0.9, present=False, raise_on_fail=False)
    assert result.passed is False
    assert "could not be used" in result.message
    with pytest.raises(AutoControlAssertionException):
        assert_image(_MISSING, threshold=0.9, present=False, raise_on_fail=True)


def test_assert_absent_still_passes_when_the_template_is_not_there(screen):
    from je_auto_control.utils.assertion import assert_image
    result = assert_image(_absent_template(), threshold=0.99, present=False, raise_on_fail=False)
    assert result.passed is True


def test_wait_image_gone_raises_on_a_missing_template(screen):
    from je_auto_control.utils.smart_waits import wait_until_image_gone
    with pytest.raises(ImageSearchInputException):
        wait_until_image_gone(_MISSING, detect_threshold=0.9, timeout_s=0.5, poll_interval_s=0.05)


def test_if_image_found_does_not_take_else_on_a_missing_template(screen):
    from je_auto_control.utils.executor.action_executor import Executor
    runner = Executor()
    record = runner.execute_action([
        ["AC_if_image_found", {"image": _MISSING, "threshold": 0.9,
                               "then": [["AC_set_var", {"name": "branch", "value": "then"}]],
                               "else": [["AC_set_var", {"name": "branch", "value": "else"}]]}],
    ])
    assert runner.variables.get_value("branch") is None
    assert "ImageSearchInputException" in next(iter(record.values()))


def test_if_image_found_takes_else_when_the_image_is_absent(screen, tmp_path):
    from je_auto_control.utils.executor.action_executor import Executor
    path = tmp_path / "absent.png"
    Image.fromarray(_absent_template()).save(path)
    runner = Executor()
    runner.execute_action([
        ["AC_if_image_found", {"image": str(path), "threshold": 0.99,
                               "then": [["AC_set_var", {"name": "branch", "value": "then"}]],
                               "else": [["AC_set_var", {"name": "branch", "value": "else"}]]}],
    ])
    assert runner.variables.get_value("branch") == "else"


def test_a_device_frame_refuses_unusable_input_as_input():
    from je_auto_control.wrapper.device_frame import DeviceFrame
    screen = Image.fromarray(np.random.default_rng(3).integers(0, 255, (120, 160, 3), dtype=np.uint8))
    frame = DeviceFrame(image=screen, point_size=screen.size)
    for template, threshold in ((np.full((12, 12), 77, np.uint8), 0.9), (_MISSING, 0.9),
                                (np.asarray(screen.crop((10, 10, 40, 40))), math.nan)):
        with pytest.raises(ImageSearchInputException):
            frame.locate_image(template, threshold)


def _fail_input(*_args, **_kwargs):
    raise ImageSearchInputException("template image not found: typo.png")


def _not_found(*_args, **_kwargs):
    raise ImageNotFoundException("not on screen")


@pytest.mark.parametrize("probe", ["trigger", "observer", "state_machine", "anchor", "scroll_find"])
def test_poll_and_branch_consumers_let_unusable_input_through(monkeypatch, probe):
    """Each reads ImageNotFoundException as "absent"; none may read input errors so."""
    monkeypatch.setattr(auto_control_image, "locate_image_center", _fail_input)
    monkeypatch.setattr(auto_control_image, "locate_all_image", _fail_input)
    with pytest.raises(ImageSearchInputException):
        _CONSUMERS[probe]()
    # ...while a plain miss still reads as absent.
    monkeypatch.setattr(auto_control_image, "locate_image_center", _not_found)
    monkeypatch.setattr(auto_control_image, "locate_all_image", _not_found)
    _CONSUMERS[probe]()


def _trigger():
    from je_auto_control.utils.triggers.trigger_engine import ImageAppearsTrigger
    return ImageAppearsTrigger(trigger_id="t", script_path="s.json", image_path="typo.png").is_fired()


def _observer():
    from je_auto_control.utils.observer.observer import image_predicate
    return image_predicate("typo.png")()


def _state_machine():
    from je_auto_control.utils.state_machine.engine import _image_found_ok
    return _image_found_ok({"if_image_found": "typo.png"}, {}, 0.0)


def _anchor():
    from je_auto_control.utils.anchor_locator import locator as anchor
    target = anchor.Locator(kind="image", template_path="typo.png")
    anchor._image_center(target)
    return anchor._image_candidates(target)


def _scroll_find():
    from je_auto_control.utils.scroll_find.scroll_find import _make_image_locator
    return _make_image_locator(0.9)("typo.png")


_CONSUMERS = {"trigger": _trigger, "observer": _observer, "state_machine": _state_machine,
              "anchor": _anchor, "scroll_find": _scroll_find}


def test_mcp_wait_for_image_raises_instead_of_timing_out(monkeypatch):
    from je_auto_control.utils.mcp_server.tools import _handlers_screen
    monkeypatch.setattr(auto_control_image, "locate_image_center", _fail_input)
    with pytest.raises(ImageSearchInputException):
        _handlers_screen.wait_for_image("typo.png", timeout=0.2, poll=0.05)


def test_pytest_keyword_wait_raises_instead_of_timing_out(monkeypatch):
    from je_auto_control.utils.pytest_plugin.keywords import keyword_wait_for_image
    monkeypatch.setattr(auto_control_image, "locate_image_center", _fail_input)
    with pytest.raises(ImageSearchInputException):
        keyword_wait_for_image("typo.png", timeout=0.2)
