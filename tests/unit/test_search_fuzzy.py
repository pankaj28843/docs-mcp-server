"""Unit tests for fuzzy matching / typo correction."""

import pytest

from docs_mcp_server.search.fuzzy import (
    find_fuzzy_matches,
    get_max_edit_distance,
    levenshtein_distance,
)


@pytest.mark.unit
class TestLevenshteinDistance:
    """Tests for levenshtein_distance function."""

    def test_identical_strings(self):
        assert levenshtein_distance("hello", "hello") == 0

    def test_empty_strings(self):
        assert levenshtein_distance("", "") == 0
        assert levenshtein_distance("abc", "") == 3
        assert levenshtein_distance("", "abc") == 3

    def test_single_insertion(self):
        assert levenshtein_distance("cat", "cats") == 1

    def test_single_deletion(self):
        assert levenshtein_distance("cats", "cat") == 1

    def test_single_substitution(self):
        assert levenshtein_distance("cat", "bat") == 1

    def test_multiple_edits(self):
        assert levenshtein_distance("kitten", "sitting") == 3

    def test_completely_different(self):
        assert levenshtein_distance("abc", "xyz") == 3

    def test_case_sensitive(self):
        # Levenshtein is case-sensitive by default
        assert levenshtein_distance("Hello", "hello") == 1

    def test_common_typos(self):
        # Common programming typos
        assert levenshtein_distance("configuration", "configration") == 1
        assert levenshtein_distance("serializer", "serailizer") == 2
        assert levenshtein_distance("django", "djagno") == 2


@pytest.mark.unit
class TestGetMaxEditDistance:
    """Tests for get_max_edit_distance function."""

    def test_very_short_terms_no_fuzzy(self):
        assert get_max_edit_distance(1) == 0
        assert get_max_edit_distance(2) == 0

    def test_short_terms_one_edit(self):
        assert get_max_edit_distance(3) == 1
        assert get_max_edit_distance(4) == 1
        assert get_max_edit_distance(5) == 1

    def test_longer_terms_two_edits(self):
        assert get_max_edit_distance(6) == 2
        assert get_max_edit_distance(10) == 2
        assert get_max_edit_distance(20) == 2


@pytest.mark.unit
class TestFindFuzzyMatches:
    """Tests for find_fuzzy_matches function."""

    def test_exact_match_first(self):
        vocabulary = ["config", "configure", "configuration"]
        matches = find_fuzzy_matches("config", vocabulary)

        assert len(matches) >= 1
        assert matches[0] == ("config", 0)

    def test_finds_close_matches(self):
        vocabulary = ["serializer", "serialize", "serial"]
        # "serailizer" has distance 2 from "serializer"
        matches = find_fuzzy_matches("serailizer", vocabulary)

        match_terms = [m[0] for m in matches]
        assert "serializer" in match_terms

    def test_respects_max_distance(self):
        vocabulary = ["hello", "world", "help", "held"]
        matches = find_fuzzy_matches("helo", vocabulary, max_distance=1)

        # "helo" -> "hello" is distance 1, "help" is distance 1, "held" is 2
        match_terms = [m[0] for m in matches]
        assert "hello" in match_terms
        assert "help" in match_terms

    def test_empty_inputs(self):
        assert find_fuzzy_matches("", ["a", "b"]) == []
        assert find_fuzzy_matches("test", []) == []

    def test_no_matches_beyond_distance(self):
        vocabulary = ["xyz", "abc", "def"]
        matches = find_fuzzy_matches("completely_different", vocabulary, max_distance=2)

        assert matches == []

    def test_sorted_by_distance(self):
        vocabulary = ["test", "tests", "testing", "tast", "toast"]
        matches = find_fuzzy_matches("test", vocabulary)

        # Exact match should be first
        assert matches[0] == ("test", 0)

        # Results should be sorted by distance
        distances = [m[1] for m in matches]
        assert distances == sorted(distances)


@pytest.mark.unit
class TestFuzzyRealWorldCases:
    """Real-world test cases for fuzzy matching."""

    def test_common_django_typos(self):
        vocabulary = ["django", "models", "serializer", "viewset", "queryset"]

        # "djagno" -> "django" (distance 2, 6 chars allows 2)
        matches = find_fuzzy_matches("djagno", vocabulary)
        match_terms = [m[0] for m in matches]
        assert "django" in match_terms

        # "modls" -> "models" (distance 1, 6 chars allows 2)
        matches = find_fuzzy_matches("modls", vocabulary)
        match_terms = [m[0] for m in matches]
        assert "models" in match_terms

    def test_common_python_typos(self):
        vocabulary = ["import", "function", "class", "method", "exception"]

        # "improt" -> "import"
        matches = find_fuzzy_matches("improt", vocabulary)
        match_terms = [m[0] for m in matches]
        assert "import" in match_terms

        # "fucntion" -> "function"
        matches = find_fuzzy_matches("fucntion", vocabulary)
        match_terms = [m[0] for m in matches]
        assert "function" in match_terms

    def test_transposition_typos(self):
        # Common keyboard typos from transposed letters
        vocabulary = ["authentication", "configuration", "implementation"]

        # "authenication" (missing 't') -> "authentication"
        matches = find_fuzzy_matches("authenication", vocabulary)
        match_terms = [m[0] for m in matches]
        assert "authentication" in match_terms
