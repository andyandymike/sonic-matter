"""Deterministic, standard-library-only UI Foley authoring tools."""

from .bake import (
    GENERATOR_ID,
    GENERATOR_VERSION,
    BakeError,
    bake_recipe,
    load_recipe,
)
from .derive_recordings import (
    DERIVATIVE_SCHEMA,
    DerivativeError,
    derive_recordings,
    load_derivative_recipe,
)

__all__ = [
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "BakeError",
    "DERIVATIVE_SCHEMA",
    "DerivativeError",
    "bake_recipe",
    "derive_recordings",
    "load_derivative_recipe",
    "load_recipe",
]
