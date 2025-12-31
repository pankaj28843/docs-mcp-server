"""Parity test corpus for comparing pure-Python extractor vs cascading extractor.

This module defines test cases for verifying extraction quality parity between
the new pure-Python article extractor and the existing cascading extractor.
"""

# Test corpus: (url, expected_attributes)
# Each entry defines a URL and expected characteristics of the extraction
PARITY_TEST_URLS = [
    # Django docs (code-heavy, complex navigation)
    (
        "https://docs.djangoproject.com/en/5.1/topics/forms/",
        {"min_words": 500, "has_code": True, "title_contains": "form"},
    ),
    # DRF docs (API reference, code examples)
    (
        "https://www.django-rest-framework.org/api-guide/serializers/",
        {"min_words": 1000, "has_code": True, "title_contains": "serializer"},
    ),
    # FastAPI docs (modern layout, code blocks)
    (
        "https://fastapi.tiangolo.com/tutorial/first-steps/",
        {"min_words": 300, "has_code": True, "title_contains": "first"},
    ),
    # Python docs (multi-column, heavy navigation)
    (
        "https://docs.python.org/3/library/asyncio.html",
        {"min_words": 500, "has_code": True, "title_contains": "asyncio"},
    ),
]


# Sample HTML fixtures for unit tests (no network required)
SIMPLE_BLOG_POST = """<!DOCTYPE html>
<html>
<head>
    <title>Simple Blog Post | My Blog</title>
    <meta property="og:title" content="Simple Blog Post">
</head>
<body>
    <header>
        <nav>
            <a href="/">Home</a>
            <a href="/about">About</a>
            <a href="/contact">Contact</a>
        </nav>
    </header>
    <main>
        <article class="post-content">
            <h1>Simple Blog Post</h1>
            <p class="byline">By Author Name | January 1, 2025</p>
            <p>This is the introduction paragraph of our simple blog post.
            It contains enough text to be considered real content, not just
            navigation or boilerplate. The article extractor should identify
            this as the main content area.</p>
            <p>Here is the second paragraph with more detailed information.
            We're discussing the topic at length, providing valuable insights
            and explanations that readers will find useful. This paragraph
            has commas, periods, and other punctuation marks.</p>
            <h2>A Subheading</h2>
            <p>Content under the subheading continues the discussion. This
            section elaborates on specific points mentioned earlier. The
            structure helps organize the content logically.</p>
            <p>Another paragraph with even more content. We want to ensure
            that the extraction passes the minimum word count threshold.
            More text here to pad out the content a bit more for testing.</p>
            <p>Final paragraph wrapping up the blog post. Thanks for reading
            this sample content that was created specifically for testing
            the article extraction functionality.</p>
        </article>
    </main>
    <aside class="sidebar">
        <h3>Related Posts</h3>
        <ul>
            <li><a href="/post1">Related Post 1</a></li>
            <li><a href="/post2">Related Post 2</a></li>
        </ul>
    </aside>
    <footer>
        <p>Copyright 2025 My Blog</p>
        <nav>
            <a href="/privacy">Privacy</a>
            <a href="/terms">Terms</a>
        </nav>
    </footer>
</body>
</html>"""

EXPECTED_SIMPLE_BLOG = {
    "title": "Simple Blog Post",
    "min_words": 150,
    "must_contain": ["introduction paragraph", "second paragraph", "Subheading"],
    "must_not_contain": ["Related Posts", "Copyright 2025", "Privacy"],
}


CODE_HEAVY_DOCS = """<!DOCTYPE html>
<html>
<head>
    <title>API Reference - Configuration</title>
</head>
<body>
    <nav class="breadcrumbs">
        <a href="/">Docs</a> &gt; <a href="/api">API</a> &gt; Configuration
    </nav>
    <div class="sidebar">
        <ul class="nav-menu">
            <li><a href="/intro">Introduction</a></li>
            <li><a href="/install">Installation</a></li>
            <li class="active"><a href="/config">Configuration</a></li>
        </ul>
    </div>
    <main class="content">
        <h1>Configuration</h1>
        <p>This page documents the configuration options available in our
        library. Configuration is done through environment variables or
        a configuration file. We support multiple formats including JSON,
        YAML, and TOML.</p>

        <h2>Environment Variables</h2>
        <p>The following environment variables are supported:</p>
        <pre><code class="language-bash">
export API_KEY="your-api-key"
export DEBUG=true
export LOG_LEVEL=info
        </code></pre>

        <h2>Configuration File</h2>
        <p>You can also use a configuration file. Create a file named
        <code>config.json</code> in your project root:</p>
        <pre><code class="language-json">
{
    "api_key": "your-api-key",
    "debug": true,
    "log_level": "info"
}
        </code></pre>

        <h3>Python Usage</h3>
        <p>Load the configuration in your Python code:</p>
        <pre><code class="language-python">
from mylib import Config

config = Config.from_file("config.json")
# or from environment
config = Config.from_env()
        </code></pre>

        <p>The configuration object provides type-safe access to all
        settings. Invalid values will raise a ValidationError with
        a descriptive message.</p>

        <p>For more advanced usage, see the advanced configuration guide
        which covers topics like environment-specific overrides and
        secrets management.</p>
    </main>
    <footer>
        <p>Last updated: 2025-01-01</p>
    </footer>
</body>
</html>"""

