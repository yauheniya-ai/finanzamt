# Configuration file for the Sphinx documentation builder.
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

# Make the package importable without installing it
sys.path.insert(0, os.path.abspath("../src"))

# -- Project information -----------------------------------------------------
project = "finamt"
copyright = "2026, Yauheniya Varabyova"
author = "Yauheniya Varabyova"
release = "0.4.6"

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",       # Pull docstrings from source code
    "sphinx.ext.autosummary",   # Generate summary tables
    "sphinx.ext.napoleon",      # Support Google/NumPy docstring styles
    "sphinx.ext.viewcode",      # Add links to highlighted source code
    "sphinx.ext.intersphinx",   # Link to other projects' docs
    "myst_parser",              # Parse Markdown (.md) files
]

# File suffixes Sphinx will process
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# autodoc: show members in source order, include private members only when
# explicitly requested, and skip the __weakref__ attribute.
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    "member-order": "bysource",
    "exclude-members": "__weakref__",
}

autosummary_generate = True

# Napoleon settings (Google-style docstrings used in this project)
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False

# Intersphinx mapping
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}

# MyST-Parser settings
myst_enable_extensions = [
    "colon_fence",
    "deflist",
]

# -- Options for HTML output -------------------------------------------------
html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

html_theme_options = {
    "navigation_depth": 4,
    "titles_only": False,
    "logo_only": False,
    "display_version": True,
    "prev_next_buttons_location": "bottom",
    "collapse_navigation": False,
    "sticky_navigation": True,
}

html_context = {
    "display_github": True,
    "github_user": "yauheniya-ai",
    "github_repo": "finamt",
    "github_version": "main",
    "conf_py_path": "/docs/",
}
