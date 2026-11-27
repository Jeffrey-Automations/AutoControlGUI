"""Generated executor scripts find their keyword files from where the script is.

``create_project_dir`` used to write the keyword path it had at creation time
into each executor script as a literal, and the three committed examples under
``AutoControl/executor`` held a path on the author's machine. A moved or
cloned project then read keyword files from a place that no longer had them.
The scripts are run here with the facade's execute / read calls replaced by
recorders, so no action from the keyword files is performed.
"""
import runpy
import shutil
from pathlib import Path

import pytest

import je_auto_control
from je_auto_control.utils.project.create_project_structure import create_project_dir

ROOT = Path(__file__).resolve().parents[3]
EXECUTORS = ("executor_one_file.py", "executor_bad_file.py", "executor_folder.py")


@pytest.fixture
def recorded(monkeypatch):
    """Replace the calls the generated scripts make; record what they are given."""
    calls = []
    monkeypatch.setattr(je_auto_control, "read_action_json", lambda path: calls.append(("read", path)) or [])
    monkeypatch.setattr(je_auto_control, "execute_action", lambda actions: calls.append(("execute", actions)))
    monkeypatch.setattr(je_auto_control, "get_dir_files_as_list",
                        lambda path: calls.append(("list", path)) or [])
    monkeypatch.setattr(je_auto_control, "execute_files", lambda files: calls.append(("files", files)))
    return calls


def _run_moved_project(tmp_path, recorded, script):
    create_project_dir(str(tmp_path / "made_here"))
    moved = tmp_path / "moved" / "AutoControl"
    moved.parent.mkdir()
    shutil.move(str(tmp_path / "made_here" / "AutoControl"), str(moved))
    shutil.rmtree(tmp_path / "made_here")
    runpy.run_path(str(moved / "executor" / script), run_name="__main__")
    return moved / "keyword", recorded[0]


@pytest.mark.parametrize("script, target", [
    ("executor_one_file.py", "keyword1.json"),
    ("executor_bad_file.py", "bad_keyword_1.json"),
])
def test_a_moved_project_reads_its_own_keyword_file(tmp_path, recorded, script, target):
    keyword_dir, (kind, path) = _run_moved_project(tmp_path, recorded, script)
    assert kind == "read"
    assert Path(path) == keyword_dir / target
    assert Path(path).is_file()


def test_a_moved_project_runs_its_own_keyword_folder(tmp_path, recorded):
    keyword_dir, (kind, path) = _run_moved_project(tmp_path, recorded, "executor_folder.py")
    assert kind == "list"
    assert Path(path) == keyword_dir
    assert Path(path).is_dir()


def test_the_scripts_do_not_depend_on_where_the_project_was_made(tmp_path):
    """No creation-time path is written into a script, so none can need quoting either."""
    for name in ("first", "second's"):
        create_project_dir(str(tmp_path / name))
    for script in EXECUTORS:
        first = (tmp_path / "first" / "AutoControl" / "executor" / script).read_text(encoding="utf-8")
        second = (tmp_path / "second's" / "AutoControl" / "executor" / script).read_text(encoding="utf-8")
        assert first == second
        assert str(tmp_path) not in first


@pytest.mark.parametrize("script", EXECUTORS)
def test_the_committed_examples_are_what_the_generator_writes(tmp_path, script):
    create_project_dir(str(tmp_path))
    generated = (tmp_path / "AutoControl" / "executor" / script).read_text(encoding="utf-8")
    committed = (ROOT / "AutoControl" / "executor" / script).read_text(encoding="utf-8")
    assert committed.replace("\r\n", "\n") == generated.replace("\r\n", "\n")
