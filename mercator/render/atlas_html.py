"""Deprecated — atlas rendering moved to `mercator.render.atlas` package.

Kept as a re-export shim while internal callers migrate. Will be removed
in a future release. New code should import from `mercator.render.atlas`
directly.
"""
from mercator.render.atlas import (  # noqa: F401
    render,
    render_single_project,
    render_repo_index,
)
