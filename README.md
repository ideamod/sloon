# Sloon

Sloon is an interactive graph-based workspace for humans, tools, and AI agents.

It provides a shared, editable graph that can be manipulated both by humans through an interactive interface and by external programs through a command-line interface.

Rather than imposing a predefined workflow, Sloon allows users to build and evolve their own structures, connect information with actions, and extend the behavior of nodes.

## Features

- Interactive graph visualization and navigation.
- Persistent nodes, directed edges, and properties.
- Expandable and collapsible graph structures.
- Command-line access to the graph.
- Extensible node types.
- Integration with external tools and AI agents.
- Independent, local workspaces.

## Getting started

Clone the repository:

```sh
git clone https://github.com/ideamod/sloon.git
cd sloon
```

Create a Python virtual environment and install dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create a workspace:

```sh
./sloon init example
```

Open the workspace in the graph visualization interface:

```sh
./sloon --workspace example.sloon visualize
```

Open the control interface:

```sh
./sloon --workspace example.sloon control
```

## CLI and agent integration

To see available command-line options:

```sh
./sloon --help
```

Sloon also provides built-in instructions for interacting with the graph through its command-line interface. These instructions can be used by both humans and AI agents.

To learn how to read and modify the graph:

```sh
./sloon skill readwrite
```

To learn how to inspect the graph without modifying it:

```sh
./sloon skill readonly
```

## Development

Sloon is organized into systems with explicit contracts, implementations, declared dependencies, and tests.

The project aims to keep graph storage, layout, visualization, interaction, and node behavior separate.

To run the tests:

```sh
python -m pip install pytest
python -m pytest
```

## Project status

Sloon is in early development. Its interfaces, architecture, and workspace format may change.


## License

Sloon is licensed under the [MIT License](LICENSE).
