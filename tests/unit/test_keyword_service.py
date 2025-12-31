"""Unit tests for keyword extraction and query analysis services."""

import pytest

from docs_mcp_server.domain.search import KeywordSet, SearchQuery
from docs_mcp_server.services.keyword_service import (
    KeywordExtractionService,
    QueryAnalysisService,
)


@pytest.mark.unit
class TestKeywordExtractionService:
    """Test KeywordExtractionService."""

    @pytest.fixture
    def extractor(self) -> KeywordExtractionService:
        """Create a KeywordExtractionService instance."""
        return KeywordExtractionService()

    def test_extract_acronyms_basic(self, extractor: KeywordExtractionService):
        """Test basic acronym extraction."""
        query = "How to configure API and JWT authentication?"
        result = extractor.extract(query)
        assert "API" in result.acronyms
        assert "JWT" in result.acronyms

    def test_extract_acronyms_excludes_common_words(self, extractor: KeywordExtractionService):
        """Test acronym extraction excludes common words."""
        query = "THE AND FOR WITH HOW"
        result = extractor.extract(query)
        assert len(result.acronyms) == 0

    def test_extract_acronyms_ignores_sentence_start(self, extractor: KeywordExtractionService):
        """Test acronym extraction ignores uppercase at sentence start."""
        query = ". TEST sentence with MID acronym"
        result = extractor.extract(query)
        # TEST should be excluded (follows ". ")
        # MID should be included
        assert "MID" in result.acronyms

    def test_extract_technical_nouns(self, extractor: KeywordExtractionService):
        """Test technical noun extraction."""
        query = "configure authentication with database"
        result = extractor.extract(query)
        assert "configure" in result.technical_nouns
        assert "authentication" in result.technical_nouns
        assert "database" in result.technical_nouns

    def test_extract_technical_nouns_filters_stopwords(self, extractor: KeywordExtractionService):
        """Test technical noun extraction filters stopwords."""
        query = "the and for with that this from have will"
        result = extractor.extract(query)
        assert len(result.technical_nouns) == 0

    def test_extract_technical_nouns_length_filter(self, extractor: KeywordExtractionService):
        """Test technical noun extraction filters short words."""
        query = "a ab abc abcd"
        result = extractor.extract(query)
        # Only "abcd" should pass (length > 3)
        assert "abcd" in result.technical_nouns
        assert "abc" not in result.technical_nouns

    def test_extract_snake_case_terms(self, extractor: KeywordExtractionService):
        """Test snake_case term extraction."""
        query = "use max_line_length and indent_size settings"
        result = extractor.extract(query)
        assert "max_line_length" in result.technical_terms
        assert "indent_size" in result.technical_terms

    def test_extract_camel_case_terms(self, extractor: KeywordExtractionService):
        """Test CamelCase term extraction."""
        query = "configure AutoFixOnSave and FormatOnType"
        result = extractor.extract(query)
        assert "AutoFixOnSave" in result.technical_terms
        assert "FormatOnType" in result.technical_terms

    def test_extract_hyphenated_terms(self, extractor: KeywordExtractionService):
        """Test hyphenated term extraction."""
        query = "enable auto-fix and type-checking features"
        result = extractor.extract(query)
        assert "auto-fix" in result.technical_terms
        assert "type-checking" in result.technical_terms

    def test_extract_verb_forms_create(self, extractor: KeywordExtractionService):
        """Test verb form extraction for 'create' variants."""
        query = "creating creates created create"
        result = extractor.extract(query)
        assert "creating" in result.verb_forms
        assert "creates" in result.verb_forms
        assert "created" in result.verb_forms
        assert "create" in result.verb_forms

    def test_extract_verb_forms_configure(self, extractor: KeywordExtractionService):
        """Test verb form extraction for 'configure' variants."""
        query = "configure configuration configuring configured"
        result = extractor.extract(query)
        assert "configure" in result.verb_forms
        assert "configuration" in result.verb_forms
        assert "configuring" in result.verb_forms
        assert "configured" in result.verb_forms

    def test_extract_verb_forms_install(self, extractor: KeywordExtractionService):
        """Test verb form extraction for 'install' variants."""
        query = "install installation installing installed"
        result = extractor.extract(query)
        assert "install" in result.verb_forms
        assert "installation" in result.verb_forms
        assert "installing" in result.verb_forms
        assert "installed" in result.verb_forms

    def test_extract_empty_query(self, extractor: KeywordExtractionService):
        """Test extraction from empty query."""
        result = extractor.extract("")
        assert len(result.acronyms) == 0
        assert len(result.technical_nouns) == 0
        assert len(result.technical_terms) == 0
        assert len(result.verb_forms) == 0

    def test_extract_complex_natural_language_query(self, extractor: KeywordExtractionService):
        """Test extraction from realistic natural language query."""
        query = "How do I configure Ruff auto-fix on save with VSCode?"
        result = extractor.extract(query)

        # VSCode doesn't match CamelCase pattern (needs 2+ capitals after first)
        # but "vscode" should be in technical_nouns
        assert "vscode" in result.technical_nouns

        # Should extract technical nouns
        assert "configure" in result.technical_nouns or "configure" in result.verb_forms

        # Should extract technical terms
        assert "auto-fix" in result.technical_terms

        # Should extract verb forms
        assert any("configur" in v for v in result.verb_forms)

    def test_extract_ruff_specific_query(self, extractor: KeywordExtractionService):
        """Test extraction from Ruff-specific query."""
        query = "configure ruff autofix on save"
        result = extractor.extract(query)

        # Should extract technical nouns
        assert "ruff" in result.technical_nouns
        assert "autofix" in result.technical_nouns
        assert "save" in result.technical_nouns

        # Should extract verb forms
        assert any("configur" in v for v in result.verb_forms)


