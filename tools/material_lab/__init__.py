"""Experimental, offline authoring tools for SonicMatter material research.

This package is deliberately separate from the Godot runtime.  It may analyze
and bake audio, but it is never imported by a shipped game or the audio thread.
"""

from .analysis import AnalysisOptions, analyze_impacts
from .godot_compiler import compile_godot_kit, validate_godot_compile_plan
from .kit import validate_kit
from .proposal import validate_proposal
from .render import ARM_NAMES, RenderOptions, render_recipe
from .rights import RIGHTS_ACTIONS, validate_rights

__all__ = [
    "ARM_NAMES",
    "RIGHTS_ACTIONS",
    "AnalysisOptions",
    "RenderOptions",
    "analyze_impacts",
    "compile_godot_kit",
    "render_recipe",
    "validate_godot_compile_plan",
    "validate_kit",
    "validate_proposal",
    "validate_rights",
]

__version__ = "0.1.0-experimental"
