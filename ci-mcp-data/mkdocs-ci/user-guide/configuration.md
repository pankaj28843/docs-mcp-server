# Configuration

MkDocs is configured with a YAML configuration file in your docs directory, typically named `mkdocs.yml`.

## Minimal Configuration

The minimum required configuration is:

```yaml
site_name: My Docs
```

## Full Configuration

A more complete configuration might look like:

```yaml
site_name: My Docs
site_url: https://example.com/
nav:
    - Home: index.md
    - About: about.md
theme: readthedocs
```

## Configuration Options

### site_name

This is the name of your documentation site and will be used in the navigation bar and page titles.

### site_url

The full URL to your site. This will be added to the generated HTML.

### nav

This setting is used to determine the format and layout of the global navigation for the site.

### theme

Sets the theme of your documentation site. MkDocs includes a few built-in themes.
