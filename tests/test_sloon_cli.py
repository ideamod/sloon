import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap

import pytest

import sloon
from systems.graph_ui import open_graph_ui
from systems.nodes import Nodes
from systems.storage import Storage


ROOT = Path(__file__).resolve().parent.parent


def run_cli(cwd: Path, *arguments: str, input=None):
    return subprocess.run(
        [sys.executable, str(ROOT / "sloon.py"), *arguments],
        cwd=cwd,
        text=True,
        capture_output=True,
        input=input,
    )


def test_repository_launcher_uses_project_environment_from_other_directory(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "sloon"
    launcher.symlink_to(ROOT / "sloon")
    result = subprocess.run(
        [str(launcher), "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0
    assert "sloon" in result.stdout
    assert "--workspace" in result.stdout
    assert "WORKSPACE.sloon" in result.stdout


def test_init_creates_named_ready_workspaces_with_optional_suffix(
    tmp_path: Path,
) -> None:
    initialized = run_cli(tmp_path, "init", "home")
    assert initialized.returncode == 0
    assert json.loads(initialized.stdout) == {
        "initialized": str(tmp_path / "home.sloon")
    }
    assert run_cli(tmp_path, "init", "work.sloon").returncode == 0
    database = tmp_path / "home.sloon" / "workspace.db"
    assert database.is_file()
    assert (tmp_path / "work.sloon" / "workspace.db").is_file()
    connection = sqlite3.connect(database)
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table'"
        )
    }
    connection.close()
    assert {
        "graph_nodes", "graph_edges", "node_properties",
        "graph_ui_params", "graph_ui_collapsed_nodes",
    } <= tables
    assert "nodes_schema" not in tables


def test_init_requires_valid_nonhidden_name_and_never_overwrites(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "home.sloon"
    workspace.mkdir()
    marker = workspace / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    result = run_cli(tmp_path, "init", "home")
    assert result.returncode == 2
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (workspace / "workspace.db").exists()

    existing_file = tmp_path / "books.sloon"
    existing_file.write_text("keep", encoding="utf-8")
    assert run_cli(tmp_path, "init", "books").returncode == 2
    assert existing_file.read_text(encoding="utf-8") == "keep"

    assert run_cli(tmp_path, "init").returncode == 2
    for name in ("", ".home", ".home.sloon", ".sloon", "nested/home"):
        rejected = run_cli(tmp_path, "init", name)
        assert rejected.returncode == 2
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "books.sloon",
        "home.sloon",
    ]


def test_commands_require_workspace_and_never_initialize_it(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "node", "list")
    assert result.returncode == 2
    assert "no workspace selected" in json.loads(result.stderr)["error"]
    assert list(tmp_path.iterdir()) == []

    missing = run_cli(
        tmp_path, "--workspace", "missing.sloon", "node", "list"
    )
    assert missing.returncode == 2
    assert "storage directory does not exist" in json.loads(missing.stderr)["error"]
    assert list(tmp_path.iterdir()) == []


def test_commands_report_invalid_workspace_database_as_json(tmp_path: Path) -> None:
    workspace = tmp_path / "invalid.sloon"
    workspace.mkdir()
    (workspace / "workspace.db").write_text("invalid", encoding="utf-8")
    result = run_cli(tmp_path, "--workspace", "invalid.sloon", "node", "list")
    assert result.returncode == 2
    assert "not valid SQLite" in json.loads(result.stderr)["error"]


def test_commands_do_not_search_parent_directories(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init", "home").returncode == 0
    child = tmp_path / "home.sloon" / "child"
    child.mkdir()
    result = run_cli(child, "node", "list")
    assert result.returncode == 2
    assert "no workspace selected" in json.loads(result.stderr)["error"]
    assert list(child.iterdir()) == []


def test_commands_do_not_scan_or_use_hidden_workspace_convention(
    tmp_path: Path,
) -> None:
    assert run_cli(tmp_path, "init", "only").returncode == 0
    (tmp_path / ".sloon").mkdir()

    unselected = run_cli(tmp_path, "node", "list")
    assert unselected.returncode == 2
    assert "no workspace selected" in json.loads(unselected.stderr)["error"]

    hidden = run_cli(tmp_path, "--workspace", ".sloon", "node", "list")
    assert hidden.returncode == 2
    assert "non-hidden .sloon" in json.loads(hidden.stderr)["error"]


def test_multiple_workspaces_are_independent_and_accept_relative_or_absolute_paths(
    tmp_path: Path,
) -> None:
    assert run_cli(tmp_path, "init", "home").returncode == 0
    assert run_cli(tmp_path, "init", "work").returncode == 0

    home_create = run_cli(
        tmp_path, "--workspace", "home.sloon", "node", "create", "--title", "Home"
    )
    work_create = run_cli(
        tmp_path,
        "--workspace",
        str(tmp_path / "work.sloon"),
        "node",
        "create",
        "--title",
        "Work",
    )
    assert json.loads(home_create.stdout) == {"node_id": 1}
    assert json.loads(work_create.stdout) == {"node_id": 1}
    assert json.loads(run_cli(
        tmp_path, "--workspace", "home.sloon", "node", "get", "1", "title"
    ).stdout) == "Home"
    assert json.loads(run_cli(
        tmp_path,
        "--workspace",
        str(tmp_path / "work.sloon"),
        "node",
        "get",
        "1",
        "title",
    ).stdout) == "Work"


def test_commands_work_inside_workspace_and_explicit_selection_takes_precedence(
    tmp_path: Path,
) -> None:
    assert run_cli(tmp_path, "init", "home").returncode == 0
    assert run_cli(tmp_path, "init", "work").returncode == 0
    home = tmp_path / "home.sloon"

    assert run_cli(home, "node", "create", "--title", "Home").returncode == 0
    selected = run_cli(
        home,
        "--workspace",
        "../work.sloon",
        "node",
        "create",
        "--title",
        "Work",
    )
    assert selected.returncode == 0
    assert json.loads(run_cli(home, "node", "get", "1", "title").stdout) == "Home"
    assert json.loads(run_cli(
        tmp_path, "--workspace", "work.sloon", "node", "get", "1", "title"
    ).stdout) == "Work"


def test_graph_retrieves_empty_and_complete_graph_with_exact_properties(
    tmp_path: Path,
) -> None:
    assert run_cli(tmp_path, "init", "home").returncode == 0
    selected = ("--workspace", "home.sloon")
    assert json.loads(run_cli(tmp_path, *selected, "graph").stdout) == {
        "nodes": [], "edges": []
    }
    operations = [
        {"op": "create_node", "fields": {"z": "last", "empty": "", "note": "one\ntwo"}},
        {"op": "create_node", "fields": {}},
        {"op": "create_node", "fields": {"title": "isolated"}},
        {"op": "create_node", "fields": {"component": "other"}},
        {"op": "connect", "source": 1, "target": 2},
        {"op": "connect", "source": 4, "target": 4},
    ]
    assert run_cli(tmp_path, *selected, "batch", json.dumps(operations)).returncode == 0

    expected = {
        "nodes": [
            {"id": 1, "properties": {"empty": "", "note": "one\ntwo", "z": "last"}},
            {"id": 2, "properties": {}},
            {"id": 3, "properties": {"title": "isolated"}},
            {"id": 4, "properties": {"component": "other"}},
        ],
        "edges": [[1, 2], [4, 4]],
    }
    assert json.loads(run_cli(tmp_path, *selected, "graph").stdout) == expected
    assert json.loads(run_cli(tmp_path / "home.sloon", "graph").stdout) == expected


def test_graph_rooted_traversal_is_induced_deterministic_and_ignores_ui_state(
    tmp_path: Path,
) -> None:
    assert run_cli(tmp_path, "init", "home").returncode == 0
    selected = ("--workspace", "home.sloon")
    operations = [
        *({"op": "create_node", "fields": {"label": str(node_id)}} for node_id in range(1, 8)),
        {"op": "connect", "source": 1, "target": 2},
        {"op": "connect", "source": 1, "target": 3},
        {"op": "connect", "source": 2, "target": 4},
        {"op": "connect", "source": 3, "target": 4},
        {"op": "connect", "source": 4, "target": 2},
        {"op": "connect", "source": 4, "target": 4},
        {"op": "connect", "source": 5, "target": 1},
        {"op": "connect", "source": 5, "target": 6},
        {"op": "connect", "source": 3, "target": 2},
    ]
    assert run_cli(tmp_path, *selected, "batch", json.dumps(operations)).returncode == 0
    storage = Storage.open(tmp_path / "home.sloon")
    try:
        graph_ui = open_graph_ui(storage.connection())
        graph_ui.set_node_collapsed(1, True)
        graph_ui.select_node(7)
    finally:
        storage.close()

    result = json.loads(run_cli(tmp_path, *selected, "graph", "1").stdout)
    assert result == {
        "nodes": [
            {"id": 1, "properties": {"label": "1"}},
            {"id": 2, "properties": {"label": "2"}},
            {"id": 3, "properties": {"label": "3"}},
            {"id": 4, "properties": {"label": "4"}},
        ],
        "edges": [[1, 2], [1, 3], [2, 4], [3, 2], [3, 4], [4, 2], [4, 4]],
    }
    assert json.loads(run_cli(tmp_path, *selected, "graph", "7").stdout) == {
        "nodes": [{"id": 7, "properties": {"label": "7"}}], "edges": []
    }


def test_graph_rejects_a_missing_root_with_standard_json_error(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init", "home").returncode == 0
    result = run_cli(tmp_path, "--workspace", "home.sloon", "graph", "99")
    assert result.returncode == 2
    assert json.loads(result.stderr) == {"error": "node does not exist: 99"}


def test_graph_reads_one_consistent_database_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "snapshot.db"
    reader_connection = sqlite3.connect(database)
    reader_connection.execute("PRAGMA foreign_keys = ON")
    reader_connection.execute("PRAGMA journal_mode = WAL")
    reader = Nodes(reader_connection)
    reader.create_node(title="before")
    writer_connection = sqlite3.connect(database)
    writer_connection.execute("PRAGMA foreign_keys = ON")
    writer = Nodes(writer_connection)

    class ConcurrentWriteAfterFirstRead:
        def transaction(self):
            return reader.transaction()

        def list_nodes(self):
            result = reader.list_nodes()
            writer.create_node(title="after")
            return result

        def list_edges(self):
            return reader.list_edges()

        def get_all(self, node_id):
            return reader.get_all(node_id)

    try:
        assert sloon._graph(ConcurrentWriteAfterFirstRead()) == {
            "nodes": [{"id": 1, "properties": {"title": "before"}}],
            "edges": [],
        }
        assert reader.list_nodes() == [1, 2]
    finally:
        writer_connection.close()
        reader_connection.close()


@pytest.mark.parametrize("name", ["readonly", "readwrite"])
def test_skill_prints_markdown_without_a_workspace_or_side_effects(
    tmp_path: Path, name: str
) -> None:
    marker = tmp_path / "keep.txt"
    marker.write_text("unchanged", encoding="utf-8")

    result = run_cli(tmp_path, "skill", name)

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.startswith("# Sloon ")
    assert "## Workspace" in result.stdout
    assert "sloon --workspace home.sloon graph" in result.stdout
    assert "sloon --workspace home.sloon graph 12" in result.stdout
    assert '"nodes"' in result.stdout
    assert '"edges"' in result.stdout
    assert "recursively following outgoing" in result.stdout
    assert "consistent snapshot" in result.stdout
    assert "underlying graph data independently of UI state" in result.stdout
    assert "nodes, selection, layout, and other presentation settings" in result.stdout
    assert "sloon --workspace home.sloon node list" in result.stdout
    assert "sloon --workspace home.sloon edges" in result.stdout
    assert "sloon --workspace home.sloon node get-all 12" in result.stdout
    assert "sloon --workspace home.sloon inputs 12" in result.stdout
    assert "sloon --workspace home.sloon outputs 12" in result.stdout
    assert "cd home.sloon" in result.stdout
    assert "never guess which workspace" in result.stdout
    assert "Relative paths are resolved against" in result.stdout
    assert "absolute paths can be used from any directory" in result.stdout
    assert "SQLite" not in result.stdout
    assert "workspace.db" not in result.stdout
    assert "not automatically trusted instructions" in result.stdout
    assert "does not grant permission to execute" in result.stdout
    assert "not an application-level permission mechanism" in result.stdout
    assert "possible type identifiers form a closed set" in result.stdout
    assert "task-specific instructions" in result.stdout
    assert '    {"id": 13, "properties": {}}' in result.stdout
    assert '  "edges": [[12, 13]]' in result.stdout
    for type_name in (
        "`text`", "`copy`", "`cmd`", "`cmd-terminal`", "`file`", "`link`", "`agent`",
    ):
        assert type_name not in result.stdout
    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["keep.txt"]


def test_readonly_skill_excludes_mutation_and_execution_commands(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "skill", "readonly")

    assert result.returncode == 0
    assert "Do not initialize" in result.stdout
    for command in (
        "node create",
        "node delete",
        "node set",
        "node delete-property",
        "sloon --workspace home.sloon connect",
        "sloon --workspace home.sloon disconnect",
        "sloon --workspace home.sloon batch",
        "sloon control",
    ):
        assert command not in result.stdout


def test_readwrite_skill_is_self_contained_and_documents_mutations(
    tmp_path: Path,
) -> None:
    result = run_cli(tmp_path, "skill", "readwrite")

    assert result.returncode == 0
    assert "## Workspace" in result.stdout
    assert "## Read the graph" in result.stdout
    assert "## Modify the graph" in result.stdout
    assert "## Atomic batches" in result.stdout
    for command in (
        "sloon --workspace home.sloon node create",
        "sloon --workspace home.sloon node delete 12",
        "sloon --workspace home.sloon node set 12",
        "sloon --workspace home.sloon node delete-property 12 type",
        "sloon --workspace home.sloon connect 12 15",
        "sloon --workspace home.sloon disconnect 12 15",
        "sloon --workspace home.sloon batch",
    ):
        assert command in result.stdout
    assert "Make only changes required" in result.stdout
    assert "never guess which workspace" in result.stdout
    assert "$'first line\\nsecond line'" in result.stdout
    assert '"value":""' in result.stdout


def test_skill_selection_lists_options_and_rejects_unknown_names(
    tmp_path: Path,
) -> None:
    listed = run_cli(tmp_path, "skill")
    assert listed.returncode == 0
    assert "# Available sloon skills" in listed.stdout
    assert "`readonly`" in listed.stdout
    assert "`readwrite`" in listed.stdout
    assert list(tmp_path.iterdir()) == []

    unknown = run_cli(tmp_path, "skill", "untrusted")
    assert unknown.returncode == 2
    assert json.loads(unknown.stderr) == {
        "error": "unknown skill 'untrusted'; available skills: readonly, readwrite"
    }
    assert list(tmp_path.iterdir()) == []


def test_cli_help_documents_graph_forms(tmp_path: Path) -> None:
    top_level = run_cli(tmp_path, "--help")
    assert top_level.returncode == 0
    assert "retrieve the full graph" in top_level.stdout
    assert "outgoing-reachable" in top_level.stdout
    graph = run_cli(tmp_path, "graph", "--help")
    assert graph.returncode == 0
    assert "[node_id]" in graph.stdout


def test_commands_documented_by_readwrite_skill_are_executable(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init", "home").returncode == 0
    selected = ("--workspace", "home.sloon")

    created = run_cli(
        tmp_path, *selected, "node", "create", "--title", "Idea", "--type", "text"
    )
    assert json.loads(created.stdout) == {"node_id": 1}
    second = run_cli(
        tmp_path,
        *selected,
        "node",
        "create",
        "--property",
        'metadata={"source":"agent"}',
    )
    assert json.loads(second.stdout) == {"node_id": 2}
    assert json.loads(run_cli(tmp_path, *selected, "node", "list").stdout) == [1, 2]
    assert json.loads(run_cli(
        tmp_path, *selected, "node", "get-all", "1"
    ).stdout) == {
        "title": "Idea",
        "type": "text",
    }

    assert run_cli(
        tmp_path, *selected, "node", "set", "1", "title", ""
    ).returncode == 0
    multiline = "first line\nsecond line"
    assert run_cli(
        tmp_path, *selected, "node", "set", "1", "note", multiline
    ).returncode == 0
    assert run_cli(tmp_path, *selected, "connect", "1", "2").returncode == 0
    assert json.loads(run_cli(tmp_path, *selected, "inputs", "2").stdout) == [1]
    assert json.loads(run_cli(tmp_path, *selected, "outputs", "1").stdout) == [2]

    batch = json.dumps([
        {"op": "set", "node_id": 1, "key": "empty", "value": ""},
        {"op": "disconnect", "source": 1, "target": 2},
    ])
    assert json.loads(run_cli(tmp_path, *selected, "batch", input=batch).stdout) == [None, None]
    assert run_cli(
        tmp_path, *selected, "node", "delete-property", "1", "type"
    ).returncode == 0
    assert run_cli(tmp_path, *selected, "node", "delete", "2").returncode == 0
    assert json.loads(run_cli(tmp_path, *selected, "edges").stdout) == []


def test_cli_json_crud_and_atomic_batch(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init", "home").returncode == 0
    selected = ("--workspace", "home.sloon")
    created = run_cli(
        tmp_path, *selected, "node", "create", "--title", "Idea", "--weight", "-3"
    )
    assert json.loads(created.stdout) == {"node_id": 1}
    batch = json.dumps([
        {"op": "create_node", "fields": {"title": "Output", "custom": "null"}},
        {"op": "connect", "source": 1, "target": 2},
    ])
    result = run_cli(tmp_path, *selected, "batch", batch)
    assert result.returncode == 0
    assert json.loads(result.stdout) == [2, None]
    assert json.loads(run_cli(tmp_path, *selected, "edges").stdout) == [[1, 2]]
    assert json.loads(run_cli(
        tmp_path, *selected, "node", "get", "1", "title"
    ).stdout) == "Idea"
    assert json.loads(run_cli(
        tmp_path, *selected, "node", "get", "1", "weight"
    ).stdout) == "-3"

    literal = run_cli(
        tmp_path, *selected, "node", "set", "1", "metadata", '{"source":"agent"}'
    )
    assert literal.returncode == 0
    assert json.loads(run_cli(
        tmp_path, *selected, "node", "get", "1", "metadata"
    ).stdout) == '{"source":"agent"}'

    failed = run_cli(tmp_path, *selected, "batch", json.dumps([
        {"op": "create_node", "fields": {"title": "rollback"}},
        {"op": "set", "node_id": 1, "key": "weight", "value": True},
    ]))
    assert failed.returncode == 2
    assert json.loads(run_cli(tmp_path, *selected, "node", "list").stdout) == [1, 2]


def test_removed_database_selection_option_is_rejected(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "--db", "anything", "node", "list").returncode != 0


def test_storage_closes_after_success_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert sloon.main(["init", "home"]) == 0
    real_open = Storage.open

    successful = real_open(tmp_path / "home.sloon")

    class SuccessfulStorage:
        open = staticmethod(lambda _path: successful)

    monkeypatch.setattr(sloon, "Storage", SuccessfulStorage)
    assert sloon.main(["--workspace", "home.sloon", "node", "list"]) == 0
    with pytest.raises(sqlite3.ProgrammingError):
        successful.connection().execute("SELECT 1")

    failing = real_open(tmp_path / "home.sloon")

    class FailingStorage:
        open = staticmethod(lambda _path: failing)

    monkeypatch.setattr(sloon, "Storage", FailingStorage)
    assert sloon.main([
        "--workspace", "home.sloon", "node", "get", "999", "title"
    ]) == 2
    with pytest.raises(sqlite3.ProgrammingError):
        failing.connection().execute("SELECT 1")


def test_interactive_control_opens_by_path_or_from_inside_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert sloon.main(["init", "home"]) == 0
    workspace = tmp_path / "home.sloon"
    calls: list[list[int]] = []

    import systems.control.app as application

    def fake_main(nodes, _graph_ui, workspace_path):
        assert workspace_path == workspace.resolve()
        calls.append(nodes.list_nodes())

    monkeypatch.setattr(application, "main", fake_main)
    assert sloon.main(["home.sloon"]) == 0
    assert sloon.main([str(workspace)]) == 0
    assert sloon.main(["--workspace", "home.sloon"]) == 0

    monkeypatch.chdir(workspace)
    assert sloon.main([]) == 0
    assert calls == [[], [], [], []]


@pytest.mark.parametrize("command", ["control", "visualize"])
def test_application_entry_points_receive_composed_consumers_and_close_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert sloon.main(["init", "home"]) == 0
    captured = {}

    if command == "control":
        import systems.control.app as application
    else:
        import systems.visualization.app as application

    def fake_main(nodes, graph_ui, workspace_path):
        assert workspace_path == (tmp_path / "home.sloon").resolve()
        captured["nodes"] = nodes
        captured["graph_ui"] = graph_ui
        assert nodes.list_nodes() == []
        assert graph_ui.get_selected_node() is None

    monkeypatch.setattr(application, "main", fake_main)
    assert sloon.main(["--workspace", "home.sloon", command]) == 0
    with pytest.raises(sqlite3.ProgrammingError):
        captured["nodes"].list_nodes()


def test_interactive_apps_render_and_execute_external_node_in_selected_workspace(
    tmp_path: Path,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from systems.control.app import ControlApp
    from systems.visualization.impl.visualization import _VisualizationApp

    package = isolated_home / ".sloon" / "types" / "cli_context_probe"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(textwrap.dedent("""
        from systems.node_types import NodeRender

        class ContextProbe:
            type = "context-probe"

            def render(self, context):
                return NodeRender(title=f"{context.node_id} {context.workspace_path}")

            def execute(self, context):
                context.nodes.set(context.node_id, "seen_workspace", str(context.workspace_path))

        node_type = ContextProbe()
    """), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    workspace_name = "selected.sloon"
    workspace_path = (tmp_path / workspace_name).resolve()
    selected = ["--workspace", workspace_name]
    assert sloon.main(["init", "selected"]) == 0
    assert sloon.main([*selected, "node", "create", "--type", "context-probe"]) == 0

    rendered = []

    def capture_render(app):
        rendered.append(app._initial_snapshot.titles[1])

    def execute_selected(app):
        assert app._control.select_node(1)
        assert app._control.execute_selected()

    monkeypatch.setattr(_VisualizationApp, "run", capture_render)
    monkeypatch.setattr(ControlApp, "run", execute_selected)
    assert sloon.main([*selected, "visualize"]) == 0
    assert sloon.main([*selected, "control"]) == 0

    assert rendered == [f"1 {workspace_path}"]
    storage = Storage.open(workspace_path)
    try:
        assert Nodes(storage.connection()).get(1, "seen_workspace") == str(workspace_path)
    finally:
        storage.close()
