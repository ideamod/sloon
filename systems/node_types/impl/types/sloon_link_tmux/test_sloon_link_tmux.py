from pathlib import Path
from unittest.mock import Mock

import pytest

from systems.node_types.impl.types.sloon_link_tmux import SloonLinkTmux
from systems.node_types.impl.types import sloon_link_tmux
from systems.node_types.spec.api import NodeContext


def _context(param: str) -> NodeContext:
    return NodeContext(
        node_id=1, workspace_path=Path("/test.sloon"),
        nodes=Mock(**{"get.return_value": param}),
    )


def _new_window_tmux(*args, **kwargs):
    if args[0] == "has-session":
        return Mock(returncode=1)
    if args[0] == "new-session":
        return Mock(stdout="@1\n")
    if args[0] == "list-panes":
        return Mock(stdout="%1\t0\t0\n")
    if args[0] == "split-window":
        return Mock(stdout="%2\n")
    return Mock()


def test_execute_accepts_absolute_sloon_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "home.sloon"
    workspace.mkdir()
    tmux = Mock(side_effect=_new_window_tmux)
    monkeypatch.setenv("TMUX", "client")
    monkeypatch.setattr(
        "systems.node_types.impl.types.sloon_link_tmux._tmux", tmux
    )

    SloonLinkTmux().execute(_context(str(workspace)))

    commands = [argument for call in tmux.call_args_list for argument in call.args]
    assert any("home.sloon" in argument for argument in commands)
    assert any(argument.startswith(str(sloon_link_tmux.SLOON_COMMAND[0]))
               for argument in commands)


def test_execute_ignores_surrounding_param_whitespace(tmp_path, monkeypatch):
    workspace = tmp_path / "home.sloon"
    workspace.mkdir()
    tmux = Mock(side_effect=_new_window_tmux)
    monkeypatch.setenv("TMUX", "client")
    monkeypatch.setattr(sloon_link_tmux, "_tmux", tmux)

    SloonLinkTmux().execute(_context(f"  {workspace}\n"))

    commands = [argument for call in tmux.call_args_list for argument in call.args]
    assert any(str(workspace) in argument for argument in commands)


def test_execute_only_switches_to_existing_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "home.sloon"
    workspace.mkdir()
    name = str(workspace)
    tmux = Mock()
    tmux.side_effect = lambda *args, **kwargs: (
        Mock(returncode=0) if args[0] == "has-session" else Mock()
    )
    monkeypatch.setenv("TMUX", "client")
    monkeypatch.setattr(sloon_link_tmux, "_tmux", tmux)
    monkeypatch.setattr(
        sloon_link_tmux, "_windows", lambda: {name: "@1"}
    )
    SloonLinkTmux().execute(_context(str(workspace)))

    assert tmux.call_args_list[1].args == (
        "switch-client", "-t", "sloon-app:@1"
    )
    assert tmux.call_count == 2


@pytest.mark.parametrize("param", ["relative.sloon", "/tmp/workspace.sloop"])
def test_execute_rejects_non_absolute_or_wrong_extension(param, monkeypatch):
    monkeypatch.setenv("TMUX", "client")

    with pytest.raises(ValueError, match=r"absolute \.sloon path"):
        SloonLinkTmux().execute(_context(param))
