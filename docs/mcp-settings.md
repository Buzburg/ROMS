# MCP settings

The Python stdio server and compiled Mojo MCP bridge enforce the same operator-selected tool policy. The default `read_only` profile keeps knowledge search, context preparation, memory recall and inspection available. Tool schemas remain discoverable so clients can explain disabled capabilities; calls are checked before the handler runs.

## Enable authoring

Set these variables in the MCP server process environment (or your client’s server `env` configuration) and restart it:

```json
{
  "ROMS_MCP_PROFILE": "local",
  "ROMS_MCP_ALLOW_DESTRUCTIVE": "1"
}
```

`local` enables tools that import documents, author skills, retain memories, write tickets and record advisory decisions. Omit `ROMS_MCP_ALLOW_DESTRUCTIVE` to keep snapshot rewind, associative memory erasure and permanent memory deletion disabled. Setting the destructive flag alone does not override `read_only`.

These controls change MCP access, not the underlying algorithms, direct Python APIs or CLI. Read tools and startup may still create databases, indexes and caches. The file watcher still indexes configured knowledge and skills. This is not a read-only filesystem, a sandbox, client authentication or a tenant boundary. Use trusted local clients; configured providers and first-use model downloads have their own network behavior.

## Plugins

Python plugins are disabled by default. To enable the bundled source navigation plugin:

```json
{
  "ROMS_MCP_PROFILE": "local",
  "ROMS_MCP_PLUGINS": "code_search"
}
```

Use comma-separated module stems, without `.py`, for additional reviewed modules. Symlinked plugin files and plugin roots are rejected. For automatic reload of these same allowed modules, also set `ROMS_MCP_HOT_RELOAD=1`; otherwise restart to load changes. The compiled Mojo bridge does not load Python plugins.

Plugins execute trusted host code and can access the server’s files and credentials. Allowlisting is an operator selection mechanism, not isolation of malicious code. Unknown plugin tools are denied by `read_only`; in `local` the operator trusts their implementation. Built-in annotations describe capabilities for clients; middleware, not annotations, enforces the profile.

## Request limits

| Setting | Default | Allowed values |
| --- | --- | --- |
| `ROMS_MCP_PROFILE` | `read_only` | `read_only`, `local` |
| `ROMS_MCP_ALLOW_DESTRUCTIVE` | off | `1` to enable |
| `ROMS_MCP_CALLS_PER_MINUTE` | `60` | `1`–`600` |
| `ROMS_MCP_MAX_CONCURRENT` | `4` | `1`–`16` |
| `ROMS_MCP_PLUGINS` | empty | Comma-separated module names |
| `ROMS_MCP_HOT_RELOAD` | off | `1` to enable |

Limits apply to tool calls per server process, across clients, using a rolling 60-second window. Denied attempts count toward the budget. Failure and cancellation release the active-call slot; over-limit calls return errors instead of queuing. Resource reads and prompt retrieval are outside this tool-call limiter. Restarting resets the counters. Invalid profiles or numeric limits fail startup.

## October 2026 compatibility notes

Existing clients that author content must opt into `local`; existing plugin users must name their modules explicitly. Specialist implementations and tool IDs remain unchanged. Snapshot restore also rejects unsafe paths, missing/corrupt blobs and snapshots without a matching saved workspace identity; see [snapshot safety](../SNAPSHOT_SAFETY.md). Embedding initialization can now retry after an initial model-load failure without reconfiguring PyTorch interop threads.
