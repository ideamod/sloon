"""Public contract for physical sloon workspace storage.

Storage owns a workspace directory and the SQLite connection to the database
inside it. It configures the connection but does not create, inspect, migrate,
or interpret application-specific tables. Additional directory contents are
outside Storage's current responsibilities and are preserved.

``initialize(path)`` creates exactly ``path`` and a valid empty SQLite database
inside it. It raises ``FileExistsError`` when the path already exists and never
overwrites existing content. Parent directories must already exist.

``open(path)`` requires an existing directory and its expected regular database
file. Missing paths raise ``FileNotFoundError``; a non-directory workspace or
non-file database raises ``NotADirectoryError`` or ``FileNotFoundError``;
invalid SQLite content raises ``sqlite3.DatabaseError``. It never initializes
or repairs storage implicitly.

The returned Storage owns one connection. Repeated ``connection()`` calls
return that same connection with SQLite foreign-key enforcement enabled.
Consumers borrow it and must not close it. ``close()`` closes it; subsequent
database operations through the borrowed object follow standard sqlite3 closed-
connection behavior. Instances and connections are intended for one thread.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class Storage:
    @classmethod
    def initialize(cls, path: Path) -> "Storage": ...

    @classmethod
    def open(cls, path: Path) -> "Storage": ...

    def connection(self) -> sqlite3.Connection: ...

    def close(self) -> None: ...
