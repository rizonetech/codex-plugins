# MCP Client Configuration

ChromeMCP runs a Streamable HTTP MCP server at:

```text
http://localhost:8931/mcp
```

Start and verify it before configuring clients:

```bash
cd /path/to/ChromeMCP
./mcp-up
bash mcp/test.sh
```

## Generic MCP Snippet

Merge the `chromemcp-playwright` entry into the MCP client config:

```json
{
  "mcpServers": {
    "chromemcp-playwright": {
      "type": "http",
      "url": "http://localhost:8931/mcp"
    }
  }
}
```

Older MCP clients that do not support Streamable HTTP can use `http://localhost:8931/sse`.

## Claude Code

Use a project-local `.mcp.json` when you want ChromeMCP available only for one project:

```json
{
  "mcpServers": {
    "chromemcp-playwright": {
      "type": "http",
      "url": "http://localhost:8931/mcp"
    }
  }
}
```

For global availability, merge the same `mcpServers` entry into `~/.claude.json`.

## Cursor

Merge the same `mcpServers` entry into:

```text
~/.cursor/mcp.json
```

## Codex

Use the local Codex plugin. See `docs/CODEX_PLUGIN.md`.

## Python Scripts

Use the supported standard-library Python helper instead of copying test
harness code:

```python
from mcp.client import McpClient

client = McpClient()
client.initialize()
print(client.tool_text(client.call_tool("browser_tabs", {"action": "list"})))
```

See `docs/PYTHON_CLIENT.md` for tab-session helpers, structured results,
CLI usage, auth lookup, and common failure handling.
