"""Unit tests for article_extractor.scorer module."""

from article_extractor.cache import ExtractionCache
from article_extractor.scorer import (
    count_commas,
    get_class_weight,
    get_tag_score,
    is_unlikely_candidate,
    score_paragraph,
)
from justhtml import JustHTML
import pytest


@pytest.fixture
def cache() -> ExtractionCache:
    """Create fresh ExtractionCache for each test."""
    return ExtractionCache()


@pytest.mark.unit
class TestGetTagScore:
    """Test tag scoring function."""

    def test_div_score(self):
        """DIV should return 5."""
        assert get_tag_score("div") == 5

    def test_article_score(self):
        """ARTICLE should return 5."""
        assert get_tag_score("article") == 5

    def test_h1_score(self):
        """H1 should return -5."""
        assert get_tag_score("h1") == -5

    def test_unknown_tag(self):
        """Unknown tag returns 0."""
        assert get_tag_score("custom-element") == 0

    def test_case_insensitive(self):
        """Tag scoring is case insensitive."""
        assert get_tag_score("DIV") == 5
        assert get_tag_score("Article") == 5


# Tests that require JustHTML parsing
@pytest.mark.unit
class TestGetClassWeightWithJustHTML:
    """Test class weight scoring with real JustHTML nodes."""

    def test_positive_class_adds_weight(self):
        """Class with positive pattern adds +25."""
        doc = JustHTML('<div class="article-content">text</div>')
        nodes = doc.query("div")
        assert len(nodes) == 1
        weight = get_class_weight(nodes[0])
        assert weight >= 25

    def test_negative_class_subtracts_weight(self):
        """Class with negative pattern subtracts -25."""

        doc = JustHTML('<div class="sidebar-widget">text</div>')
        nodes = doc.query("div")
        assert len(nodes) == 1
        weight = get_class_weight(nodes[0])
        assert weight <= -25

    def test_neutral_class(self):
        """Class without patterns returns 0."""

        doc = JustHTML('<div class="container">text</div>')
        nodes = doc.query("div")
        assert len(nodes) == 1
        weight = get_class_weight(nodes[0])
        assert weight == 0

    def test_photo_hint_bonus(self):
        """Photo hint class adds +10."""

        doc = JustHTML('<div class="figure-image">text</div>')
        nodes = doc.query("div")
        assert len(nodes) == 1
        weight = get_class_weight(nodes[0])
        assert weight >= 10


@pytest.mark.unit
class TestIsUnlikelyCandidate:
    """Test unlikely candidate detection."""

    def test_sidebar_is_unlikely(self):
        """Sidebar class should be unlikely."""

        doc = JustHTML('<div class="sidebar">content</div>')
        nodes = doc.query("div")
        assert is_unlikely_candidate(nodes[0])

    def test_footer_is_unlikely(self):
        """Footer class should be unlikely."""

        doc = JustHTML('<div class="footer">content</div>')
        nodes = doc.query("div")
        assert is_unlikely_candidate(nodes[0])

    def test_article_not_unlikely(self):
        """Article class should NOT be unlikely."""

        doc = JustHTML('<div class="article">content</div>')
        nodes = doc.query("div")
        assert not is_unlikely_candidate(nodes[0])

    def test_article_sidebar_not_unlikely(self):
        """Sidebar with article pattern should NOT be unlikely (whitelist)."""

        doc = JustHTML('<div class="sidebar article-sidebar">content</div>')
        nodes = doc.query("div")
        # Should not be unlikely because "article" is in ok_maybe
        assert not is_unlikely_candidate(nodes[0])


@pytest.mark.unit
class TestScoreParagraph:
    """Test paragraph scoring."""

    def test_short_paragraph_zero_score(self, cache: ExtractionCache):
        """Very short paragraph returns 0."""

        doc = JustHTML("<p>Short</p>")
        nodes = doc.query("p")
        score = score_paragraph(nodes[0], cache)
        assert score == 0  # Below MIN_PARAGRAPH_LENGTH

    def test_normal_paragraph_positive_score(self, cache: ExtractionCache):
        """Normal paragraph gets positive score."""

        text = "This is a paragraph with enough content, including commas, to get a score."
        doc = JustHTML(f"<p>{text}</p>")
        nodes = doc.query("p")
        score = score_paragraph(nodes[0], cache)
        assert score > 0

    def test_commas_increase_score(self, cache: ExtractionCache):
        """More commas = higher score."""

        doc1 = JustHTML("<p>This is text without any punctuation marks here</p>")
        doc2 = JustHTML("<p>This, is, text, with, many, commas, here</p>")
        score1 = score_paragraph(doc1.query("p")[0], cache)
        score2 = score_paragraph(doc2.query("p")[0], cache)
        assert score2 > score1

    def test_length_increases_score(self, cache: ExtractionCache):
        """Longer text = higher score (up to 3 bonus)."""

        short = "<p>" + "word " * 20 + "</p>"  # ~100 chars
        long = "<p>" + "word " * 80 + "</p>"  # ~400 chars

        doc_short = JustHTML(short)
        doc_long = JustHTML(long)

        score_short = score_paragraph(doc_short.query("p")[0], cache)
        score_long = score_paragraph(doc_long.query("p")[0], cache)

        assert score_long > score_short


@pytest.mark.unit
class TestCountCommas:
    """Test comma counting function (now in scorer module)."""

    def test_no_commas(self):
        """Text without commas returns 0."""
        assert count_commas("no commas here") == 0

    def test_single_comma(self):
        """Text with one comma returns 1."""
        assert count_commas("hello, world") == 1

    def test_multiple_commas(self):
        """Text with multiple commas."""
        assert count_commas("one, two, three, four") == 3

    def test_comma_with_extra_spaces(self):
        """Commas with varying whitespace."""
        assert count_commas("one,  two,   three") == 2
