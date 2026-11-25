"""Public entry point for physical workspace storage."""

from .impl.sqlite import Storage

__all__ = ["Storage"]
