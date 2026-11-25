# Named workspaces

Each workspace is a named, non-hidden directory ending in `.sloon`. Multiple
workspaces can coexist in one parent directory. Initialize them by name:

```bash
sloon init home
sloon init work.sloon
```

These commands create `home.sloon/workspace.db` and
`work.sloon/workspace.db`. The name is required; supplying the suffix is
optional.

Select a workspace explicitly for CLI commands:

```bash
sloon --workspace home.sloon graph
sloon --workspace /absolute/path/to/work.sloon graph 12
```

Or run commands from inside the workspace directory:

```bash
cd home.sloon
sloon graph
sloon
```

`sloon home.sloon` opens Control directly. Sloon never searches parent
directories, scans the current directory, or selects a workspace implicitly.

`graph` returns every node with exactly its stored properties and every edge in
one consistent snapshot. `graph NODE_ID` returns the induced subgraph reachable
from that node by recursively following outgoing edges. Nodes are ordered by
ID; edges are ordered by source and then target. The existing `node list`,
`node get-all`, `edges`, `inputs`, and `outputs` commands remain available for
targeted inspection.

## Converting an existing standalone database

Do not move or overwrite a potentially active SQLite database. From the project
directory that should contain the new workspace, initialize the destination and
copy through SQLite's online backup API:

```bash
sloon init imported
python3 - data/workspace.db imported.sloon/workspace.db <<'PY'
import sqlite3
import sys

source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
destination = sqlite3.connect(sys.argv[2])
try:
    source.backup(destination)
finally:
    destination.close()
    source.close()
PY
```

The backup replaces the newly initialized destination database, not the source.
The copied database must already use the current application schema. The next
`sloon` command opens it directly. Node IDs, edges, properties, Graph UI state,
custom properties, and unrelated tables are retained.

## Textual node properties

Node property values are literal text. Ordinary values do not need JSON
quoting, and JSON documents can be stored as text when desired:

```bash
sloon --workspace home.sloon node create --title "Idea" --weight -3
sloon --workspace home.sloon node set 1 phase anything
sloon --workspace home.sloon node set 1 metadata '{"source":"agent"}'
sloon --workspace home.sloon node create --property 'note=plain text' --property 'empty='
```

JSON is still used for command output and for the `batch` transport. In a
batch, every node-property value must therefore be a JSON string; numbers,
booleans, objects, arrays, and null are rejected as property values.

## Agent CLI skills

The application can print self-contained Markdown instructions for external
agents without opening or creating a workspace:

```bash
sloon skill readonly
sloon skill readwrite
```

Running `sloon skill` lists the available variants. These are static
instructions, not enforced permissions: `readonly` tells an agent to inspect
only, while `readwrite` documents deliberate graph mutations and atomic
batches.
