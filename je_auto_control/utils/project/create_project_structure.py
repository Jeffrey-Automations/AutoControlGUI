from os import getcwd
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple


from je_auto_control.utils.json.json_file import write_action_json
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.project.template.template_executor import (
    executor_template_1, executor_template_2, bad_executor_template_1
)
from je_auto_control.utils.project.template.template_keyword import (
    template_keyword_1, template_keyword_2, bad_template_1
)

_project_lock = Lock()
_TEMPLATE_PLACEHOLDER = "{temp}"  # noqa: S101  # reason: literal sentinel substituted in templates


def create_dir(dir_name: str) -> None:
    """
    Create directory if not exists.
    建立目錄 (若不存在則建立)

    :param dir_name: 目錄名稱 Directory name
    """
    Path(dir_name).mkdir(parents=True, exist_ok=True)


def _write_file(file_path: Path, content: str) -> None:
    """
    Write content to file.
    將內容寫入檔案

    :param file_path: 檔案路徑 File path
    :param content: 要寫入的內容 Content to write
    """
    with open(file_path, "w+", encoding="utf-8") as file:
        file.write(content)


def _template_files(keyword_dir: Path, executor_dir: Path) -> List[Tuple[Path, Callable[[Path], None]]]:
    """Every file the template writes, with the call that writes it."""
    def keyword(content: Any) -> Callable[[Path], None]:
        return lambda path: write_action_json(str(path), content)

    def executor(template: str, target: Path) -> Callable[[Path], None]:
        return lambda path: _write_file(path, template.replace(_TEMPLATE_PLACEHOLDER, repr(str(target))))

    files: List[Tuple[Path, Callable[[Path], None]]] = []
    if keyword_dir.is_dir():
        files += [
            (keyword_dir / "keyword1.json", keyword(template_keyword_1)),
            (keyword_dir / "keyword2.json", keyword(template_keyword_2)),
            (keyword_dir / "bad_keyword_1.json", keyword(bad_template_1)),
        ]
    if executor_dir.is_dir():
        files += [
            (executor_dir / "executor_one_file.py", executor(executor_template_1, keyword_dir / "keyword1.json")),
            (executor_dir / "executor_bad_file.py",
             executor(bad_executor_template_1, keyword_dir / "bad_keyword_1.json")),
            (executor_dir / "executor_folder.py", executor(executor_template_2, keyword_dir)),
        ]
    return files


def create_template(parent_name: str,
                    project_path: Optional[str] = None,
                    overwrite: bool = False) -> Dict[str, List[str]]:
    """
    Create template files in keyword and executor directories.
    在 keyword 與 executor 目錄中建立範例模板檔案

    A file that already exists is left alone and listed under ``skipped``
    unless ``overwrite`` is true. 既有檔案預設不覆寫。

    :param parent_name: 專案主目錄名稱 Project parent directory name
    :param project_path: 專案路徑 Project path (預設為當前工作目錄)
    :param overwrite: 是否覆寫既有檔案 Replace files that already exist
    :return: ``{"written": [...], "skipped": [...]}`` file paths
    """
    if project_path is None:
        project_path = getcwd()
    root = Path(project_path) / parent_name
    report: Dict[str, List[str]] = {"written": [], "skipped": []}
    with _project_lock:
        for path, write in _template_files(root / "keyword", root / "executor"):
            if path.exists() and not overwrite:
                report["skipped"].append(str(path))
                continue
            write(path)
            report["written"].append(str(path))
    if report["skipped"]:
        autocontrol_logger.warning(
            "create_project_dir kept %d existing file(s); pass overwrite=True to replace them: %s",
            len(report["skipped"]), report["skipped"],
        )
    return report


def create_project_dir(project_path: Optional[str] = None,
                       parent_name: str = "AutoControl",
                       overwrite: bool = False) -> Dict[str, List[str]]:
    """
    Create project directory structure and templates.
    建立專案目錄結構並生成範例模板檔案

    Existing template files are not replaced unless ``overwrite`` is true;
    the result lists what was written and what was skipped.

    :param project_path: 專案路徑 Project path (預設為當前工作目錄)
    :param parent_name: 專案主目錄名稱 Project parent directory name
    :param overwrite: 是否覆寫既有檔案 Replace template files that already exist
    :return: ``{"written": [...], "skipped": [...]}`` file paths
    """
    autocontrol_logger.info(f"create_project_dir, project_path: {project_path}, parent_name: {parent_name}")

    if project_path is None:
        project_path = getcwd()

    # 建立 keyword 與 executor 子目錄 Create keyword and executor subdirectories
    create_dir(str(Path(project_path) / parent_name / "keyword"))
    create_dir(str(Path(project_path) / parent_name / "executor"))

    # 建立範例模板檔案 Create template files
    return create_template(parent_name, project_path, overwrite=overwrite)
