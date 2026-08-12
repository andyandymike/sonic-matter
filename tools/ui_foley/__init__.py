"""Deterministic, standard-library-only UI Foley authoring tools."""

from .bake import (
    GENERATOR_ID,
    GENERATOR_VERSION,
    BakeError,
    bake_recipe,
    load_recipe,
)

__all__ = [
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "BakeError",
    "bake_recipe",
    "load_recipe",
]
