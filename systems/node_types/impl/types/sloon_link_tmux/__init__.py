"""Open or reuse a Sloon workspace in the sloon-app tmux session."""

import hashlib
import os
from pathlib import Path
import shlex
import subprocess

from systems.node_types.spec.api import NodeContext, NodeRender

SESSION = "sloon-app"
SLOON_COMMAND = (str(Path(__file__).resolve().parents[5] / "sloon"),)


def _tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", *args], check=check, capture_output=True, text=True
    )


def _windows() -> dict[str, str]:
    result = _tmux("list-windows", "-t", f"={SESSION}",
                   "-F", "#{window_id}\t#{window_name}")
    return {name: window_id for window_id, name in
            (line.split("\t", 1) for line in result.stdout.splitlines())}


def _panes(window_id: str) -> list[tuple[str, bool]]:
    result = _tmux("list-panes", "-t", window_id,
                   "-F", "#{pane_id}\t#{pane_dead}\t#{pane_left}")
    rows = [line.split("\t") for line in result.stdout.splitlines()]
    return [(pane, dead == "1") for pane, dead, _ in
            sorted(rows, key=lambda row: int(row[2]))]


class SloonLinkTmux:
    type = "sloon-link-tmux"

    def render(self, context: NodeContext) -> NodeRender:
        return NodeRender(title=context.properties.get("title", ""),
                          border_style="dashed")

    def execute(self, context: NodeContext) -> None:
        if not os.environ.get("TMUX"):
            raise RuntimeError("sloon-link-tmux requires a tmux client")

        raw = context.properties.get("param", "")
        if not raw.strip():
            raise ValueError("param must contain a .sloon path")
        path = Path(raw.strip()).expanduser()
        if not path.is_absolute() or path.suffix != ".sloon":
            raise ValueError("param must be an absolute .sloon path")
        path = path.resolve(strict=True)
        name = hashlib.sha256(os.fsencode(path)).hexdigest()
        visualize = shlex.join([*SLOON_COMMAND, "--workspace", str(path), "visualize"])
        control = shlex.join([*SLOON_COMMAND, "--workspace", str(path), "control"])

        exists = _tmux("has-session", "-t", f"={SESSION}", check=False)
        window_id = _windows().get(name) if exists.returncode == 0 else None
        if window_id is not None:
            _tmux("switch-client", "-t", f"{SESSION}:{window_id}")
            return

        if exists.returncode == 0:
            args = ["new-window", "-t", f"{SESSION}:"]
        else:
            args = ["new-session", "-s", SESSION]
        window_id = _tmux(*args, "-d", "-P", "-F", "#{window_id}",
                          "-n", name, "sleep 86400").stdout.strip()
        try:
            _tmux("set-option", "-w", "-t", window_id,
                  "automatic-rename", "off")
            left = _panes(window_id)[0][0]
            right = _tmux("split-window", "-h", "-d", "-l", "35%",
                          "-t", left, "-P", "-F", "#{pane_id}",
                          "sleep 86400").stdout.strip()
            for pane, command in ((left, visualize), (right, control)):
                _tmux("set-option", "-p", "-t", pane,
                      "remain-on-exit", "on")
                _tmux("respawn-pane", "-k", "-t", pane, command)
        except Exception:
            _tmux("kill-window", "-t", window_id, check=False)
            raise
        _tmux("select-pane", "-t", right)
        _tmux("switch-client", "-t", f"{SESSION}:{window_id}")


node_type = SloonLinkTmux()
