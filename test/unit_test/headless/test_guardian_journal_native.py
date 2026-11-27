"""The guardian journal's recovery suites, wherever Linux has a C compiler.

The whole owner-service suite needs glibc headers with ``PIDFD_GET_INFO`` (see
``test_owner_service_native.py``), which the CI runners do not have, so it skips there. The
journal code uses none of that, so its two suites are built and run on their own with the same
flags: recovery picks the newest valid slot, an interrupted or partial read is retried, and a
read that fails outright refuses recovery instead of falling back to an older record.
"""
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3] / "native" / "owner_service"
SUITES = {
    "guardian_journal_acceptance": ["guardian_journal_acceptance.c", "guardian_journal.c"],
    "guardian_journal_io_acceptance": ["guardian_journal_io_acceptance.c"],
}


def _checks():
    spec = importlib.util.spec_from_file_location("owner_run_checks", ROOT / "tests" / "run_checks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("suite", sorted(SUITES))
def test_journal_suite_passes(suite):
    if not sys.platform.startswith("linux"):
        pytest.skip("the owner service is Linux-only")
    if shutil.which(os.environ.get("CC", "cc")) is None:
        pytest.skip("no C compiler")
    checks = _checks()
    with tempfile.TemporaryDirectory(prefix="guardian-journal-") as directory:
        work = Path(directory)
        built = checks.compile_(work, SUITES[suite], suite, ["-DNO_ACCEPTANCE_BUILD"])
        assert built["exit"] == 0, built["stderr"]
        result = checks.run([str(work / suite)])
    assert result["exit"] == 0, result
