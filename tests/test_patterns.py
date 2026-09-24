from __future__ import annotations

import pytest

from manual_cli.patterns import PatternError, parse_section_patterns


def test_parse_single_numbers():
    assert parse_section_patterns(["3"]) == [3]
    assert parse_section_patterns(["1", "3", "2"]) == [1, 2, 3]


def test_parse_range():
    assert parse_section_patterns(["2-5"]) == [2, 3, 4, 5]


def test_parse_single_element_range():
    assert parse_section_patterns(["4-4"]) == [4]


def test_parse_mixed_enumeration_and_ranges():
    assert parse_section_patterns(["1", "5-7", "12", "3-3"]) == [1, 3, 5, 6, 7, 12]


def test_parse_deduplicates_overlapping_values():
    assert parse_section_patterns(["1-3", "2", "3-5"]) == [1, 2, 3, 4, 5]


def test_parse_rejects_inverted_range():
    with pytest.raises(PatternError, match="8-3"):
        parse_section_patterns(["8-3"])


def test_parse_rejects_garbage_token():
    with pytest.raises(PatternError, match="abc"):
        parse_section_patterns(["abc"])


def test_parse_rejects_empty_token_list():
    with pytest.raises(PatternError):
        parse_section_patterns([])


def test_parse_rejects_negative_or_malformed_range():
    with pytest.raises(PatternError):
        parse_section_patterns(["-3"])
