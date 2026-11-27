from pathlib import Path

from je_auto_control import execute_files, get_dir_files_as_list

# Resolved from this script's location, so the project still runs after it is moved.
KEYWORD_DIR = Path(__file__).resolve().parent.parent / "keyword"

execute_files(
    get_dir_files_as_list(
        str(KEYWORD_DIR)
    )
)
