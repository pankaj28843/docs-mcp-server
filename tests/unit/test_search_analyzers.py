"""Unit tests for analyzer pipelines and filters."""

import pytest

from docs_mcp_server.search import analyzers
from docs_mcp_server.search.analyzers import (
    AnalyzerPipeline,
    KeywordAnalyzer,
    LowercaseFilter,
    PathAnalyzer,
    PorterStemFilter,
    RegexTokenizer,
    StandardAnalyzer,
    StopFilter,
    Token,
    get_analyzer,
)


@pytest.fixture
def fresh_registry(monkeypatch):
    """Provide a temporary analyzer registry so tests stay isolated."""

    monkeypatch.setattr(analyzers, "_ANALYZER_FACTORIES", analyzers._ANALYZER_FACTORIES.copy())
    return analyzers._ANALYZER_FACTORIES


@pytest.mark.unit
class TestToken:
    """Token helpers produce safe copies with metadata intact."""

    def test_copy_with_preserves_metadata(self):
        token = Token(
            text="Configure",
            position=2,
            start_char=10,
            end_char=20,
            boost=1.5,
            attributes={"field": "body"},
        )

        clone = token.copy_with(text="configure", boost=2.0)
        clone.attributes["field"] = "title"

        assert clone.text == "configure"
        assert clone.position == token.position
        assert clone.start_char == token.start_char
        assert clone.end_char == token.end_char
        assert clone.boost == 2.0
        assert token.text == "Configure"
        assert token.attributes["field"] == "body"  # original attributes untouched


@pytest.mark.unit
class TestRegexTokenizer:
    """Regex tokenizer should emit positions and char offsets."""

    def test_emits_tokens_with_offsets(self):
        tokenizer = RegexTokenizer()

        tokens = list(tokenizer("Configure logging now"))

        assert [t.text for t in tokens] == ["Configure", "logging", "now"]
        assert [t.position for t in tokens] == [0, 1, 2]
        assert tokens[0].start_char == 0
        assert tokens[0].end_char == 9
        assert tokens[1].start_char == 10
        assert tokens[1].end_char == 17
        assert tokens[2].start_char == 18
        assert tokens[2].end_char == 21


@pytest.mark.unit
class TestLowercaseFilter:
    """Lowercase filter normalizes only when necessary."""

    def test_lowercases_uppercase_tokens(self):
        raw = [
            Token(text="Docs", position=0, start_char=0, end_char=4),
            Token(text="search", position=1, start_char=5, end_char=11),
        ]

        filtered = list(LowercaseFilter()(raw))

        assert filtered[0].text == "docs"
        assert filtered[1] is raw[1]  # already lowercase so original object reused


@pytest.mark.unit
class TestStopFilter:
    """Stop filters remove configured stopwords."""

    def test_default_stopwords_remove_common_terms(self):
        tokens = [
            Token(text="search", position=0, start_char=0, end_char=6),
            Token(text="and", position=1, start_char=7, end_char=10),
            Token(text="docs", position=2, start_char=11, end_char=15),
        ]

        filtered = list(StopFilter()(tokens))

        assert [t.text for t in filtered] == ["search", "docs"]

    def test_custom_stopwords_override_default_set(self):
        tokens = [
            Token(text="Search", position=0, start_char=0, end_char=6),
            Token(text="and", position=1, start_char=7, end_char=10),
            Token(text="docs", position=2, start_char=11, end_char=15),
        ]

        filtered = list(StopFilter(stopwords=["docs"])(tokens))

        assert [t.text for t in filtered] == ["Search", "and"]


@pytest.mark.unit
class TestPorterStemFilter:
    """Stemming filter applies both complex and simple suffix rules."""

    def test_handles_complex_and_simple_suffixes(self):
        tokens = [
            Token(text="running", position=0, start_char=0, end_char=7),
            Token(text="organization", position=1, start_char=8, end_char=20),
        ]

        stemmed = list(PorterStemFilter()(tokens))

        assert [t.text for t in stemmed] == ["runn", "organize"]


