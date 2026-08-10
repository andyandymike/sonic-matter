class MaterialLabError(Exception):
    """Base class for a user-actionable Material Lab failure."""


class AudioFormatError(MaterialLabError):
    """Raised when an input or output audio contract is violated."""


class ManifestError(MaterialLabError):
    """Raised when a kit, recipe, or rights manifest fails closed."""
