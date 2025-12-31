"""Unit tests for article_extractor.constants module."""

from article_extractor.constants import (
    BYLINE_RE,
    COMMA_RE,
    LINK_DENSITY_THRESHOLD,
    MIN_CHAR_THRESHOLD,
    MIN_PARAGRAPH_LENGTH,
    MIN_WORD_COUNT,
    NEGATIVE_SCORE_HINTS,
    NEGATIVE_SCORE_RE,
    OK_MAYBE_CANDIDATES,
    OK_MAYBE_RE,
    PHOTO_HINTS_RE,
    POSITIVE_SCORE_HINTS,
    POSITIVE_SCORE_RE,
    PRESERVE_TAGS,
    READABILITY_ASSET_RE,
    SCORABLE_TAGS,
    STRIP_TAGS,
    TAG_SCORES,
    TOP_CANDIDATES_COUNT,
    UNLIKELY_CANDIDATES,
    UNLIKELY_CANDIDATES_RE,
    UNLIKELY_ROLES,
)
import pytest


@pytest.mark.unit
class TestTagScores:
    """Test TAG_SCORES dictionary."""

    def test_div_positive_score(self):
        """DIV should have positive score (content container)."""
        assert TAG_SCORES["div"] == 5

    def test_article_positive_score(self):
        """ARTICLE should have positive score."""
        assert TAG_SCORES["article"] == 5

    def test_h1_negative_score(self):
        """H1 should have negative score (heading, not container)."""
        assert TAG_SCORES["h1"] == -5

    def test_footer_elements_negative(self):
        """Form and list elements should be negative."""
        assert TAG_SCORES["form"] == -3
        assert TAG_SCORES["ul"] == -3
        assert TAG_SCORES["ol"] == -3

    def test_all_headings_negative(self):
        """All heading tags should have -5 score."""
        for h in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            assert TAG_SCORES[h] == -5, f"{h} should be -5"


@pytest.mark.unit
class TestUnlikelyCandidates:
    """Test unlikely candidate patterns."""

    def test_unlikely_list_contains_common_boilerplate(self):
        """UNLIKELY_CANDIDATES should include common boilerplate terms."""
        assert "sidebar" in UNLIKELY_CANDIDATES
        assert "footer" in UNLIKELY_CANDIDATES
        assert "comment" in UNLIKELY_CANDIDATES
        assert "nav" in UNLIKELY_CANDIDATES

    def test_unlikely_regex_matches_footer(self):
        """Regex should match footer class."""
        assert UNLIKELY_CANDIDATES_RE.search("page-footer")
        assert UNLIKELY_CANDIDATES_RE.search("footer-widget")

    def test_unlikely_regex_matches_sidebar(self):
        """Regex should match sidebar class."""
        assert UNLIKELY_CANDIDATES_RE.search("sidebar-left")
        assert UNLIKELY_CANDIDATES_RE.search("right-sidebar")

    def test_unlikely_regex_case_insensitive(self):
        """Regex should be case insensitive."""
        assert UNLIKELY_CANDIDATES_RE.search("FOOTER")
        assert UNLIKELY_CANDIDATES_RE.search("SideBar")

    def test_ok_maybe_overrides_unlikely(self):
        """OK_MAYBE patterns should include article, content, main."""
        assert "article" in OK_MAYBE_CANDIDATES
        assert "content" in OK_MAYBE_CANDIDATES
        assert "main" in OK_MAYBE_CANDIDATES

    def test_ok_maybe_regex_matches(self):
        """OK_MAYBE regex should match content patterns."""
        assert OK_MAYBE_RE.search("article-content")
        assert OK_MAYBE_RE.search("main-column")


@pytest.mark.unit
class TestPositiveNegativeHints:
    """Test positive and negative score hint patterns."""

    def test_positive_hints_include_content_terms(self):
        """Positive hints should include content-related terms."""
        assert "article" in POSITIVE_SCORE_HINTS
        assert "content" in POSITIVE_SCORE_HINTS
        assert "post" in POSITIVE_SCORE_HINTS

    def test_positive_regex_matches_article_class(self):
        """Positive regex should match article-related classes."""
        assert POSITIVE_SCORE_RE.search("post-content")
        assert POSITIVE_SCORE_RE.search("article-body")
        assert POSITIVE_SCORE_RE.search("entry-content")

    def test_negative_hints_include_boilerplate_terms(self):
        """Negative hints should include boilerplate terms."""
        assert "footer" in NEGATIVE_SCORE_HINTS
        assert "sidebar" in NEGATIVE_SCORE_HINTS
        assert "comment" in NEGATIVE_SCORE_HINTS

    def test_negative_regex_matches_sidebar_class(self):
        """Negative regex should match boilerplate classes."""
        assert NEGATIVE_SCORE_RE.search("sidebar-widget")
        assert NEGATIVE_SCORE_RE.search("footer-nav")
        assert NEGATIVE_SCORE_RE.search("comment-section")