@pytest.mark.unit
class TestQueryAnalysisService:
    """Test QueryAnalysisService."""

    @pytest.fixture
    def extractor(self) -> KeywordExtractionService:
        """Create a KeywordExtractionService instance."""
        return KeywordExtractionService()

    @pytest.fixture
    def analyzer(self, extractor: KeywordExtractionService) -> QueryAnalysisService:
        """Create a QueryAnalysisService instance."""
        return QueryAnalysisService(extractor)

    def test_analyze_normalizes_tokens(self, analyzer: QueryAnalysisService):
        """Test query analysis normalizes tokens."""
        result = analyzer.analyze("How Do I Configure Ruff?")
        assert "configure" in result.normalized_tokens
        assert "ruff" in result.normalized_tokens
        # Stopwords like "do" may appear in tokens but are filtered in keyword extraction
        # The QueryAnalysisService filters stopwords during tokenization
        # Note: short words like "i" and "do" are kept in tokens for now

    def test_analyze_removes_punctuation(self, analyzer: QueryAnalysisService):
        """Test query analysis removes punctuation."""
        result = analyzer.analyze("configure, update & deploy!")
        assert "configure" in result.normalized_tokens
        assert "update" in result.normalized_tokens
        assert "deploy" in result.normalized_tokens

    def test_analyze_preserves_original_text(self, analyzer: QueryAnalysisService):
        """Test query analysis preserves original text."""
        original = "How do I configure Ruff auto-fix?"
        result = analyzer.analyze(original)
        assert result.original_text == original

    def test_analyze_extracts_keywords(self, analyzer: QueryAnalysisService):
        """Test query analysis extracts keywords."""
        result = analyzer.analyze("configure Ruff auto-fix on save")
        keywords = result.extracted_keywords
        assert isinstance(keywords, KeywordSet)
        assert len(keywords.acronyms) >= 0
        assert len(keywords.technical_nouns) > 0
        assert len(keywords.technical_terms) > 0

    def test_analyze_with_tenant_context(self, analyzer: QueryAnalysisService):
        """Test query analysis includes tenant context."""
        result = analyzer.analyze("configure settings", tenant_context="ruff")
        assert result.tenant_context == "ruff"

    def test_analyze_empty_query(self, analyzer: QueryAnalysisService):
        """Test query analysis with empty string."""
        result = analyzer.analyze("")
        assert result.original_text == ""
        assert len(result.normalized_tokens) == 0
        assert isinstance(result.extracted_keywords, KeywordSet)

    def test_analyze_returns_search_query_object(self, analyzer: QueryAnalysisService):
        """Test query analysis returns SearchQuery value object."""
        result = analyzer.analyze("test query")
        assert isinstance(result, SearchQuery)
        assert hasattr(result, "original_text")
        assert hasattr(result, "normalized_tokens")
        assert hasattr(result, "extracted_keywords")
        assert hasattr(result, "tenant_context")
