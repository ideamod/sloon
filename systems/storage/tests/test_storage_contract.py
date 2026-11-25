import sqlite3
from pathlib import Path

import pytest

from systems.storage import Storage


def test_initialize_creates_directory_and_empty_valid_database(tmp_path: Path) -> None:
    workspace = tmp_path / "custom-name"
    storage = Storage.initialize(workspace)
    try:
        assert workspace.is_dir()
        assert (workspace / "workspace.db").is_file()
        assert storage.connection().execute(
            "SELECT name FROM sqlite_schema WHERE type='table'"
        ).fetchall() == []
    finally:
        storage.close()


def test_initialize_rejects_every_existing_path_without_changes(tmp_path: Path) -> None:
    directory = tmp_path / "existing"
    directory.mkdir()
    marker = directory / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        Storage.initialize(directory)
    assert marker.read_text(encoding="utf-8") == "keep"

    file_path = tmp_path / "existing-file"
    file_path.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        Storage.initialize(file_path)
    assert file_path.read_text(encoding="utf-8") == "keep"


def test_open_requires_directory_database_and_valid_sqlite(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        Storage.open(missing)
    assert not missing.exists()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(FileNotFoundError):
        Storage.open(workspace)
    assert list(workspace.iterdir()) == []

    database = workspace / "workspace.db"
    database.touch()
    with pytest.raises(sqlite3.DatabaseError):
        Storage.open(workspace)
    database.write_bytes(b"not sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        Storage.open(workspace)


def test_open_preserves_additional_files_and_directories(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    storage = Storage.initialize(workspace)
    storage.close()
    attachment = workspace / "attachments" / "note.txt"
    attachment.parent.mkdir()
    attachment.write_text("preserve me", encoding="utf-8")

    reopened = Storage.open(workspace)
    reopened.close()

    assert attachment.read_text(encoding="utf-8") == "preserve me"


def test_connection_identity_foreign_keys_and_lifecycle(tmp_path: Path) -> None:
    storage = Storage.initialize(tmp_path / "workspace")
    connection = storage.connection()
    assert storage.connection() is connection
    assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    storage.close()
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_path_is_independent_of_current_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    workspace = parent / "workspace"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    storage = Storage.initialize(workspace)
    storage.close()

    assert (workspace / "workspace.db").is_file()
    assert not (elsewhere / "workspace").exists()