@pytest.mark.unit
class TestPhotoHints:
    """Test photo/image hint patterns."""

    def test_photo_regex_matches_figure(self):
        """Should match figure-related classes."""
        assert PHOTO_HINTS_RE.search("article-figure")
        assert PHOTO_HINTS_RE.search("photo-gallery")
        assert PHOTO_HINTS_RE.search("image-container")


@pytest.mark.unit
class TestReadabilityAsset:
    """Test Readability asset pattern."""

    def test_readability_asset_matches(self):
        """Should match entry-content-asset class."""
        assert READABILITY_ASSET_RE.search("entry-content-asset")
        assert READABILITY_ASSET_RE.search("entry-content-asset image")


@pytest.mark.unit
class TestThresholds:
    """Test threshold constants."""

    def test_min_char_threshold(self):
        """MIN_CHAR_THRESHOLD should be 500."""
        assert MIN_CHAR_THRESHOLD == 500

    def test_min_paragraph_length(self):
        """MIN_PARAGRAPH_LENGTH should be 25."""
        assert MIN_PARAGRAPH_LENGTH == 25

    def test_min_word_count(self):
        """MIN_WORD_COUNT should be 150."""
        assert MIN_WORD_COUNT == 150

    def test_top_candidates_count(self):
        """TOP_CANDIDATES_COUNT should be 5."""
        assert TOP_CANDIDATES_COUNT == 5

    def test_link_density_threshold(self):
        """LINK_DENSITY_THRESHOLD should be 0.25."""
        assert LINK_DENSITY_THRESHOLD == 0.25


@pytest.mark.unit
class TestUnlikelyRoles:
    """Test ARIA roles to filter."""

    def test_navigation_role_included(self):
        """Navigation role should be filtered."""
        assert "navigation" in UNLIKELY_ROLES
        assert "menu" in UNLIKELY_ROLES

    def test_dialog_roles_included(self):
        """Dialog roles should be filtered."""
        assert "dialog" in UNLIKELY_ROLES
        assert "alertdialog" in UNLIKELY_ROLES


@pytest.mark.unit
class TestBylinePattern:
    """Test byline detection pattern."""

    def test_byline_matches_author(self):
        """Should match author-related classes."""
        assert BYLINE_RE.search("byline")
        assert BYLINE_RE.search("post-author")
        assert BYLINE_RE.search("p-author h-card")


@pytest.mark.unit
class TestCommaPattern:
    """Test comma detection pattern."""

    def test_comma_pattern_finds_commas(self):
        """Should find commas in text."""
        text = "one, two, three, four"
        matches = COMMA_RE.findall(text)
        assert len(matches) == 3


@pytest.mark.unit
class TestTagSets:
    """Test tag sets for preservation and stripping."""

    def test_preserve_tags_include_content_elements(self):
        """Preserve tags should include content elements."""
        assert "p" in PRESERVE_TAGS
        assert "a" in PRESERVE_TAGS
        assert "pre" in PRESERVE_TAGS
        assert "code" in PRESERVE_TAGS
        assert "h1" in PRESERVE_TAGS

    def test_strip_tags_include_boilerplate(self):
        """Strip tags should include non-content elements."""
        assert "script" in STRIP_TAGS
        assert "style" in STRIP_TAGS
        assert "nav" in STRIP_TAGS
        assert "footer" in STRIP_TAGS

    def test_no_overlap_preserve_strip(self):
        """Preserve and strip sets should not overlap."""
        overlap = PRESERVE_TAGS & STRIP_TAGS
        assert len(overlap) == 0, f"Overlapping tags: {overlap}"


@pytest.mark.unit
class TestScorableTags:
    """Test scorable tag set."""

    def test_scorable_includes_paragraphs(self):
        """Scorable tags should include paragraph."""
        assert "p" in SCORABLE_TAGS

    def test_scorable_includes_sections(self):
        """Scorable tags should include section and headings."""
        assert "section" in SCORABLE_TAGS
        assert "h2" in SCORABLE_TAGS
        assert "h3" in SCORABLE_TAGS
