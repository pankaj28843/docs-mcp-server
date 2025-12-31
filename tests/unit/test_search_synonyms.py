"""Unit tests for synonym expansion.

Synonym expansion allows common technical terms to be expanded
to their alternatives, improving recall for search queries.
"""

import pytest

from docs_mcp_server.search.synonyms import (
    DEFAULT_SYNONYMS,
    SynonymExpander,
    expand_query_terms,
)


@pytest.mark.unit
class TestSynonymExpander:
    """SynonymExpander expands terms to include synonyms."""

    def test_expands_async_to_asynchronous(self):
        expander = SynonymExpander()
        expanded = expander.expand("async")

        assert "async" in expanded
        assert "asynchronous" in expanded

    def test_expands_asynchronous_to_async(self):
        expander = SynonymExpander()
        expanded = expander.expand("asynchronous")

        assert "asynchronous" in expanded
        assert "async" in expanded

    def test_expands_auth_to_authentication(self):
        expander = SynonymExpander()
        expanded = expander.expand("auth")

        assert "auth" in expanded
        assert "authentication" in expanded
        assert "authorization" in expanded

    def test_expands_config_to_configuration(self):
        expander = SynonymExpander()
        expanded = expander.expand("config")

        assert "config" in expanded
        assert "configuration" in expanded
        assert "configure" in expanded

    def test_unknown_term_returns_itself(self):
        expander = SynonymExpander()
        expanded = expander.expand("unknownterm")

        assert expanded == {"unknownterm"}

    def test_expansion_is_case_insensitive(self):
        expander = SynonymExpander()
        expanded = expander.expand("ASYNC")

        # Should match lowercase and expand
        assert "async" in expanded
        assert "asynchronous" in expanded

    def test_custom_synonyms_override_defaults(self):
        custom = {"foo": {"bar", "baz"}}
        expander = SynonymExpander(synonyms=custom)

        expanded = expander.expand("foo")
        assert "foo" in expanded
        assert "bar" in expanded
        assert "baz" in expanded

        # Default synonyms not available with custom
        expanded_async = expander.expand("async")
        assert expanded_async == {"async"}


@pytest.mark.unit
class TestExpandQueryTerms:
    """expand_query_terms expands all terms in a query."""

    def test_expands_multiple_terms(self):
        terms = ["async", "config"]
        expanded = expand_query_terms(terms)

        # Should include original terms plus synonyms
        assert "async" in expanded
        assert "asynchronous" in expanded
        assert "config" in expanded
        assert "configuration" in expanded

    def test_empty_terms_returns_empty(self):
        expanded = expand_query_terms([])
        assert expanded == set()

    def test_preserves_non_synonym_terms(self):
        terms = ["hello", "async"]
        expanded = expand_query_terms(terms)

        assert "hello" in expanded
        assert "async" in expanded
        assert "asynchronous" in expanded


@pytest.mark.unit
class TestDefaultSynonyms:
    """DEFAULT_SYNONYMS contains common technical abbreviations."""

    def test_contains_common_abbreviations(self):
        assert "async" in DEFAULT_SYNONYMS
        assert "auth" in DEFAULT_SYNONYMS
        assert "config" in DEFAULT_SYNONYMS
        assert "db" in DEFAULT_SYNONYMS
        assert "env" in DEFAULT_SYNONYMS

    def test_synonyms_are_bidirectional_lookup(self):
        # If "async" -> "asynchronous", then "asynchronous" -> "async"
        async_synonyms = DEFAULT_SYNONYMS.get("async", set())
        if "asynchronous" in async_synonyms:
            async_full_synonyms = DEFAULT_SYNONYMS.get("asynchronous", set())
            assert "async" in async_full_synonyms
