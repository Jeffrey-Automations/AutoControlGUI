from pathlib import Path

from je_auto_control import execute_action, read_executable_action_json

# Resolved from this script's location, so the project still runs after it is moved.
KEYWORD_DIR = Path(__file__).resolve().parent.parent / "keyword"

execute_action(
    read_executable_action_json(
        str(KEYWORD_DIR / "keyword1.json")
    )
)
