"""Unit tests for sentence-boundary aware snippet extraction."""

import pytest

from docs_mcp_server.search.snippet import (
    build_smart_snippet,
    extract_sentence_snippet,
    find_sentence_end,
    find_sentence_start,
    highlight_terms_in_snippet,
)


@pytest.mark.unit
class TestFindSentenceStart:
    """Tests for find_sentence_start function."""

    def test_finds_sentence_start_after_period(self):
        text = "First sentence. Second sentence with match here."
        # Position in "Second"
        position = 20
        result = find_sentence_start(text, position)
        assert result == 16  # After ". "

    def test_returns_zero_for_beginning(self):
        text = "Only one sentence here."
        result = find_sentence_start(text, 0)
        assert result == 0

    def test_finds_start_after_question_mark(self):
        text = "What is this? This is the answer."
        position = 20  # In "This is"
        result = find_sentence_start(text, position)
        assert result == 14  # After "? "

    def test_finds_start_after_exclamation(self):
        text = "Wow! This is amazing."
        position = 10  # In "This"
        result = find_sentence_start(text, position)
        assert result == 5  # After "! "

    def test_falls_back_to_word_boundary(self):
        text = "one two three four five six"
        position = 15  # In "four"
        result = find_sentence_start(text, position, max_lookback=10)
        # Should find a word boundary
        assert result < position


@pytest.mark.unit
class TestFindSentenceEnd:
    """Tests for find_sentence_end function."""

    def test_finds_sentence_end_at_period(self):
        text = "This is a sentence. Next sentence."
        position = 5  # In "is"
        result = find_sentence_end(text, position)
        assert result == 20  # After ". "

    def test_returns_text_length_at_end(self):
        text = "Short text"
        result = find_sentence_end(text, len(text))
        assert result == len(text)

    def test_finds_end_at_question_mark(self):
        text = "What is this? And more."
        position = 5  # In "is"
        result = find_sentence_end(text, position)
        assert result == 14  # After "? "

    def test_finds_end_at_exclamation(self):
        text = "This is great! More text."
        position = 5  # In "is"
        result = find_sentence_end(text, position)
        assert result == 15  # After "! "


@pytest.mark.unit
class TestExtractSentenceSnippet:
    """Tests for extract_sentence_snippet function."""

    def test_extracts_snippet_with_context(self):
        text = "First sentence here. The match is in this sentence. Last sentence."
        match_pos = 25  # "match"
        match_len = 5

        snippet, start, end = extract_sentence_snippet(text, match_pos, match_len, max_chars=100)

        assert "match" in snippet
        assert start >= 0
        assert end <= len(snippet)

    def test_handles_empty_text(self):
        snippet, start, end = extract_sentence_snippet("", 0, 0)
        assert snippet == ""
        assert start == 0
        assert end == 0

    def test_respects_max_chars(self):
        text = "A" * 1000
        snippet, _, _ = extract_sentence_snippet(text, 500, 10, max_chars=100)
        assert len(snippet) <= 100

    def test_includes_surrounding_context(self):
        text = "Start. The important match word is here. End."
        match_pos = text.find("match")
        match_len = 5

        snippet, _, _ = extract_sentence_snippet(text, match_pos, match_len, surrounding_context=50)

        # Should have some context around "match"
        assert len(snippet) > match_len


