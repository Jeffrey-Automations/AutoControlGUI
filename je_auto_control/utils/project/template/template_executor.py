"""Executor scripts ``create_project_dir`` writes; each finds ``keyword/`` from its own location."""

executor_template_1: str = \
    """from pathlib import Path

from je_auto_control import execute_action, read_action_json

# Resolved from this script's location, so the project still runs after it is moved.
KEYWORD_DIR = Path(__file__).resolve().parent.parent / "keyword"

execute_action(
    read_action_json(
        str(KEYWORD_DIR / "keyword1.json")
    )
)
"""

executor_template_2: str = \
    """from pathlib import Path

from je_auto_control import execute_files, get_dir_files_as_list

# Resolved from this script's location, so the project still runs after it is moved.
KEYWORD_DIR = Path(__file__).resolve().parent.parent / "keyword"

execute_files(
    get_dir_files_as_list(
        str(KEYWORD_DIR)
    )
)
"""

bad_executor_template_1: str = \
    """
# This example is primarily intended to remind users of the importance of verifying input.
from pathlib import Path

from je_auto_control import execute_action, read_action_json

# Resolved from this script's location, so the project still runs after it is moved.
KEYWORD_DIR = Path(__file__).resolve().parent.parent / "keyword"

execute_action(
    read_action_json(
        str(KEYWORD_DIR / "bad_keyword_1.json")
    )
)
"""
