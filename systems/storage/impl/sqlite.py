"""SQLite-backed physical workspace storage."""

from __future__ import annotations

import sqlite3
from pathlib import Path


_DATABASE_FILENAME = "workspace.db"


class Storage:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def initialize(cls, path: Path) -> "Storage":
        workspace = _path(path)
        workspace.mkdir()
        database = workspace / _DATABASE_FILENAME
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(database)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("VACUUM")
            _validate_connection(connection)
            return cls(connection)
        except BaseException:
            if connection is not None:
                connection.close()
            try:
                database.unlink()
            except FileNotFoundError:
                pass
            try:
                workspace.rmdir()
            except OSError:
                pass
            raise

    @classmethod
    def open(cls, path: Path) -> "Storage":
        workspace = _path(path)
        if not workspace.exists():
            raise FileNotFoundError(f"storage directory does not exist: {workspace}")
        if not workspace.is_dir():
            raise NotADirectoryError(f"storage path is not a directory: {workspace}")
        database = workspace / _DATABASE_FILENAME
        if not database.is_file():
            raise FileNotFoundError(f"workspace database does not exist: {database}")
        with database.open("rb") as database_file:
            if database_file.read(16) != b"SQLite format 3\x00":
                raise sqlite3.DatabaseError(
                    f"workspace database is not valid SQLite: {database}"
                )
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=rw", uri=True)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            _validate_connection(connection)
        except BaseException:
            connection.close()
            raise
        return cls(connection)

    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        self._connection.close()


def _path(path: Path) -> Path:
    if not isinstance(path, Path):
        raise TypeError("storage path must be a pathlib.Path")
    return path


def _validate_connection(connection: sqlite3.Connection) -> None:
    connection.execute("SELECT name FROM sqlite_schema LIMIT 1").fetchone()
    foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
    if foreign_keys is None or foreign_keys[0] != 1:
        raise sqlite3.DatabaseError("SQLite foreign-key enforcement is unavailable")
