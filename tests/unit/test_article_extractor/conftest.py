"""Test fixtures for article extractor tests."""

import pytest


@pytest.fixture
def simple_article_html() -> str:
    """Simple blog post HTML for testing."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>Test Article Title | Example Site</title>
    <meta property="og:title" content="Test Article Title">
</head>
<body>
    <header>
        <nav>
            <a href="/">Home</a>
            <a href="/about">About</a>
        </nav>
    </header>
    <main>
        <article class="post-content">
            <h1>Test Article Title</h1>
            <p>This is the first paragraph of the article. It contains enough
            text to be considered content, with commas, periods, and other
            punctuation marks that indicate real prose.</p>
            <p>Here is another paragraph with more content. The article extractor
            should recognize this as the main content area because it has
            substantial text content and proper paragraph structure.</p>
            <p>A third paragraph continues the article with additional information.
            This helps ensure the content passes minimum word count thresholds
            that are used to filter out navigation and boilerplate text.</p>
            <pre><code>def example():
    return "code block"</code></pre>
            <p>The conclusion wraps up the article with final thoughts.</p>
        </article>
    </main>
    <aside class="sidebar">
        <h3>Related Posts</h3>
        <ul>
            <li><a href="/post1">Post 1</a></li>
            <li><a href="/post2">Post 2</a></li>
        </ul>
    </aside>
    <footer>
        <p>Copyright 2025</p>
    </footer>
</body>
</html>"""


@pytest.fixture
def minimal_html() -> str:
    """Minimal HTML with very little content."""
    return """<!DOCTYPE html>
<html>
<head><title>Short Page</title></head>
<body>
    <p>Too short.</p>
</body>
</html>"""


@pytest.fixture
def code_heavy_html() -> str:
    """HTML with lots of code blocks (like documentation)."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>API Documentation | Docs</title>
</head>
<body>
    <nav class="sidebar">
        <ul>
            <li><a href="/getting-started">Getting Started</a></li>
            <li><a href="/api">API Reference</a></li>
        </ul>
    </nav>
    <main class="content">
        <h1>Getting Started</h1>
        <p>This guide will help you get started with the library. Follow
        the installation instructions and then run the example code.</p>
        <h2>Installation</h2>
        <p>Install the package using pip:</p>
        <pre><code>pip install example-library</code></pre>
        <h2>Quick Start</h2>
        <p>Here is a simple example to get you started:</p>
        <pre><code>from example import Client

client = Client(api_key="your-key")
result = client.query("hello world")
print(result)</code></pre>
        <p>For more advanced usage, see the API reference documentation.</p>
    </main>
    <footer>
        <p>Documentation licensed under MIT</p>
    </footer>
</body>
</html>"""


@pytest.fixture
def navigation_heavy_html() -> str:
    """HTML with heavy navigation but also real content."""
    return """<!DOCTYPE html>
<html>
<head><title>Page with Heavy Navigation</title></head>
<body>
    <header class="site-header">
        <nav class="main-nav">
            <a href="/">Home</a>
            <a href="/products">Products</a>
            <a href="/services">Services</a>
            <a href="/about">About</a>
            <a href="/contact">Contact</a>
            <a href="/blog">Blog</a>
            <a href="/support">Support</a>
            <a href="/careers">Careers</a>
        </nav>
        <div class="breadcrumb">
            <a href="/">Home</a> &gt;
            <a href="/blog">Blog</a> &gt;
            <span>Current Article</span>
        </div>
    </header>
    <div class="container">
        <article class="article-content">
            <h1>The Main Article</h1>
            <p>This is the actual content of the page. Despite all the
            navigation above, this should be extracted as the main content.
            The article contains several paragraphs of meaningful text.</p>
            <p>The second paragraph adds more substance to the article.
            It discusses important topics and provides value to readers
            who came here looking for specific information.</p>
            <p>Finally, the third paragraph concludes the discussion with
            a summary of the key points covered in this article.</p>
        </article>
        <aside class="sidebar-widget">
            <h4>Popular Articles</h4>
            <ul>
                <li><a href="/article1">Article 1</a></li>
                <li><a href="/article2">Article 2</a></li>
                <li><a href="/article3">Article 3</a></li>
            </ul>
        </aside>
    </div>
    <footer class="site-footer">
        <nav class="footer-nav">
            <a href="/privacy">Privacy</a>
            <a href="/terms">Terms</a>
        </nav>
    </footer>
</body>
</html>"""
