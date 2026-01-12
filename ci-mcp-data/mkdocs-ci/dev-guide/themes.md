# Themes

A guide to creating and distributing custom themes.

## Creating a Custom Theme

The bare minimum required for a custom theme is a single template file which defines the layout for all pages.

This template file should be named `main.html` and placed in a directory which will be the theme directory.

## Template Variables

Each template in a theme is built with the Jinja2 template engine. A number of global variables are available to all templates.

### config

The `config` variable is an instance of MkDocs' config object and is how you can access any configuration option set in `mkdocs.yml`.

### page

The `page` variable contains the metadata and content for the current page being rendered.

### nav

The `nav` variable is the site navigation object and can be used to create the site navigation.

## Packaging Themes

Themes can be packaged and distributed as Python packages. This allows themes to be easily installed and shared.

To package a theme, create a Python package with the theme files in a subdirectory.
