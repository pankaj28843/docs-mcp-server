# Writing Your Docs

MkDocs pages must be authored in Markdown. MkDocs uses the Python-Markdown library to render Markdown documents to HTML.

## File Layout

Your documentation source should be written as regular Markdown files, and placed in a directory somewhere in your project.

Typically this directory will be named `docs` and will exist at the top level of your project, alongside the `mkdocs.yml` configuration file.

```
mkdocs.yml    # The configuration file.
docs/
    index.md  # The documentation homepage.
    ...       # Other markdown pages, images and other files.
```

## Index Pages

When MkDocs builds your site, it will create an `index.html` file for each Markdown file in your docs directory.

If a directory contains an `index.md` file, that file will be used to generate the `index.html` file for that directory.

## Linking to Pages

MkDocs allows you to interlink your documentation by using regular Markdown linking syntax.

```markdown
Please see the [project license](license.md) for further details.
```