@pytest.mark.unit
class TestHighlightTermsInSnippet:
    """Tests for highlight_terms_in_snippet function."""

    def test_highlights_single_term_plain(self):
        snippet = "The configuration is important"
        terms = ["configuration"]

        result = highlight_terms_in_snippet(snippet, terms, style="plain")

        assert "[[configuration]]" in result

    def test_highlights_single_term_html(self):
        snippet = "The configuration is important"
        terms = ["configuration"]

        result = highlight_terms_in_snippet(snippet, terms, style="html")

        assert "<mark>configuration</mark>" in result

    def test_highlights_case_insensitive(self):
        snippet = "The Configuration is important"
        terms = ["configuration"]

        result = highlight_terms_in_snippet(snippet, terms, style="plain")

        assert "[[Configuration]]" in result  # Preserves original case

    def test_highlights_multiple_terms(self):
        snippet = "The config and environment settings"
        terms = ["config", "environment"]

        result = highlight_terms_in_snippet(snippet, terms, style="plain")

        assert "[[config]]" in result
        assert "[[environment]]" in result

    def test_respects_max_highlights(self):
        snippet = "one two three four five"
        terms = ["one", "two", "three", "four", "five"]

        result = highlight_terms_in_snippet(snippet, terms, style="plain", max_highlights=2)

        # Should only highlight first 2 terms found
        highlight_count = result.count("[[")
        assert highlight_count == 2

    def test_handles_empty_snippet(self):
        result = highlight_terms_in_snippet("", ["term"])
        assert result == ""

    def test_handles_empty_terms(self):
        snippet = "Some text here"
        result = highlight_terms_in_snippet(snippet, [])
        assert result == snippet

    def test_ignores_short_terms(self):
        snippet = "A b c here"
        terms = ["A", "b"]  # Too short

        result = highlight_terms_in_snippet(snippet, terms, style="plain")

        assert "[[" not in result  # No highlights for 1-char terms

    def test_handles_overlapping_terms(self):
        """Test that overlapping terms like 'serialize' and 'serializer' don't cause nested brackets."""
        snippet = "The serializers.py file contains serializer classes"
        terms = ["serialize", "serializer", "serializers"]

        result = highlight_terms_in_snippet(snippet, terms, style="plain")

        # Should NOT have nested brackets like [[[[serialize]]r]]s
        assert "[[[[" not in result
        # Should have clean highlights
        assert "[[" in result
        # Count brackets - should be balanced
        open_count = result.count("[[")
        close_count = result.count("]]")
        assert open_count == close_count

    def test_skips_markdown_links(self):
        """Test that terms inside markdown links are not highlighted."""
        snippet = "[serializers.py](https://github.com/encode/django) provides serializer classes"
        terms = ["serializer", "serializers"]

        result = highlight_terms_in_snippet(snippet, terms, style="plain")

        # The markdown link should be preserved, no highlighting inside
        assert "[serializers.py]" in result
        # But the term outside the link should be highlighted
        assert "[[serializer]]" in result
        # Should not have nested brackets in markdown
        assert "[[[" not in result


@pytest.mark.unit
class TestBuildSmartSnippet:
    """Tests for build_smart_snippet function."""

    def test_builds_snippet_with_highlight(self):
        text = "Django is a web framework. It provides many features for building applications."
        terms = ["framework"]

        result = build_smart_snippet(text, terms, max_chars=200)

        assert "[[framework]]" in result

    def test_uses_html_style(self):
        text = "The configuration file is important."
        terms = ["configuration"]

        result = build_smart_snippet(text, terms, style="html")

        assert "<mark>configuration</mark>" in result

    def test_handles_no_match(self):
        text = "Some text without the search term."
        terms = ["nonexistent"]

        result = build_smart_snippet(text, terms, max_chars=50)

        # Should return beginning of text
        assert result.startswith("Some text")

    def test_handles_empty_text(self):
        result = build_smart_snippet("", ["term"])
        assert result == ""

    def test_handles_empty_terms(self):
        text = "Some text here that is interesting."

        result = build_smart_snippet(text, [], max_chars=50)

        # Should return beginning of text
        assert len(result) <= 50

    def test_respects_max_chars(self):
        text = "A" * 1000
        terms = ["AAAA"]

        result = build_smart_snippet(text, terms, max_chars=100)

        assert len(result) <= 150  # Some buffer for highlighting

    def test_finds_earliest_match(self):
        text = "First match here. Second match there."
        terms = ["match"]

        result = build_smart_snippet(text, terms)

        # Should highlight the first occurrence
        assert "[[match]]" in result

    def test_real_world_example(self):
        text = """Django is a high-level Python web framework that encourages rapid development
        and clean, pragmatic design. Built by experienced developers, it takes care of much of
        the hassle of web development, so you can focus on writing your app without needing to
        reinvent the wheel. It's free and open source."""

        terms = ["framework", "development"]

        result = build_smart_snippet(text, terms, max_chars=200)

        # Should have highlighted terms
        assert "[[" in result
        # Should be reasonable length
        assert len(result) <= 250


@pytest.mark.unit
class TestSnippetEdgeCases:
    """Edge case tests for snippet functions."""

    def test_handles_unicode_text(self):
        text = "Café résumé naïve. The match is here."
        terms = ["match"]

        result = build_smart_snippet(text, terms)

        assert "[[match]]" in result

    def test_handles_special_regex_chars(self):
        text = "Use file.py for configuration."
        terms = ["file.py"]  # Contains regex special char

        result = build_smart_snippet(text, terms)

        assert "[[file.py]]" in result

    def test_handles_very_long_term(self):
        text = "The supercalifragilisticexpialidocious word is here."
        terms = ["supercalifragilisticexpialidocious"]

        result = build_smart_snippet(text, terms, max_chars=100)

        assert "[[supercalifragilisticexpialidocious]]" in result

    def test_handles_term_at_beginning(self):
        text = "Configuration is key to success."
        terms = ["Configuration"]

        result = build_smart_snippet(text, terms)

        assert result.startswith("[[Configuration]]")

    def test_handles_term_at_end(self):
        text = "This is about configuration."
        terms = ["configuration"]

        result = build_smart_snippet(text, terms)

        assert "[[configuration]]" in result
