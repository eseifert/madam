from madam.core import Madam as Madam

_default_madam: Madam | None = None


def __getattr__(name: str):
    global _default_madam
    if name == 'default_madam':
        if _default_madam is None:
            _default_madam = Madam()
        return _default_madam
    raise AttributeError(f"module 'madam' has no attribute {name!r}")
