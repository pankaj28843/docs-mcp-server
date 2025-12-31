"""Unit tests for code-friendly analyzer.

The code-friendly analyzer preserves technical tokens like CamelCase,
underscores, and dot-notation that are common in code documentation.
"""

import pytest

from docs_mcp_server.search.analyzers import CodeFriendlyAnalyzer, get_analyzer


@pytest.mark.unit
class TestCodeFriendlyAnalyzer:
    """Code-friendly analyzer preserves code tokens."""

    def test_preserves_camelcase_tokens(self):
        analyzer = CodeFriendlyAnalyzer()
        tokens = analyzer("QuerySet ModelForm BaseModel")

        # CamelCase should be preserved (lowercased)
        texts = [t.text for t in tokens]
        assert "queryset" in texts
        assert "modelform" in texts
        assert "basemodel" in texts

    def test_preserves_underscore_tokens(self):
        analyzer = CodeFriendlyAnalyzer()
        tokens = analyzer("get_queryset __init__ user_id")

        # Underscores preserved as part of tokens
        texts = [t.text for t in tokens]
        assert "get_queryset" in texts
        assert "__init__" in texts
        assert "user_id" in texts

    def test_preserves_dotted_module_names(self):
        analyzer = CodeFriendlyAnalyzer()
        tokens = analyzer("torch.optim torch.nn.Module numpy.ndarray")

        # Dots preserved, modules kept together
        texts = [t.text for t in tokens]
        # Should have both full module and parts for matching
        assert any("torch" in t for t in texts)
        assert any("optim" in t for t in texts)

    def test_no_stemming_applied(self):
        analyzer = CodeFriendlyAnalyzer()
        tokens = analyzer("running optimization configuration")

        # No stemming - words preserved as-is (lowercased)
        texts = [t.text for t in tokens]
        assert "running" in texts
        assert "optimization" in texts
        assert "configuration" in texts

    def test_removes_stopwords(self):
        analyzer = CodeFriendlyAnalyzer()
        tokens = analyzer("the QuerySet is a useful class")

        texts = [t.text for t in tokens]
        # Stopwords removed
        assert "the" not in texts
        assert "is" not in texts
        assert "a" not in texts
        # Content words preserved
        assert "queryset" in texts
        assert "useful" in texts
        assert "class" in texts

    def test_registered_in_factory(self):
        analyzer = get_analyzer("code-friendly")
        assert isinstance(analyzer, CodeFriendlyAnalyzer)


@pytest.mark.unit
class TestCodeTokenizer:
    """CodeTokenizer handles code-specific patterns."""

    def test_splits_on_whitespace(self):
        from docs_mcp_server.search.analyzers import CodeTokenizer

        tokenizer = CodeTokenizer()
        tokens = list(tokenizer("hello world test"))

        texts = [t.text for t in tokens]
        assert texts == ["hello", "world", "test"]

    def test_preserves_underscores_and_dots(self):
        from docs_mcp_server.search.analyzers import CodeTokenizer

        tokenizer = CodeTokenizer()
        tokens = list(tokenizer("get_queryset torch.nn.Module"))

        texts = [t.text for t in tokens]
        assert "get_queryset" in texts
        assert "torch.nn.Module" in texts

    def test_handles_special_chars(self):
        from docs_mcp_server.search.analyzers import CodeTokenizer

        tokenizer = CodeTokenizer()
        tokens = list(tokenizer("foo() bar[] baz<>"))

        texts = [t.text for t in tokens]
        # Parentheses, brackets, angle brackets are separators
        assert "foo" in texts
        assert "bar" in texts
        assert "baz" in texts
