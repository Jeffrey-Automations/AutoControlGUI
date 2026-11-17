"""Every English GUI string has a translation in each bundled language.

A key missing from a catalogue does not fail at run time: the lookup falls
back to English, so a tab silently shows English text inside a translated
window. Seven testing tabs shipped that way (95 strings in all three
catalogues) before this check existed.
"""
import re

import pytest

from je_auto_control.gui.language_wrapper.english import english_word_dict
from je_auto_control.gui.language_wrapper.japanese import japanese_word_dict
from je_auto_control.gui.language_wrapper.simplified_chinese import simplified_chinese_word_dict
from je_auto_control.gui.language_wrapper.traditional_chinese import traditional_chinese_word_dict

CATALOGUES = {
    "Traditional_Chinese": traditional_chinese_word_dict,
    "Simplified_Chinese": simplified_chinese_word_dict,
    "Japanese": japanese_word_dict,
}
_FIELD = re.compile(r"{(\w*)}")


@pytest.mark.parametrize("name", sorted(CATALOGUES))
def test_catalogue_translates_every_english_key(name):
    missing = sorted(set(english_word_dict) - set(CATALOGUES[name]))
    assert not missing, f"{name} lacks {len(missing)} keys: {missing[:20]}"


@pytest.mark.parametrize("name", sorted(CATALOGUES))
def test_translations_keep_the_format_fields(name):
    catalogue = CATALOGUES[name]
    wrong = [
        key for key, text in english_word_dict.items()
        if isinstance(text, str) and isinstance(catalogue.get(key), str)
        and set(_FIELD.findall(text)) != set(_FIELD.findall(catalogue[key]))
    ]
    assert not wrong, f"{name} changes the format fields of: {wrong[:20]}"