@pytest.mark.unit
class TestAnalyzerPipeline:
    """Pipelines should respect filter order and reset positions."""

    def test_pipeline_reindexes_after_filters(self):
        def drop_short_tokens(stream):
            for token in stream:
                if len(token.text) >= 4:
                    yield token

        pipeline = AnalyzerPipeline(RegexTokenizer(), [LowercaseFilter(), drop_short_tokens])

        tokens = pipeline("API docs and Hooks")

        assert [t.text for t in tokens] == ["docs", "hooks"]
        assert [t.position for t in tokens] == [0, 1]


@pytest.mark.unit
class TestStandardAnalyzer:
    """Standard analyzer encapsulates tokenizer + filters."""

    def test_default_pipeline_lowercases_stems_and_removes_stopwords(self):
        analyzer = StandardAnalyzer()

        tokens = analyzer("Running and TESTING analyzers")

        assert [t.text for t in tokens] == ["runn", "test", "analyzer"]
        assert [t.position for t in tokens] == [0, 1, 2]

    def test_can_disable_stemming(self):
        analyzer = StandardAnalyzer(apply_stemming=False)

        tokens = analyzer("Running and TESTING analyzers")

        assert [t.text for t in tokens] == ["running", "testing", "analyzers"]

    def test_custom_stopwords_replace_default_set(self):
        analyzer = StandardAnalyzer(stopwords=["doc"], apply_stemming=False)

        tokens = analyzer("Doc and API")

        assert [t.text for t in tokens] == ["and", "api"]


@pytest.mark.unit
class TestKeywordAnalyzer:
    """Keyword analyzer returns a single token covering the input."""

    def test_keyword_analyzer_preserves_input(self):
        analyzer = KeywordAnalyzer()

        tokens = analyzer("/docs/path/file.md")

        assert len(tokens) == 1
        assert tokens[0].text == "/docs/path/file.md"
        assert tokens[0].start_char == 0
        assert tokens[0].end_char == len("/docs/path/file.md")


@pytest.mark.unit
class TestAnalyzerRegistry:
    """Analyzer registry lookups and registrations are validated."""

    def test_get_analyzer_defaults_to_standard(self):
        analyzer = get_analyzer(None)

        assert isinstance(analyzer, StandardAnalyzer)

    def test_get_analyzer_is_case_insensitive(self):
        analyzer = get_analyzer("ENGLISH-NOSTEM")

        assert isinstance(analyzer, StandardAnalyzer)

    def test_get_analyzer_unknown_name_raises(self, fresh_registry):
        with pytest.raises(ValueError, match="Unknown analyzer"):
            get_analyzer("missing")


@pytest.mark.unit
class TestPathAnalyzer:
    """PathAnalyzer splits URL paths into searchable segments."""

    def test_splits_url_path_on_slashes(self):
        analyzer = PathAnalyzer()

        tokens = analyzer("/en/5.1/topics/forms/")

        assert [t.text for t in tokens] == ["en", "5.1", "topics", "forms"]
        assert [t.position for t in tokens] == [0, 1, 2, 3]

    def test_handles_empty_input(self):
        analyzer = PathAnalyzer()

        tokens = analyzer("")

        assert tokens == []

    def test_lowercases_path_segments(self):
        analyzer = PathAnalyzer()

        tokens = analyzer("/API/ModelForms/Reference/")

        assert [t.text for t in tokens] == ["api", "modelforms", "reference"]

    def test_filters_empty_segments(self):
        analyzer = PathAnalyzer()

        tokens = analyzer("///docs///path//")

        assert [t.text for t in tokens] == ["docs", "path"]

    def test_path_analyzer_registered_in_registry(self):
        analyzer = get_analyzer("path")

        assert isinstance(analyzer, PathAnalyzer)