EXPECTED_CODE_HEAVY = {
    "title": "Configuration",
    "min_words": 100,
    "must_contain": ["environment variables", "API_KEY", "config.json", "Config.from_file"],
    "must_not_contain": ["Introduction", "Installation", "nav-menu"],
    "has_code": True,
}


MULTI_COLUMN_NEWS = """<!DOCTYPE html>
<html>
<head>
    <title>Breaking News: Major Discovery | News Site</title>
    <meta property="og:title" content="Major Discovery Announced">
</head>
<body>
    <header class="site-header">
        <div class="logo">News Site</div>
        <nav class="main-nav">
            <a href="/news">News</a>
            <a href="/sports">Sports</a>
            <a href="/tech">Tech</a>
            <a href="/entertainment">Entertainment</a>
        </nav>
    </header>
    <div class="ad-banner">
        <img src="ad.jpg" alt="Advertisement">
        <span>Sponsored Content</span>
    </div>
    <main class="article-container">
        <article class="main-article">
            <h1>Major Discovery Announced</h1>
            <div class="article-meta">
                <span class="author">By Jane Reporter</span>
                <span class="date">December 28, 2025</span>
            </div>
            <p class="lead">Scientists have announced a groundbreaking
            discovery that could revolutionize our understanding of the
            natural world. The findings were published today in a leading
            scientific journal.</p>
            <p>The research team, led by Dr. Smith at the University,
            spent five years studying the phenomenon. Their work involved
            collecting thousands of samples from locations around the globe,
            analyzing them using advanced techniques.</p>
            <p>"This is a significant breakthrough," said Dr. Smith in a
            press conference. "We've been working toward this moment for
            years, and the implications are far-reaching."</p>
            <p>The discovery has immediate applications in medicine,
            technology, and environmental science. Several companies have
            already expressed interest in licensing the technology.</p>
            <p>Critics, however, urge caution. "While the results are
            promising, we need more independent verification," said
            Professor Jones from another institution. "Science requires
            rigorous peer review."</p>
            <p>The research was funded by multiple government agencies
            and private foundations. Full details are available in the
            published paper.</p>
        </article>
        <aside class="sidebar">
            <div class="trending">
                <h3>Trending Now</h3>
                <ul>
                    <li><a href="/story1">Other Story 1</a></li>
                    <li><a href="/story2">Other Story 2</a></li>
                    <li><a href="/story3">Other Story 3</a></li>
                </ul>
            </div>
            <div class="social-share">
                <a href="#">Share on Twitter</a>
                <a href="#">Share on Facebook</a>
            </div>
        </aside>
    </main>
    <section class="related-articles">
        <h2>Related Articles</h2>
        <div class="article-grid">
            <a href="/related1">Related Article 1</a>
            <a href="/related2">Related Article 2</a>
        </div>
    </section>
    <footer>
        <p>© 2025 News Site. All rights reserved.</p>
    </footer>
</body>
</html>"""

EXPECTED_MULTI_COLUMN = {
    "title": "Major Discovery Announced",
    "min_words": 150,  # Article content is ~163 words
    "must_contain": ["groundbreaking discovery", "Dr. Smith", "peer review"],
    "must_not_contain": ["Trending Now", "Share on Twitter", "Related Articles", "Advertisement"],
}


MINIMAL_CONTENT = """<!DOCTYPE html>
<html>
<head><title>Changelog</title></head>
<body>
    <h1>Changelog</h1>
    <p>Version 1.0.0 released.</p>
</body>
</html>"""

EXPECTED_MINIMAL = {
    "title": "Changelog",
    "max_words": 50,
    "is_minimal": True,
}


# All fixtures for parametrized tests
PARITY_FIXTURES = {
    "simple_blog_post": (SIMPLE_BLOG_POST, EXPECTED_SIMPLE_BLOG),
    "code_heavy_docs": (CODE_HEAVY_DOCS, EXPECTED_CODE_HEAVY),
    "multi_column_news": (MULTI_COLUMN_NEWS, EXPECTED_MULTI_COLUMN),
    "minimal_content": (MINIMAL_CONTENT, EXPECTED_MINIMAL),
}
