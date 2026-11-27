"""Service ownership scopes fold case with the OS table, never Python's own case mapping."""
import hashlib
import sys

import pytest

from je_auto_control.utils.agent_runtime.service_scope import service_resource, service_scope
from je_auto_control.utils.agent_runtime.service_status import ServiceQueryError

# The NT upcase table, as probed on Windows 11: it maps é→É, ǆ→Ǆ, ÿ→Ÿ, ａ→Ａ
# and leaves ß, ı, ſ, the Kelvin sign and µ alone, unlike str.upper().
TABLE = {0xE9: 0xC9, 0x1C6: 0x1C4, 0xFF: 0x178, 0xFF41: 0xFF21}


def table(unit):
    if 0x61 <= unit <= 0x7A:
        return unit - 0x20
    return TABLE.get(unit, unit)


def test_ascii_keys_keep_the_original_scope_digest():
    expected = hashlib.sha256(b"local-scm-ascii-v1\0ownedfixture").hexdigest()
    assert service_scope("OwnedFixture") == service_scope("ownedfixture") == expected
    assert service_scope("OwnedFixture", upcase=lambda _unit: pytest.fail("ASCII needs no table")) == expected


def test_unicode_case_aliases_share_one_scope_by_the_injected_table():
    assert service_scope("Café", upcase=table) == service_scope("CAFÉ", upcase=table)
    assert service_scope("ǆ ﬀ", upcase=table) == service_scope("Ǆ ﬀ", upcase=table)
    assert service_scope("Café", upcase=table) != service_scope("Cafe", upcase=table)


def test_python_case_mapping_is_never_used_to_merge_or_split_names():
    # str.upper() maps ß to SS and ı to I; the OS table keeps them, so they stay distinct services.
    assert service_scope("Straße", upcase=table) != service_scope("STRASSE", upcase=table)
    assert service_scope("ıx", upcase=table) != service_scope("IX", upcase=table)
    # µ (U+00B5) and Μ (U+039C) are equal under str.upper() but not under the table.
    assert service_scope("µx", upcase=table) != service_scope("Μx", upcase=table)


def test_a_key_the_table_folds_to_ascii_shares_that_ascii_scope():
    folding = {0x212A: 0x4B}  # a table that maps the Kelvin sign to K
    upcase = lambda unit: folding.get(unit, table(unit))  # noqa: E731  # reason: one-line table
    assert service_scope("Key", upcase=upcase) == service_scope("Key")


def test_astral_characters_are_folded_per_utf16_unit_and_round_trip():
    scope = service_scope("svc\U0001f600", upcase=table)
    assert scope == service_scope("SVC\U0001f600", upcase=table)


@pytest.mark.parametrize("key", ["", "a/b", "a\b", "x" * 257, "Owned\u200bFixture", "a\tb", "a b",
                                 "a b", "ab", "a\ud800b", "é" * 257, "\U0001f600" * 129, 7, None])
def test_hidden_separator_control_and_oversized_keys_are_unsupported(key):
    with pytest.raises(ServiceQueryError):
        service_scope(key, upcase=table)


@pytest.mark.parametrize("mapped", [-1, 0x10000, "A", None])
def test_a_table_answer_outside_one_utf16_unit_is_refused(mapped):
    with pytest.raises(ServiceQueryError):
        service_scope("é", upcase=lambda _unit: mapped)


def test_a_table_that_splits_a_surrogate_pair_is_refused():
    with pytest.raises(ServiceQueryError):
        service_scope("\U0001f600", upcase=lambda unit: 0x41 if unit == 0xD83D else unit)


@pytest.mark.skipif(sys.platform == "win32", reason="the OS table exists on Windows")
def test_non_ascii_keys_are_unsupported_without_the_os_table():
    with pytest.raises(ServiceQueryError):
        service_scope("服務")
    assert service_scope("Owned") == service_scope("OWNED")


@pytest.mark.skipif(sys.platform != "win32", reason="uses the real NT upcase table")
def test_the_real_os_table_folds_unicode_aliases_into_one_lock(tmp_path):
    assert service_resource("Café", tmp_path) == service_resource("CAFÉ", tmp_path)
    assert service_resource("ｓｖｃ", tmp_path) == service_resource("ＳＶＣ", tmp_path)
    assert service_resource("服務", tmp_path) != service_resource("服务", tmp_path)
    assert service_scope("Straße") != service_scope("STRASSE")
    assert service_resource("Owned", tmp_path).parent == tmp_path
