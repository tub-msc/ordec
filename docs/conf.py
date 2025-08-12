# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'ORDeC'
copyright = '2025, ORDeC Contributors'
author = 'ORDeC Contributors'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx_rtd_theme',
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.inheritance_diagram',
    'myst_nb',
    'ordec.sphinx_ext',
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store', 'conf.py', 'data_model.rst']

autodoc_default_options = {
#    'show-inheritance': True,
    'member-order': 'bysource',
    'exclude-members': 'Frozen, Mutable, Tuple',
}

napoleon_use_ivar = False
#add_module_names = False
#autodoc_class_signature = 'separated'
autodoc_inherit_docstrings = False

# Make inheritance graphs go from top to bottom instead of left to right:
inheritance_graph_attrs = dict(rankdir="TB", size='""')


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

import jupytext

nb_custom_formats = {
  ".py": ["jupytext.reads", {"fmt": "py"}]
}
