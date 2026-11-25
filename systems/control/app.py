"""Terminal keyboard controls for graph selection."""

from pathlib import Path
import re
import subprocess
import tempfile

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Input, Static

from systems.control import Direction, NodeInfo, TitleSearchResult, open_control
from systems.control.spec.api import ControlAPI
from systems.graph_ui.spec.api import GraphUIAPI
from systems.nodes import Nodes
from systems.node_types import resolve_node_type


class ControlApp(App[None]):
    BINDINGS = [
        Binding("h", "move_left", "Left"),
        Binding("j", "move_down", "Down"),
        Binding("k", "move_up", "Up"),
        Binding("l", "move_right", "Right"),
        Binding("/", "start_select", "Select node"),
        Binding(":", "start_command", "Command"),
        Binding("t", "start_title", "Edit title"),
        Binding("c", "start_connect", "Connect node"),
        Binding("escape", "cancel_select", show=False),
        Binding("up", "search_previous", show=False, priority=True),
        Binding("down", "search_next", show=False, priority=True),
        Binding("a", "create_node", "New node"),
        Binding("o", "create_output", "New output"),
        Binding("i", "create_input", "New input"),
        Binding("space", "toggle_collapse", "Collapse"),
        Binding("enter", "execute_selected", "Execute"),
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", show=False),
    ]

    CSS = """
    #status, #status-separator, #selected-node-info, #search-results,
    #node-command {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    #status {
        color: $text-muted;
        background: $surface;
    }
    #status-separator {
        height: 1;
        color: $text-disabled;
    }
    #status.status-success { color: $success; }
    #status.status-warning { color: $warning; }
    #status.status-error { color: $error; }
    #selected-node-info, #search-results-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    #search-results-scroll { display: none; }
    #node-command { display: none; }
    """

    def __init__(self, control: ControlAPI) -> None:
        super().__init__()
        self._control = control
        self._input_mode: str | None = None
        self._search_results: tuple[TitleSearchResult, ...] = ()
        self._active_search_index: int | None = None
        self._search_query = ""

    def compose(self) -> ComposeResult:
        yield Static(
            "Ready",
            id="status",
            classes="status-neutral",
            markup=False,
        )
        yield Static("─", id="status-separator", markup=False)
        yield Static(
            self._format_selected_node(None, 1),
            id="selected-node-info",
            markup=False,
        )
        with VerticalScroll(id="search-results-scroll", can_focus=False):
            yield Static(id="search-results", markup=False)
        yield Input(placeholder="node ID", id="node-command", disabled=True)

    def on_mount(self) -> None:
        self._refresh_selected_node_info()
        self.set_interval(0.1, self._refresh_selected_node_info)

    def on_resize(self, event: events.Resize) -> None:
        self._refresh_selected_node_info()

    def _refresh_selected_node_info(self) -> None:
        info = self._control.get_selected_info()
        if not isinstance(info, NodeInfo):
            info = None
        separator_width = max(1, self.size.width - 2)
        separator = "─" * separator_width
        for rule in self.query("#status-separator"):
            rule.update(Text(separator, style="dim"))
        content = self._format_selected_node(info, separator_width)
        for panel in self.query("#selected-node-info"):
            panel.update(content)

    @staticmethod
    def _format_selected_node(
        info: NodeInfo | None,
        separator_width: int = 1,
    ) -> Text:
        content = Text()
        content.append("SELECTED NODE", style="bold dim")
        if info is None:
            content.append("\nNo node selected", style="dim")
            return content

        content.append(f"  #{info.node_id}", style="dim")
        properties = info.properties
        title = str(properties["title"])
        node_type = str(properties["type"])
        param = str(properties["param"])
        note = str(properties["note"])
        tags = str(properties["tags"])
        status = str(properties["status"])
        weight = int(properties["weight"])

        content.append("\n")
        content.append(title or "—", style="bold" if title else "dim")
        content.append("\n")
        content.append(node_type, style="cyan")
        content.append("  ")
        status_colors = {
            "none": "grey50",
            "progress": "blue",
            "success": "green",
            "warning": "yellow",
            "failure": "red",
        }
        content.append(
            f"● {status}",
            style=status_colors.get(status, "grey50"),
        )
        content.append(f"  WEIGHT  {weight}", style="dim")

        separator = "─" * max(1, separator_width)
        content.append("\n")
        content.append(separator, style="dim")
        content.append("\nPARAM", style="bold dim")
        content.append("\n")
        content.append(param or "—", style=None if param else "dim")
        content.append("\n")
        content.append(separator, style="dim")
        content.append("\nNOTE", style="bold dim")
        content.append("\n")
        if note:
            lines = note.splitlines(keepends=True)
            preview = "".join(lines[:3])
            content.append(preview)
            if len(lines) > 3:
                if preview and not preview.endswith(("\n", "\r")):
                    content.append("\n")
                content.append("…", style="dim")
        else:
            content.append("—", style="dim")
        content.append("\n")
        content.append(separator, style="dim")
        content.append("\nTAGS", style="bold dim")
        content.append("\n")
        content.append(tags or "—", style=None if tags else "dim")
        return content

    def action_move_left(self) -> None:
        self._show_selection(self._control.move(Direction.LEFT))

    def action_move_down(self) -> None:
        self._show_selection(self._control.move(Direction.DOWN))

    def action_move_up(self) -> None:
        self._show_selection(self._control.move(Direction.UP))

    def action_move_right(self) -> None:
        self._show_selection(self._control.move(Direction.RIGHT))

    def action_start_select(self) -> None:
        self._open_command("select", "node ID or title")
        self._show_search_panel()
        self._update_search("")

    def action_start_command(self) -> None:
        self._open_command(
            "command",
            "type <value> | title [value] | status <value> | note | "
            "tags | weight | param [value] | delete (d) | connect <id> | "
            "disconnect [id] | w<cells> | h<rows> | id",
        )

    def action_start_title(self) -> None:
        info = self._control.get_selected_info()
        title = (
            str(info.properties["title"])
            if info is not None
            else ""
        )
        self._open_command("title", "node title", title)

    def action_start_connect(self) -> None:
        self._open_command("connect", "target node ID")

    def _open_command(
        self,
        mode: str,
        placeholder: str,
        value: str = "",
    ) -> None:
        self._input_mode = mode
        command = self.query_one("#node-command", Input)
        command.disabled = False
        command.styles.display = "block"
        command.placeholder = placeholder
        command.value = value
        command.focus()
        command.cursor_position = len(value)
        self.call_after_refresh(
            setattr,
            command,
            "cursor_position",
            len(value),
        )

    def action_cancel_select(self) -> None:
        self._close_command()

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._input_mode == "select" and event.input.id == "node-command":
            self._update_search(event.value)

    def action_search_previous(self) -> None:
        if self._input_mode is None:
            self._change_weight(1)
            return
        if self._input_mode != "select" or not self._search_results:
            return
        current = self._active_search_index or 0
        self._active_search_index = max(0, current - 1)
        self._render_search_results()

    def action_search_next(self) -> None:
        if self._input_mode is None:
            self._change_weight(-1)
            return
        if self._input_mode != "select" or not self._search_results:
            return
        current = self._active_search_index or 0
        self._active_search_index = min(
            len(self._search_results) - 1,
            current + 1,
        )
        self._render_search_results()

    def _change_weight(self, delta: int) -> None:
        info = self._control.get_selected_info()
        if info is None:
            self._show_status("No existing node is selected")
            return
        current = int(info.properties["weight"])
        if self._control.set_selected_weight(current + delta):
            self._show_status(f"Weight updated: {current + delta}")
            self.refresh(layout=True)
        else:
            self._show_status("No existing node is selected")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        mode = self._input_mode
        match = re.fullmatch(r"/?(\d+)", event.value.strip())
        if mode == "select":
            if match is not None:
                node_id = int(match.group(1))
            elif (
                self._active_search_index is not None
                and self._active_search_index < len(self._search_results)
            ):
                node_id = self._search_results[
                    self._active_search_index
                ].node_id
            else:
                self._show_status("No matching nodes")
                return
            self._close_command()
            if self._control.select_node(node_id):
                self._show_selection(node_id)
            else:
                self._show_status(f"Node {node_id} does not exist")
            return

        self._close_command()
        if mode == "command":
            self._run_command(event.value)
        elif mode == "title":
            if self._control.set_selected_title(event.value):
                self._show_status("Title updated")
            else:
                self._show_status("No existing node is selected")
        elif mode == "tags":
            if self._control.set_selected_tags(event.value):
                self._show_status("Tags updated")
            else:
                self._show_status("No existing node is selected")
        elif mode == "weight":
            if re.fullmatch(r"[+-]?\d+", event.value.strip()) is None:
                self._show_status("Invalid weight")
            elif self._control.set_selected_weight(int(event.value.strip())):
                self._show_status("Weight updated")
                self.refresh(layout=True)
            else:
                self._show_status("No existing node is selected")
        elif mode == "connect":
            target_match = re.fullmatch(r"\d+", event.value.strip())
            if target_match is None:
                self._show_status("Invalid target node ID")
            else:
                target_id = int(target_match.group())
                if self._control.connect(target_id):
                    self._show_status(f"Connected node {target_id}")
                else:
                    self._show_status(f"Cannot connect node {target_id}")

    def _show_search_panel(self) -> None:
        self.query_one("#selected-node-info", Static).styles.display = "none"
        self.query_one("#search-results-scroll").styles.display = "block"

    def _update_search(self, query: str) -> None:
        previous_node_id = None
        if (
            self._active_search_index is not None
            and self._active_search_index < len(self._search_results)
        ):
            previous_node_id = self._search_results[
                self._active_search_index
            ].node_id

        self._search_query = query
        stripped = query.strip()
        if not stripped or re.fullmatch(r"/?\d+", stripped):
            results: tuple[TitleSearchResult, ...] = ()
        else:
            results = self._control.search_titles(query)
        self._search_results = results

        matching_index = next(
            (
                index
                for index, result in enumerate(results)
                if result.node_id == previous_node_id
            ),
            None,
        )
        if matching_index is not None:
            self._active_search_index = matching_index
        elif results:
            previous_index = self._active_search_index
            self._active_search_index = min(
                previous_index if previous_index is not None else 0,
                len(results) - 1,
            )
        else:
            self._active_search_index = None
        self._render_search_results()

    def _render_search_results(self) -> None:
        content = self.query_one("#search-results", Static)
        content.update(
            self._format_search_results(
                self._search_query,
                self._search_results,
                self._active_search_index,
            )
        )
        if self._active_search_index is not None:
            self.call_after_refresh(
                self._scroll_to_active_search_result,
            )

    def _scroll_to_active_search_result(self) -> None:
        active_index = self._active_search_index
        if active_index is None:
            return
        content_widget = self.query_one("#search-results", Static)
        prefix = self._format_search_header(
            self._search_query,
            len(self._search_results),
        )
        for result in self._search_results[:active_index]:
            self._append_search_result(prefix, result, active=False)
        width = max(1, content_widget.content_size.width)
        active_y = max(0, len(prefix.wrap(self.console, width)) - 1)
        self.query_one("#search-results-scroll", VerticalScroll).scroll_to(
            y=active_y,
            animate=False,
            force=True,
        )

    @staticmethod
    def _format_search_results(
        query: str,
        results: tuple[TitleSearchResult, ...],
        active_index: int | None,
    ) -> Text:
        content = ControlApp._format_search_header(query, len(results))
        stripped = query.strip()
        numeric = re.fullmatch(r"/?(\d+)", stripped)
        if not stripped:
            content.append("\nType a node title or numeric ID", style="dim")
            return content
        if numeric is not None:
            content.append("\nPress Enter to select node ", style="dim")
            content.append(f"#{numeric.group(1)}", style="bold")
            return content

        if not results:
            content.append("\nNo matching node titles", style="yellow")
            return content

        for index, result in enumerate(results):
            ControlApp._append_search_result(
                content,
                result,
                active=index == active_index,
            )
        return content

    @staticmethod
    def _format_search_header(query: str, count: int) -> Text:
        content = Text()
        content.append(f"SEARCH  /{query}", style="bold")
        if query.strip() and re.fullmatch(r"/?\d+", query.strip()) is None:
            content.append(
                f"  {count} match{'es' if count != 1 else ''}",
                style="dim",
            )
        return content

    @staticmethod
    def _append_search_result(
        content: Text,
        result: TitleSearchResult,
        *,
        active: bool,
    ) -> None:
        status_colors = {
            "none": "grey50",
            "progress": "blue",
            "success": "green",
            "warning": "yellow",
            "failure": "red",
        }
        style = "reverse" if active else None
        content.append("\n")
        content.append("› " if active else "  ", style=style)
        content.append(
            result.title,
            style=f"bold {style}" if style else "bold",
        )
        content.append(f"  #{result.node_id}  {result.type}  ", style=style)
        status_style = status_colors.get(result.status, "grey50")
        if active:
            status_style += " reverse"
        content.append(f"● {result.status}", style=status_style)

    def _run_command(self, value: str) -> None:
        if value == "note":
            self._edit_selected_note()
            return

        if value == "tags":
            info = self._control.get_selected_info()
            if info is None:
                self._show_status("No existing node is selected")
                return
            tags = str(info.properties["tags"])
            self._open_command("tags", "comma-separated tags", tags)
            return

        if value == "weight":
            info = self._control.get_selected_info()
            if info is None:
                self._show_status("No existing node is selected")
                return
            weight = int(info.properties["weight"])
            self._open_command("weight", "integer weight", str(weight))
            return

        status_match = re.fullmatch(r"status(?: (.*))?", value)
        if status_match is not None:
            status = status_match.group(1)
            if status not in {
                "none",
                "progress",
                "success",
                "warning",
                "failure",
            }:
                self._show_status("Invalid status")
            elif self._control.set_selected_status(status):
                self._show_status("Status updated")
            else:
                self._show_status("No existing node is selected")
            return

        type_match = re.fullmatch(r"type(?: (.*))?", value)
        if type_match is not None:
            assignment_type = type_match.group(1) or ""
            if not assignment_type:
                self._show_status("Type must be non-empty")
            elif self._control.set_selected_type(assignment_type):
                self._show_status("Type updated")
            else:
                self._show_status("No existing node is selected")
            return

        param_match = re.fullmatch(r"param(?: (.*))?", value)
        if param_match is not None:
            if value == "param":
                self._edit_selected_text("param")
                return
            param = param_match.group(1) or ""
            if self._control.set_selected_param(param):
                self._show_status("Parameter updated")
            else:
                self._show_status("No existing node is selected")
            return

        title_match = re.fullmatch(r"title(?: (.*))?", value)
        if title_match is not None:
            title = title_match.group(1) or ""
            if self._control.set_selected_title(title):
                self._show_status("Title updated")
            else:
                self._show_status("No existing node is selected")
            return

        value = value.strip()
        if value == "id":
            visible = self._control.toggle_node_ids()
            self._show_status(f"Node IDs: {'shown' if visible else 'hidden'}")
            return

        if value in {"delete", "d"}:
            deleted = self._control.delete_selected()
            if deleted is None:
                self._show_status("No existing node is selected")
            else:
                self._show_status(f"Deleted node {deleted}")
            return

        if value == "disconnect":
            removed = self._control.disconnect_all()
            if removed is None:
                self._show_status("No existing node is selected")
            else:
                self._show_status(f"Disconnected {removed} edge(s)")
            return

        height_match = re.fullmatch(r"h(\d+)", value)
        if height_match is not None:
            height = int(height_match.group(1))
            if self._control.set_node_height(height):
                self._show_status(f"Node height: {height}")
            else:
                self._show_status("Node height must be at least 1")
            return

        width_match = re.fullmatch(r"w(\d+)", value)
        if width_match is not None:
            width = int(width_match.group(1))
            if self._control.set_node_width(width):
                self._show_status(f"Node width: {width}")
            else:
                self._show_status("Node width must be at least 3")
            return

        match = re.fullmatch(r"(connect|disconnect)\s+(\d+)", value)
        if match is None:
            self._show_status("Invalid command")
            return

        operation, raw_node_id = match.groups()
        node_id = int(raw_node_id)
        succeeded = (
            self._control.connect(node_id)
            if operation == "connect"
            else self._control.disconnect(node_id)
        )
        if succeeded:
            self._show_status(f"{operation.title()}ed node {node_id}")
        else:
            self._show_status(f"Cannot {operation} node {node_id}")

    def _edit_selected_note(self) -> None:
        self._edit_selected_text("note")

    def _edit_selected_text(self, field: str) -> None:
        info = self._control.get_selected_info()
        if info is None:
            self._show_status("No existing node is selected")
            return

        original_text = (
            str(info.properties[field])
        )
        label = "Note" if field == "note" else "Parameter"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f"graph-manager-{field}-",
                suffix=".txt",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(original_text.encode("utf-8"))

            try:
                with self.suspend():
                    result = subprocess.run(
                        ["vim", str(temporary_path)],
                        check=False,
                    )
            except Exception as error:
                self._show_status(f"Could not open Vim: {error}")
                return

            if result.returncode != 0:
                self._show_status(
                    f"Vim exited with status {result.returncode}"
                )
                return

            try:
                edited_text = temporary_path.read_bytes().decode("utf-8")
            except (OSError, UnicodeError) as error:
                self._show_status(f"Could not read edited {field}: {error}")
                return

            if edited_text == original_text:
                self._show_status(f"{label} unchanged")
            elif getattr(self._control, f"set_selected_{field}")(edited_text):
                self._show_status(f"{label} updated")
            else:
                self._show_status("No existing node is selected")
        except OSError as error:
            self._show_status(f"Could not edit {field}: {error}")
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self.refresh(layout=True)
            self._refresh_selected_node_info()

    def action_create_output(self) -> None:
        self._show_selection(self._control.create_output())

    def action_create_input(self) -> None:
        self._show_selection(self._control.create_input())

    def action_create_node(self) -> None:
        self._show_selection(self._control.create_node())

    def action_execute_selected(self) -> None:
        if self._input_mode is not None:
            return
        try:
            executed = self._control.execute_selected()
        except Exception as error:
            self._show_status(f"Execution failed: {error}")
            return
        if executed:
            self._show_status("Executed selected node")
        else:
            self._show_status("No existing node is selected")

    def action_toggle_collapse(self) -> None:
        if self._input_mode is not None:
            return
        collapsed = self._control.toggle_selected_collapse()
        if collapsed is not None:
            self._show_status("Node collapsed" if collapsed else "Node expanded")

    def _show_selection(self, selected: int | None) -> None:
        self._show_status(f"Selected: {selected}")

    def _show_status(self, status: str) -> None:
        status_widget = self.query_one("#status", Static)
        status_widget.update(status)
        status_widget.remove_class(
            "status-neutral",
            "status-success",
            "status-warning",
            "status-error",
        )
        error_prefixes = (
            "Cannot ",
            "Could not ",
            "Execution failed",
            "Invalid ",
            "Node height must",
            "Node width must",
            "Type must",
            "Vim exited",
        )
        warning_prefixes = (
            "No existing node",
            "Note unchanged",
        )
        if status.startswith(error_prefixes):
            status_widget.add_class("status-error")
        elif status.startswith(warning_prefixes):
            status_widget.add_class("status-warning")
        else:
            status_widget.add_class("status-success")
        self._refresh_selected_node_info()

    def _close_command(self) -> None:
        self._input_mode = None
        command = self.query_one("#node-command", Input)
        command.value = ""
        command.styles.display = "none"
        command.disabled = True
        self._search_results = ()
        self._active_search_index = None
        self._search_query = ""
        self.query_one("#search-results-scroll").styles.display = "none"
        self.query_one("#selected-node-info", Static).styles.display = "block"
        self.screen.set_focus(None)


def main(nodes: Nodes, graph_ui: GraphUIAPI) -> None:
    control = open_control(nodes, graph_ui, resolve_node_type)
    ControlApp(control).run()
