#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R code template loader — template_loader module for ctrdata package.

Loads .R template files from ctrdata/templates/ and renders them
with Jinja2 for safe variable substitution.
"""

import os
from pathlib import Path

import jinja2

# Template directory — resolved relative to this file's location
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Jinja2 environment — $ is NOT a delimiter so R code passes through unchanged
_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
    variable_start_string="{{ ",
    variable_end_string=" }}",
    block_start_string="{% ",
    block_end_string=" %}",
    comment_start_string="{# ",
    comment_end_string=" #}",
    autoescape=False,
    keep_trailing_newline=True,
)


def render(name: str, **kwargs) -> str:
    """
    Load and render an R template with the given variables.

    Args:
        name: Template name (without .R extension), e.g. "db_info"
        **kwargs: Variable substitutions for the template

    Returns:
        Rendered R code string
    """
    tmpl = _env.get_template(f"{name}.R")
    return tmpl.render(**kwargs)
