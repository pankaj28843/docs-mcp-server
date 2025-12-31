"""Analyzer utilities for the lightweight search stack.

This module intentionally mirrors Whoosh's composable tokenizer/filter design
without pulling in heavy dependencies. The analyzers defined here are used by
schema field definitions to transform raw text into tokens suitable for
ranking.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, MutableMapping, Sequence
from dataclasses import dataclass, field
import re
from typing import Any, Protocol


@dataclass
class Token:
    """Represents a token emitted by analyzers."""

    text: str
    position: int
    start_char: int
    end_char: int
    boost: float = 1.0
    attributes: MutableMapping[str, Any] = field(default_factory=dict)

    def copy_with(self, **updates: Any) -> Token:
        data = {
            "text": self.text,
            "position": self.position,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "boost": self.boost,
            "attributes": dict(self.attributes),
        }
        data.update(updates)
        return Token(**data)


class Analyzer(Protocol):
    """Protocol implemented by analyzers."""

    def __call__(self, text: str) -> list[Token]:  # pragma: no cover - interface definition
        ...


class Tokenizer(Protocol):
    """Protocol implemented by tokenizers."""

    def __call__(self, text: str) -> Iterator[Token]:  # pragma: no cover - interface definition
        ...


class TokenFilter(Protocol):
    """Protocol implemented by token filters."""

    def __call__(self, tokens: Iterable[Token]) -> Iterator[Token]:  # pragma: no cover - interface definition
        ...


class RegexTokenizer:
    """Regex-based tokenizer that yields word tokens."""

    def __init__(self, pattern: str = r"[\w']+", flags: int = re.UNICODE | re.MULTILINE) -> None:
        self.pattern = re.compile(pattern, flags)

    def __call__(self, text: str) -> Iterator[Token]:
        for position, match in enumerate(self.pattern.finditer(text)):
            yield Token(
                text=match.group(0),
                position=position,
                start_char=match.start(),
                end_char=match.end(),
            )


class LowercaseFilter:
    """Filter that lowercases token text."""

    def __call__(self, tokens: Iterable[Token]) -> Iterator[Token]:
        for token in tokens:
            if token.text.islower():
                yield token
            else:
                yield token.copy_with(text=token.text.lower())


DEFAULT_STOPWORDS = [
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "if",
    "in",
    "into",
    "is",
    "it",
    "no",
    "not",
    "of",
    "on",
    "or",
    "such",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "they",
    "this",
    "to",
    "was",
    "will",
    "with",
]

_SUFFIX_RULES: tuple[tuple[str, str], ...] = (
    ("ization", "ize"),
    ("ational", "ate"),
    ("fulness", "ful"),
    ("ousness", "ous"),
    ("iveness", "ive"),
    ("tional", "tion"),
    ("biliti", "ble"),
    ("lessli", "less"),
    ("entli", "ent"),
    ("enci", "ence"),
    ("anci", "ance"),
    ("izer", "ize"),
    ("abli", "able"),
    ("alli", "al"),
    ("ator", "ate"),
    ("alism", "al"),
    ("aliti", "al"),
    ("ousli", "ous"),
    ("ration", "rate"),
    ("ation", "ate"),
    ("ness", ""),
    ("ment", ""),
    ("ance", "an"),
    ("ence", "en"),
    ("able", ""),
    ("ible", ""),
)

_SIMPLE_SUFFIXES: tuple[str, ...] = ("ingly", "edly", "ing", "ed", "ly", "es", "s")


class StopFilter:
    """Removes stopwords from the stream."""

    def __init__(self, stopwords: Sequence[str] | None = None) -> None:
        vocab = stopwords if stopwords is not None else DEFAULT_STOPWORDS
        self.stopwords = {word.lower() for word in vocab}

    def __call__(self, tokens: Iterable[Token]) -> Iterator[Token]:
        for token in tokens:
            if token.text.lower() not in self.stopwords:
                yield token


class PorterStemFilter:
    """Applies a minimal Porter-style stemming routine."""

    def __init__(self) -> None:
        self._stem = _build_porter_stemmer()

    def __call__(self, tokens: Iterable[Token]) -> Iterator[Token]:
        for token in tokens:
            yield token.copy_with(text=self._stem(token.text))


def _build_porter_stemmer() -> Callable[[str], str]:
    """Return a very small Porter-like stemmer suited for docs search."""

    def stem(word: str) -> str:
        lower = word.lower()
        candidate = _strip_complex_suffix(lower)
        if candidate:
            return candidate
        fallback = _strip_simple_suffix(lower)
        if fallback:
            return fallback
        return lower

    return stem


def _strip_complex_suffix(lower: str) -> str | None:
    for suffix, replacement in _SUFFIX_RULES:
        if lower.endswith(suffix) and len(lower) - len(suffix) >= 2:
            candidate = lower[: -len(suffix)] + replacement
            if len(candidate) >= 2:
                return candidate
    return None


def _strip_simple_suffix(lower: str) -> str | None:
    for suffix in _SIMPLE_SUFFIXES:
        if lower.endswith(suffix) and len(lower) - len(suffix) >= 2:
            candidate = lower[: -len(suffix)]
            if len(candidate) >= 2:
                return candidate
    return None


class AnalyzerPipeline:
    """Composable analyzer pipeline (tokenizer + filters)."""

    def __init__(self, tokenizer: Tokenizer, filters: Sequence[TokenFilter] | None = None) -> None:
        self.tokenizer = tokenizer
        self.filters = list(filters or [])

    def __call__(self, text: str) -> list[Token]:
        stream: Iterable[Token] = self.tokenizer(text)
        for token_filter in self.filters:
            stream = token_filter(stream)
        tokens = list(stream)
        for idx, token in enumerate(tokens):  # normalize positions post-filtering
            token.position = idx
        return tokens


class KeywordAnalyzer:
    """Analyzer that treats the entire input as a single token."""

    def __call__(self, text: str) -> list[Token]:
        if not text:
            return []
        return [Token(text=text, position=0, start_char=0, end_char=len(text))]


class PathAnalyzer:
    """Analyzer for URL paths - splits on slashes and lowercases.

    Extracts path segments from URLs like "/en/5.1/topics/forms/modelforms/"
    into tokens: ["en", "5.1", "topics", "forms", "modelforms"]

    This enables matching queries like "modelforms" or "topics forms" to
    documents with matching URL path segments.

    For query text without slashes, falls back to standard word tokenization
    with stemming to maintain consistency with other text fields.
    """

    def __init__(self) -> None:
        # Fallback to standard analyzer when no slashes present (for queries)
        self._fallback_analyzer = StandardAnalyzer()

    def __call__(self, text: str) -> list[Token]:
        if not text:
            return []

        # If no slashes, treat as regular text query (use standard analyzer)
        if "/" not in text:
            return self._fallback_analyzer(text)

        # Has slashes - extract path segments
        segments = text.split("/")
        tokens: list[Token] = []
        position = 0
        char_pos = 0
        for segment in segments:
            lowered = segment.lower()
            if not lowered:  # skip empty segments
                char_pos += 1  # count the slash
                continue
            tokens.append(
                Token(
                    text=lowered,
                    position=position,
                    start_char=char_pos,
                    end_char=char_pos + len(segment),
                )
            )
            position += 1
            char_pos += len(segment) + 1  # +1 for the slash

        return tokens


class StandardAnalyzer:
    """Default analyzer wired into the schema."""

    def __init__(
        self,
        *,
        stopwords: Sequence[str] | None = None,
        apply_stemming: bool = True,
    ) -> None:
        filters: list[TokenFilter] = [LowercaseFilter(), StopFilter(stopwords)]
        if apply_stemming:
            filters.append(PorterStemFilter())
        self.pipeline = AnalyzerPipeline(RegexTokenizer(), filters)

    def __call__(self, text: str) -> list[Token]:
        return self.pipeline(text)


class CodeTokenizer:
    """Tokenizer for code documentation that preserves technical patterns.

    Unlike RegexTokenizer, this tokenizer:
    - Preserves underscores in identifiers (get_queryset, __init__)
    - Preserves dots in module paths (torch.nn.Module)
    - Keeps CamelCase tokens intact
    """

    # Match: word characters, underscores, and dots (but not leading/trailing dots)
    # Also match standalone words
    _CODE_PATTERN = re.compile(r"[\w]+(?:[._][\w]+)*", re.UNICODE)

    def __call__(self, text: str) -> Iterator[Token]:
        for position, match in enumerate(self._CODE_PATTERN.finditer(text)):
            yield Token(
                text=match.group(0),
                position=position,
                start_char=match.start(),
                end_char=match.end(),
            )


class CodeFriendlyAnalyzer:
    """Analyzer for code documentation that preserves technical tokens.

    This analyzer:
    - Preserves underscores, dots, and CamelCase patterns
    - Does NOT apply stemming (prevents 'optimization' -> 'optim' conflicts)
    - Removes stopwords
    - Lowercases for matching

    Use this for technical documentation where code patterns matter more
    than natural language variations.
    """

    def __init__(self, *, stopwords: Sequence[str] | None = None) -> None:
        filters: list[TokenFilter] = [LowercaseFilter(), StopFilter(stopwords)]
        # No stemming - code tokens should match exactly
        self.pipeline = AnalyzerPipeline(CodeTokenizer(), filters)

    def __call__(self, text: str) -> list[Token]:
        return self.pipeline(text)


_ANALYZER_FACTORIES: dict[str, Callable[[], Analyzer]] = {
    "default": lambda: StandardAnalyzer(),
    "english": lambda: StandardAnalyzer(),
    "english-nostem": lambda: StandardAnalyzer(apply_stemming=False),
    "aggressive-stem": lambda: StandardAnalyzer(),
    "code-friendly": lambda: CodeFriendlyAnalyzer(),
    "keyword": lambda: KeywordAnalyzer(),
    "path": lambda: PathAnalyzer(),
}


def get_analyzer(name: str | None) -> Analyzer:
    """Return analyzer by name, defaulting to the standard analyzer."""

    if name is None:
        return _ANALYZER_FACTORIES["default"]()
    normalized = name.lower()
    if normalized not in _ANALYZER_FACTORIES:
        msg = f"Unknown analyzer '{name}'. Available: {sorted(_ANALYZER_FACTORIES)}"
        raise ValueError(msg)
    return _ANALYZER_FACTORIES[normalized]()
