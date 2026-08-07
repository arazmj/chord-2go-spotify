from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as distribution_version

PROJECT_NAME = "chord-2go-spotify"
_FALLBACK_VERSION = "0.1.0"


def get_version() -> str:
    try:
        return distribution_version(PROJECT_NAME)
    except PackageNotFoundError:
        return _FALLBACK_VERSION


def get_version_text() -> str:
    return f"{PROJECT_NAME} {get_version()}"


__version__ = get_version()

__all__ = ["PROJECT_NAME", "__version__", "get_version", "get_version_text"]
