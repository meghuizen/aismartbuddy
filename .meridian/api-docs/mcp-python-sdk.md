# MCP Python SDK (`mcp`)

The official Python SDK for building Model Context Protocol servers and clients. Provides both a high-level `FastMCP` API (decorator-based, automatic schema generation) and a low-level `Server` API (full protocol control).

**Version researched**: 1.27.0 (released 2026-04-02)
**Protocol version**: 2025-11-25 (LATEST_PROTOCOL_VERSION)
**Python requirement**: >=3.10
**License**: MIT
**Maintainer**: David Soria Parra (Anthropic)
**Official docs**: https://py.sdk.modelcontextprotocol.io/
**GitHub**: https://github.com/modelcontextprotocol/python-sdk

---

## Overview

MCP (Model Context Protocol) is a standardized protocol that lets applications provide context and capabilities to LLMs. The Python SDK lets you build servers that expose three primitives:

| Primitive     | Purpose                                    | Controlled by |
|---------------|--------------------------------------------|---------------|
| **Tools**     | Functions the LLM can call (actions)       | Model         |
| **Resources** | Read-only data sources for context         | Application   |
| **Prompts**   | Pre-built instruction templates            | User          |

The SDK has two API levels:
- **FastMCP** (recommended): Decorator-based, auto-generates JSON schemas from type hints and docstrings. Import from `mcp.server.fastmcp`.
- **Low-level Server**: Full protocol control, manual handler registration. Import from `mcp.server.lowlevel`.

---

## How It Works

### Architecture

```
AI Host (Claude, etc.)
    |
    | JSON-RPC 2.0 over transport
    |
MCP Server (your code)
    |-- Tools (callable functions)
    |-- Resources (data providers)
    |-- Prompts (templates)
    |-- Lifespan (startup/shutdown)
```

The server communicates via JSON-RPC 2.0. Each message is a request, response, or notification. The transport layer handles the wire format:

- **stdio**: Newline-delimited JSON over stdin/stdout. Best for local tools and desktop integrations.
- **Streamable HTTP** (recommended for remote): HTTP POST with SSE streaming responses. Replaces the deprecated SSE transport.
- **SSE** (deprecated): Server-Sent Events. Still supported but new projects should use Streamable HTTP.

### Session Lifecycle

1. Client sends `initialize` with capabilities and protocol version
2. Server responds with its capabilities, name, version
3. Client sends `initialized` notification
4. Normal operation (tools/list, tools/call, resources/read, etc.)
5. Connection closes

The SDK handles this lifecycle automatically. You just register handlers.

### Key Concepts

- **Stateless between calls**: The server does not persist state in memory between tool calls. Any persistence goes through external stores.
- **JSON Schema everywhere**: Tool input schemas, output schemas, resource descriptions all use JSON Schema.
- **Context injection**: Tool/resource/prompt functions can receive a `Context` object by adding a type-annotated parameter. The SDK injects it automatically.
- **Async-first**: All handlers can be async. Sync functions are also supported (called in a thread).

---

## Current State (v1.27.0)

### Dependencies

Core dependencies (installed automatically):
- `anyio` - async I/O
- `pydantic` >=2.0 - schema generation and validation
- `pydantic-settings` - settings from env vars
- `starlette` - ASGI for HTTP transports
- `sse-starlette` - SSE support
- `uvicorn` - ASGI server
- `httpx` - HTTP client
- `httpx-sse` - SSE client
- `jsonschema` - input/output validation
- `python-dotenv` - .env loading

Optional extras:
- `mcp[cli]` - CLI tools including `mcp dev` inspector
- `mcp[rich]` - Rich console output
- `mcp[ws]` - WebSocket transport

### Protocol Versions Supported

- `2025-11-25` (latest)
- `2025-03-26` (default negotiated if client omits version)
- Earlier versions also supported

### What Changed Recently

- FastMCP is now the built-in high-level API (merged from standalone project)
- Streamable HTTP transport added as the recommended remote transport
- SSE transport deprecated
- Elicitation support (form mode and URL mode) added
- Structured output with `outputSchema` validation
- Tool annotations (`ToolAnnotations`) for hints about tool behavior
- DNS rebinding protection for localhost servers
- Experimental task support for long-running operations
- OAuth 2.0 auth support built in

---

## Setup

### Installation

```bash
# Basic install
uv add mcp

# With CLI tools (recommended for development)
uv add "mcp[cli]"

# Or with pip
pip install "mcp[cli]"
```

### Minimum Project Structure

```
my_mcp_server/
  __init__.py       # Empty or package init
  __main__.py       # Entry point: runs the server
  server.py         # FastMCP instance + tool/resource registration
  tools/            # Tool modules (optional, for organization)
    __init__.py
    search.py
    database.py
  resources/        # Resource modules (optional)
    __init__.py
    config.py
```

### Minimal Server

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-server")

@mcp.tool()
async def add(a: int, b: int) -> int:
    """Add two numbers together.

    Args:
        a: First number
        b: Second number
    """
    return a + b

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

### Claude Code Integration

Add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "uv",
      "args": ["run", "python", "-m", "my_mcp_server"]
    }
  }
}
```

---

## FastMCP API (High-Level)

### Creating a Server

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="my-server",                          # Server name (shown to clients)
    instructions="Server for doing X and Y",   # Instructions for the AI
    # HTTP settings (for SSE/Streamable HTTP transports)
    host="127.0.0.1",
    port=8000,
    # Behavior
    debug=False,
    log_level="INFO",                          # DEBUG, INFO, WARNING, ERROR, CRITICAL
    # Duplicate handling
    warn_on_duplicate_tools=True,
    warn_on_duplicate_resources=True,
    warn_on_duplicate_prompts=True,
    # Lifespan for startup/shutdown
    lifespan=None,                             # async context manager
    # Streamable HTTP settings
    stateless_http=False,                      # True = new transport per request
    json_response=False,                       # True = JSON instead of SSE for responses
    streamable_http_path="/mcp",               # Endpoint path
    # SSE settings (deprecated transport)
    sse_path="/sse",
    message_path="/messages/",
)
```

All settings can be set via environment variables with the `FASTMCP_` prefix:
```bash
FASTMCP_DEBUG=true
FASTMCP_LOG_LEVEL=DEBUG
FASTMCP_HOST=0.0.0.0
FASTMCP_PORT=9000
```

Settings are also loaded from `.env` files automatically (via pydantic-settings).

### Running the Server

```python
# Synchronous entry point (blocks)
mcp.run(transport="stdio")              # stdio transport
mcp.run(transport="streamable-http")    # Streamable HTTP transport
mcp.run(transport="sse")                # SSE transport (deprecated)

# Async entry points (for embedding in larger apps)
await mcp.run_stdio_async()
await mcp.run_streamable_http_async()
await mcp.run_sse_async()
```

### `__main__.py` Entry Point Pattern

```python
# my_mcp_server/__main__.py
from my_mcp_server.server import mcp

def main():
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
```

---

## Tools

Tools are functions the LLM can call. They are the most important primitive for most servers.

### Registering Tools

```python
@mcp.tool()
def my_tool(query: str, limit: int = 10) -> str:
    """Search for items matching the query.

    Args:
        query: The search query string
        limit: Maximum number of results to return
    """
    return f"Found {limit} results for {query}"
```

The SDK automatically:
1. Uses the function name as the tool name (or override with `name=`)
2. Uses the docstring as the tool description
3. Generates JSON Schema from type hints
4. Validates input arguments against the schema
5. Handles both sync and async functions

### Tool Decorator Parameters

```python
@mcp.tool(
    name="search_items",                  # Override function name
    title="Search Items",                 # Human-readable title
    description="Search for items",       # Override docstring
    annotations=ToolAnnotations(          # Behavioral hints for clients
        readOnlyHint=True,                # Does not modify environment
        destructiveHint=False,            # Does not destroy data
        idempotentHint=True,              # Same args = same result
        openWorldHint=True,               # Interacts with external systems
    ),
    icons=[Icon(url="https://example.com/icon.png")],
    meta={"version": "1.0"},             # Arbitrary metadata
    structured_output=None,               # None=auto, True=force, False=disable
)
async def search_items(query: str, limit: int = 10) -> str:
    """Search for items."""
    ...
```

### ToolAnnotations

`ToolAnnotations` provides behavioral hints to clients. All fields are optional and are **hints only** -- clients should not make trust decisions based on them from untrusted servers.

```python
from mcp.types import ToolAnnotations

ToolAnnotations(
    title="Human Title",       # Human-readable title
    readOnlyHint=True,         # True = does not modify environment (default: False)
    destructiveHint=False,     # True = may destroy data (default: True when readOnly=False)
    idempotentHint=True,       # True = repeated calls are safe (default: False)
    openWorldHint=True,        # True = interacts with external systems (default: True)
)
```

### Tool Return Types

Tools can return various types. The SDK converts them to MCP content blocks:

```python
# String -> TextContent
@mcp.tool()
def text_tool() -> str:
    return "Hello world"

# Dict/BaseModel -> JSON string in TextContent (or structured output)
@mcp.tool()
def json_tool() -> dict:
    return {"key": "value", "count": 42}

# List -> JSON
@mcp.tool()
def list_tool() -> list[str]:
    return ["a", "b", "c"]

# Image helper -> ImageContent (base64 encoded)
from mcp.server.fastmcp import Image
@mcp.tool()
def image_tool() -> Image:
    return Image(path="/path/to/image.png")
    # or: Image(data=bytes_data, format="png")

# Audio helper -> AudioContent (base64 encoded)
from mcp.server.fastmcp import Audio
@mcp.tool()
def audio_tool() -> Audio:
    return Audio(path="/path/to/audio.wav")

# None -> empty TextContent
@mcp.tool()
def void_tool() -> None:
    do_something()
```

### Structured Output

When a tool has a non-primitive return type annotation (e.g., a Pydantic model), the SDK auto-generates an `outputSchema` and returns structured content alongside unstructured content:

```python
from pydantic import BaseModel

class SearchResult(BaseModel):
    items: list[str]
    total: int

@mcp.tool()
def search(query: str) -> SearchResult:
    """Search and return structured results."""
    return SearchResult(items=["a", "b"], total=2)
```

This sets `outputSchema` in the tool definition and returns both:
- `content`: TextContent with JSON string (for display/backwards compat)
- `structuredContent`: The validated dict (for programmatic use)

Control with `structured_output=`:
- `None` (default): Auto-detect from return type. Primitives (str, int, etc.) are unstructured.
- `True`: Force structured output (fails if return type can't be schematized).
- `False`: Force unstructured output even if return type is a model.

### Context Injection

Any tool function can receive a `Context` object for advanced capabilities:

```python
from mcp.server.fastmcp import Context

@mcp.tool()
async def my_tool(query: str, ctx: Context) -> str:
    """A tool that uses context for logging and progress."""
    # Logging (sent to client)
    await ctx.info(f"Processing query: {query}")
    await ctx.debug("Debug details...")
    await ctx.warning("Something concerning")
    await ctx.error("Something went wrong")

    # Progress reporting
    await ctx.report_progress(progress=50, total=100, message="Halfway done")

    # Read a resource from this server
    contents = await ctx.read_resource("config://settings")

    # Get request metadata
    request_id = ctx.request_id

    # Access the session for advanced operations
    session = ctx.session

    return "Done"
```

The parameter name does not matter -- only the `Context` type annotation. You can name it `ctx`, `context`, `c`, etc.

### Context API Reference

| Method/Property | Description |
|-----------------|-------------|
| `await ctx.info(msg)` | Send info log to client |
| `await ctx.debug(msg)` | Send debug log to client |
| `await ctx.warning(msg)` | Send warning log to client |
| `await ctx.error(msg)` | Send error log to client |
| `await ctx.log(level, msg)` | Send log at specified level |
| `await ctx.report_progress(progress, total, message)` | Report operation progress |
| `await ctx.read_resource(uri)` | Read a resource by URI |
| `await ctx.elicit(message, schema)` | Elicit form input from user |
| `await ctx.elicit_url(message, url, elicitation_id)` | Direct user to URL for out-of-band interaction |
| `ctx.request_id` | Current request ID |
| `ctx.session` | Access underlying ServerSession |
| `ctx.fastmcp` | Access the FastMCP instance |
| `await ctx.close_sse_stream()` | Close SSE stream (Streamable HTTP only) |

### Elicitation (Interactive Input)

Tools can ask the user for additional information during execution:

```python
from pydantic import BaseModel

class ConfirmDelete(BaseModel):
    confirm: bool
    reason: str | None = None

@mcp.tool()
async def delete_item(item_id: str, ctx: Context) -> str:
    """Delete an item with user confirmation."""
    result = await ctx.elicit(
        message=f"Are you sure you want to delete item {item_id}?",
        schema=ConfirmDelete,
    )

    if result.action == "accept" and result.data.confirm:
        # Proceed with deletion
        return f"Deleted {item_id}"
    elif result.action == "decline":
        return "Deletion declined by user"
    elif result.action == "cancel":
        return "Deletion cancelled"
```

Elicitation schema restrictions: Only primitive types (str, int, float, bool), Optional variants, and `list[str]` are allowed in elicitation schemas. No nested models.

### URL Elicitation (Out-of-Band Interaction)

For sensitive data (credentials, OAuth flows, payments) that should NOT pass through the LLM:

```python
@mcp.tool()
async def connect_service(ctx: Context) -> str:
    """Connect to an external service requiring OAuth."""
    result = await ctx.elicit_url(
        message="Please authorize access to your account",
        url="https://example.com/oauth/authorize?client_id=...",
        elicitation_id="oauth-connect-001",
    )

    if result.action == "accept":
        # User navigated to URL; actual auth happened out-of-band
        return "Authorization flow initiated"
    return "Authorization declined"
```

### Removing Tools at Runtime

```python
mcp.remove_tool("tool_name")
```

### Adding Tools Programmatically

```python
def my_func(x: int) -> str:
    """Do something."""
    return str(x)

mcp.add_tool(
    fn=my_func,
    name="custom_name",
    description="Custom description",
)
```

---

## Resources

Resources provide read-only data that applications can include as context.

### Static Resources

```python
@mcp.resource("config://app-settings")
def get_settings() -> str:
    """Application configuration settings."""
    return json.dumps({"debug": False, "version": "1.0"})

@mcp.resource("data://users")
async def get_users() -> str:
    """List of all users."""
    users = await fetch_users_from_db()
    return json.dumps(users)
```

### Resource Decorator Parameters

```python
@mcp.resource(
    "config://app-settings",
    name="app-settings",              # Override function name
    title="Application Settings",     # Human-readable title
    description="Current app config", # Override docstring
    mime_type="application/json",     # MIME type (default: text/plain)
    icons=[...],
    annotations=Annotations(
        audience=["user"],            # "user" and/or "assistant"
        priority=0.8,                 # 0.0 to 1.0
    ),
    meta={"version": "1.0"},
)
def get_settings() -> str:
    ...
```

### Resource Templates (Dynamic URIs)

When a URI contains `{param}` placeholders, the resource becomes a template:

```python
@mcp.resource("weather://{city}/current")
def get_weather(city: str) -> str:
    """Get current weather for a city.

    Args:
        city: City name
    """
    return f"Weather for {city}: Sunny, 72F"

@mcp.resource("db://{database}/{table}")
async def get_table(database: str, table: str) -> str:
    """Read a database table."""
    data = await query_db(database, table)
    return json.dumps(data)
```

URI parameters MUST match function parameters exactly (excluding Context).

### Resource Return Types

- `str` -> text content (default)
- `bytes` -> binary content
- Other types -> JSON serialized via `pydantic_core.to_json()`

### Resource Types Available

The SDK provides several built-in resource types for programmatic use:

```python
from mcp.server.fastmcp.resources import (
    FunctionResource,    # Wraps a function (used by @mcp.resource)
    TextResource,        # Static text
    BinaryResource,      # Static binary data
    FileResource,        # Reads from filesystem
    HttpResource,        # Fetches from HTTP URL
    DirectoryResource,   # Lists directory contents
)

# Example: adding a file resource programmatically
from mcp.server.fastmcp.resources import FileResource
mcp.add_resource(FileResource(
    uri="file:///path/to/data.json",
    path="/path/to/data.json",
    mime_type="application/json",
    name="data-file",
    description="Important data file",
))
```

### Context in Resources

Resource templates can also receive Context:

```python
@mcp.resource("status://{service}")
async def get_status(service: str, ctx: Context) -> str:
    """Get service status."""
    await ctx.info(f"Checking status of {service}")
    return f"{service}: OK"
```

---

## Prompts

Prompts are pre-built templates that help users accomplish specific tasks.

### Registering Prompts

```python
from mcp.server.fastmcp.prompts import Message, UserMessage, AssistantMessage

@mcp.prompt()
def analyze_code(code: str, language: str = "python") -> list[Message]:
    """Analyze code for potential issues.

    Args:
        code: The source code to analyze
        language: Programming language
    """
    return [
        UserMessage(f"Please analyze this {language} code for issues:\n\n```{language}\n{code}\n```"),
        AssistantMessage("I'll analyze the code for potential issues..."),
    ]

@mcp.prompt(
    name="review-pr",
    title="Review Pull Request",
    description="Review a GitHub pull request",
)
async def review_pr(pr_url: str) -> list[Message]:
    """Review a pull request."""
    pr_data = await fetch_pr(pr_url)
    return [
        UserMessage(f"Please review this PR:\n\n{pr_data}"),
    ]
```

### Prompt Return Types

Prompts can return:
- `str` -> Converted to a single UserMessage with TextContent
- `Message` -> Used directly
- `dict` -> Validated as UserMessage or AssistantMessage
- `list` of any of the above

---

## Lifespan (Startup/Shutdown)

Use lifespan for database connections, HTTP clients, or any resource that needs setup/teardown:

```python
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP

@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Initialize and clean up resources."""
    # Startup
    db = await create_db_connection()
    http_client = httpx.AsyncClient()

    try:
        yield {"db": db, "http": http_client}  # Available via context
    finally:
        # Shutdown
        await db.close()
        await http_client.aclose()

mcp = FastMCP("my-server", lifespan=app_lifespan)

@mcp.tool()
async def query_db(sql: str, ctx: Context) -> str:
    """Run a database query."""
    db = ctx.request_context.lifespan_context["db"]
    result = await db.execute(sql)
    return str(result)
```

The dict yielded from the lifespan is accessible via `ctx.request_context.lifespan_context`.

---

## Transports

### stdio (Default, Local)

Best for local tools and desktop integrations. Communication over stdin/stdout using newline-delimited JSON.

```python
mcp.run(transport="stdio")
```

**Critical rule for stdio**: Never write to stdout from your code. `print()` goes to stdout by default and will corrupt JSON-RPC messages. Use:
```python
import sys
print("Debug info", file=sys.stderr)  # Safe
import logging
logging.info("This goes to stderr by default")  # Safe
```

### Streamable HTTP (Recommended for Remote)

HTTP POST with SSE streaming. Supports session resumability.

```python
mcp = FastMCP(
    "my-server",
    host="0.0.0.0",
    port=8000,
    streamable_http_path="/mcp",
    stateless_http=False,  # True for serverless/stateless deployments
)
mcp.run(transport="streamable-http")
```

With event store for resumability:
```python
from mcp.server.streamable_http import EventStore

class MyEventStore(EventStore):
    """Implement for session resumability."""

    async def store_event(self, stream_id, message):
        # Store event, return event ID
        ...

    async def replay_events_after(self, last_event_id, send_callback):
        # Replay events after the given ID
        ...

mcp = FastMCP("my-server", event_store=MyEventStore())
```

### SSE (Deprecated)

Still supported but use Streamable HTTP for new projects.

```python
mcp.run(transport="sse")
```

### Mounting in FastAPI/Starlette

Get the ASGI app for manual mounting:

```python
# Streamable HTTP
starlette_app = mcp.streamable_http_app()

# SSE
starlette_app = mcp.sse_app()

# Mount in FastAPI
from fastapi import FastAPI
app = FastAPI()
app.mount("/mcp", starlette_app)
```

### Custom HTTP Routes

Add non-MCP endpoints to the server:

```python
from starlette.requests import Request
from starlette.responses import JSONResponse

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})
```

Custom routes do NOT require authorization (useful for health checks, OAuth callbacks).

---

## Transport Security

DNS rebinding protection is auto-enabled for localhost servers:

```python
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "my-server",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
    ),
)
```

Validates Host, Origin, and Content-Type headers on incoming requests.

---

## Authentication (OAuth 2.0)

The SDK has built-in OAuth support for remote transports:

```python
from mcp.server.auth.settings import AuthSettings
from mcp.server.auth.provider import TokenVerifier

class MyTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> dict:
        # Verify JWT or opaque token
        ...

mcp = FastMCP(
    "my-server",
    token_verifier=MyTokenVerifier(),
    auth=AuthSettings(
        issuer_url="https://auth.example.com",
        resource_server_url="https://my-mcp-server.example.com",
        required_scopes=["read", "write"],
    ),
)
```

---

## Low-Level Server API

For full protocol control, use `Server` directly:

```python
from mcp.server.lowlevel.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
import mcp.types as types

server = Server("my-server", instructions="A helpful server")

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="add",
            description="Add two numbers",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"},
                },
                "required": ["a", "b"],
            },
        ),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "add":
        result = arguments["a"] + arguments["b"]
        return [types.TextContent(type="text", text=str(result))]
    raise ValueError(f"Unknown tool: {name}")

@server.list_resources()
async def list_resources() -> list[types.Resource]:
    return [...]

@server.read_resource()
async def read_resource(uri) -> Iterable[ReadResourceContents]:
    return [ReadResourceContents(content="data", mime_type="text/plain")]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )

import anyio
anyio.run(main)
```

### Low-Level Handler Decorators

| Decorator | Signature |
|-----------|-----------|
| `@server.list_tools()` | `() -> list[Tool]` |
| `@server.call_tool()` | `(name: str, arguments: dict) -> list[ContentBlock] \| dict \| tuple` |
| `@server.list_resources()` | `() -> list[Resource]` |
| `@server.read_resource()` | `(uri: AnyUrl) -> Iterable[ReadResourceContents]` |
| `@server.list_resource_templates()` | `() -> list[ResourceTemplate]` |
| `@server.list_prompts()` | `() -> list[Prompt]` |
| `@server.get_prompt()` | `(name: str, arguments: dict \| None) -> GetPromptResult` |
| `@server.completion()` | `(ref, argument, context) -> Completion \| None` |
| `@server.set_logging_level()` | `(level: LoggingLevel) -> None` |
| `@server.progress_notification()` | `(token, progress, total, message) -> None` |

### Accessing Request Context (Low-Level)

```python
@server.call_tool()
async def call_tool(name: str, arguments: dict):
    ctx = server.request_context  # RequestContext object
    session = ctx.session          # ServerSession
    lifespan = ctx.lifespan_context
    request_id = ctx.request_id
    meta = ctx.meta                # progress token, etc.
    ...
```

---

## Session Management

### ServerSession

The `ServerSession` manages communication between server and client. It is created automatically by `Server.run()` and provides methods for server-to-client communication:

```python
session = ctx.session  # Get from request context

# Send log messages
await session.send_log_message(level="info", data="Processing...", logger="my-tool")

# Send progress
await session.send_progress_notification(
    progress_token="token-123",
    progress=50,
    total=100,
    message="Halfway done",
)

# Notify client of changes
await session.send_resource_list_changed()
await session.send_tool_list_changed()
await session.send_prompt_list_changed()
await session.send_resource_updated(uri)

# Request sampling (ask client to call LLM)
result = await session.create_message(
    messages=[types.SamplingMessage(role="user", content=types.TextContent(type="text", text="Hello"))],
    max_tokens=100,
)

# List client roots
roots = await session.list_roots()

# Check client capabilities
has_sampling = session.check_client_capability(
    types.ClientCapabilities(sampling=types.SamplingCapability())
)

# Send ping
await session.send_ping()
```

### Client Capabilities

Check what the client supports before using features:

```python
client_caps = session.client_params.capabilities if session.client_params else None

# Check specific capabilities
if client_caps and client_caps.sampling:
    # Client supports sampling (create_message)
    pass
if client_caps and client_caps.elicitation:
    # Client supports elicitation
    pass
if client_caps and client_caps.roots:
    # Client supports roots
    pass
```

---

## Error Handling

### McpError

The primary exception type for MCP protocol errors:

```python
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData, INVALID_PARAMS, METHOD_NOT_FOUND, INTERNAL_ERROR

# Raise a protocol error
raise McpError(ErrorData(
    code=INVALID_PARAMS,
    message="Invalid parameter: limit must be positive",
    data={"param": "limit", "value": -1},
))
```

### Error Codes

From the JSON-RPC 2.0 spec and MCP extensions:
- `PARSE_ERROR = -32700`
- `INVALID_REQUEST = -32600`
- `METHOD_NOT_FOUND = -32601`
- `INVALID_PARAMS = -32602`
- `INTERNAL_ERROR = -32603`
- `URL_ELICITATION_REQUIRED = -32042` (MCP extension)

### FastMCP Exception Hierarchy

```
Exception
  FastMCPError
    ValidationError     # Parameter/return value validation
    ResourceError       # Resource operations
    ToolError           # Tool operations
  InvalidSignature      # Bad function signature for FastMCP
  McpError              # Protocol-level error (from shared.exceptions)
    UrlElicitationRequiredError  # Tool needs URL elicitation
```

### Error Handling in Tools

In FastMCP, exceptions in tool functions are caught and returned as error results:

```python
@mcp.tool()
def risky_tool(path: str) -> str:
    """Read a file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    # Exception is caught, wrapped in CallToolResult with isError=True
    return open(path).read()
```

In the low-level API, the `call_tool` handler wraps exceptions:

```python
@server.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        ...
    except Exception as e:
        # Returning error result manually:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=str(e))],
            isError=True,
        )
```

### UrlElicitationRequiredError

Special error for tools that need out-of-band URL interactions before proceeding:

```python
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp.types import ElicitRequestURLParams

raise UrlElicitationRequiredError([
    ElicitRequestURLParams(
        mode="url",
        message="Authorization required",
        url="https://example.com/oauth/authorize",
        elicitationId="auth-001",
    )
])
```

---

## Content Types

### MCP Content Blocks

```python
from mcp.types import (
    TextContent,          # text + optional annotations
    ImageContent,         # base64-encoded image + MIME type
    AudioContent,         # base64-encoded audio + MIME type
    EmbeddedResource,     # Embedded resource content
    ResourceLink,         # Link to a resource
)

# ContentBlock union:
ContentBlock = TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource
```

### Creating Content Blocks

```python
# Text
TextContent(type="text", text="Hello world")

# Image (base64)
ImageContent(type="image", data="base64string...", mimeType="image/png")

# Audio (base64)
AudioContent(type="audio", data="base64string...", mimeType="audio/wav")

# Embedded resource
EmbeddedResource(
    type="resource",
    resource=TextResourceContents(uri="file:///path", text="content", mimeType="text/plain"),
)

# Resource link
ResourceLink(
    type="resource_link",
    uri="file:///path/to/file",
    name="My File",
    description="An important file",
    mimeType="text/plain",
)
```

### FastMCP Helpers

```python
from mcp.server.fastmcp import Image, Audio

# Image from file
Image(path="/path/to/photo.png")
Image(data=raw_bytes, format="jpeg")

# Audio from file
Audio(path="/path/to/audio.mp3")
Audio(data=raw_bytes, format="wav")
```

---

## Best Practices

### Tool Descriptions

Tool descriptions are critical because they are what the AI reads to decide when and how to use tools. From official docs and source code analysis:

1. **Use docstrings as descriptions.** FastMCP uses the function docstring as the tool description. Write clear, action-oriented docstrings.

2. **Document all parameters in the docstring.** Use `Args:` section in Google-style docstrings. The SDK extracts these for the schema.

3. **Be specific about what the tool does.** "Search for weather alerts in a US state" is better than "Get weather data".

4. **Document constraints.** If a parameter has format requirements (e.g., "Two-letter US state code"), state them explicitly.

5. **Use type hints aggressively.** `str`, `int`, `float`, `bool`, `list[str]`, `Optional[int]`, Pydantic models, enums -- all generate proper JSON Schema.

6. **Prefer small, focused tools.** One tool per action. Don't create a god-tool that does everything.

7. **Use `ToolAnnotations`** to signal behavior:
   - Read-only tools: `readOnlyHint=True` (no side effects)
   - Destructive tools: `destructiveHint=True` (clients may add confirmation)
   - Idempotent tools: `idempotentHint=True` (safe to retry)

### Example of a Well-Described Tool

```python
@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
async def search_issues(
    query: str,
    repo: str,
    state: str = "open",
    limit: int = 20,
) -> str:
    """Search GitHub issues in a repository.

    Searches issue titles and bodies using GitHub's search syntax.
    Returns a formatted list of matching issues with their number,
    title, state, and URL.

    Args:
        query: Search query string. Supports GitHub search syntax
               (e.g., 'label:bug', 'is:open', 'author:user').
        repo: Repository in 'owner/name' format (e.g., 'anthropic/claude').
        state: Filter by issue state. One of 'open', 'closed', or 'all'.
        limit: Maximum number of issues to return (1-100, default 20).
    """
    ...
```

### Server Design

1. **Tools are stateless.** Don't store state in module globals between tool calls. Use a database, file, or external service.

2. **Use lifespan for expensive resources.** Database connections, HTTP clients, API keys -- initialize in lifespan, access via context.

3. **Configuration via environment variables.** Use `.env` files and `os.environ`. Never hardcode secrets.

4. **Handle errors gracefully.** Return informative error messages. Don't let raw tracebacks leak to clients.

5. **Never print to stdout in stdio mode.** Use `logging` or `print(..., file=sys.stderr)`.

6. **Validate inputs yourself** even though the SDK validates against the JSON schema. Schema validation catches type errors; you need to catch semantic errors (e.g., "file not found", "permission denied").

### Multi-Tool Server Organization

For servers with many tools, organize by module:

```python
# server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-server")

# Import tools from modules (they register via decorator side effects)
import my_server.tools.search    # registers @mcp.tool() decorated functions
import my_server.tools.database
import my_server.tools.files
```

Or use `add_tool` for more control:

```python
# server.py
from mcp.server.fastmcp import FastMCP
from my_server.tools.search import search_web, search_files
from my_server.tools.database import query, insert

mcp = FastMCP("my-server")
mcp.add_tool(search_web, name="search_web", description="Search the web")
mcp.add_tool(search_files, name="search_files", description="Search local files")
mcp.add_tool(query, name="db_query", description="Query the database")
```

---

## Limits and Constraints

- **Protocol version negotiation**: Server and client negotiate a version. The server falls back to LATEST_PROTOCOL_VERSION if the client's version is not in SUPPORTED_PROTOCOL_VERSIONS.
- **Tool name validation**: Tool names are validated and warnings are emitted for non-standard names. Use alphanumeric, underscore, and hyphen characters.
- **Elicitation schemas**: Only primitive types, Optional primitives, and list[str]. No nested models.
- **Resource URIs**: Any URI scheme is valid. Use descriptive schemes (e.g., `db://`, `config://`, `weather://`).
- **No built-in rate limiting**: Implement your own if needed for external API calls.
- **No built-in persistence**: The SDK is stateless. Use external stores for data persistence.

---

## Common Mistakes

1. **Using `@tool` instead of `@tool()`** -- The decorator must be called with parentheses, even with no arguments. The SDK raises `TypeError: Did you forget to call it?`

2. **Writing to stdout in stdio mode** -- `print()` corrupts JSON-RPC. Use `logging` or `print(file=sys.stderr)`.

3. **Missing type hints on tool parameters** -- Without type hints, parameters default to `Any` and get a generic JSON Schema (`{"type": "string"}`). Always add type hints.

4. **Forgetting to `await` in async tools** -- If your tool is async but you forget to await async calls inside it, you get coroutine objects instead of results.

5. **Mismatch between URI template params and function params** -- `@mcp.resource("data://{x}/{y}")` requires exactly `def func(x, y)`. Extra or missing params raise `ValueError`.

6. **Storing state in module globals** -- Tools are stateless between calls. Module globals persist only within a single server process, which may restart.

7. **Not handling errors in tools** -- Unhandled exceptions become `isError=True` results with the exception message. This is fine for development but consider explicit error handling for production.

8. **Using deprecated SSE transport for new projects** -- Use `streamable-http` instead.

---

## Gotchas

1. **Claude Desktop sends JSON strings for complex types.** The SDK's `pre_parse_json` method handles this automatically -- it detects when a list or dict was serialized as a JSON string inside a string parameter and pre-parses it. You don't need to handle this yourself.

2. **Sync functions are supported but run in threads.** FastMCP detects whether your function is async or sync and handles it appropriately. Sync functions run via `anyio.to_thread`.

3. **`structured_output` auto-detection.** If your function returns `str`, `int`, `float`, `bool`, `bytes`, or `None`, the SDK treats it as unstructured. If it returns a Pydantic model, dict type, TypedDict, or dataclass, it auto-creates an output schema. Override with `structured_output=True/False`.

4. **Tool names from function names.** The tool name defaults to the function name. Lambda functions require an explicit `name=` parameter.

5. **FastMCP settings from environment.** All FastMCP settings can be overridden via `FASTMCP_*` env vars. This means `FASTMCP_PORT=9000` in your environment will override `port=8000` in the constructor.

6. **Duplicate tool handling.** If you register two tools with the same name, the first one wins and a warning is logged (if `warn_on_duplicate_tools=True`). The second registration is silently ignored -- it does NOT overwrite.

7. **DNS rebinding protection auto-enabled for localhost.** When `host` is `127.0.0.1`, `localhost`, or `::1`, the SDK automatically adds `TransportSecuritySettings` with protection enabled. Pass `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)` to disable.

8. **Request context is a ContextVar.** `server.request_context` uses Python's `contextvars` module. It's only available inside a request handler. Accessing it outside raises `LookupError`.

---

## Testing

### MCP Inspector

The SDK ships with a CLI inspector tool:

```bash
# Install CLI extras
uv add "mcp[cli]"

# Run the inspector against your server
mcp dev my_server/server.py
```

### In-Process Testing

Use `raise_exceptions=True` in `Server.run()` for tests to get proper stack traces:

```python
await server.run(
    read_stream,
    write_stream,
    init_options,
    raise_exceptions=True,  # Exceptions propagate instead of being swallowed
)
```

---

## Links

- **Official docs**: https://py.sdk.modelcontextprotocol.io/
- **GitHub**: https://github.com/modelcontextprotocol/python-sdk
- **PyPI**: https://pypi.org/project/mcp/
- **MCP specification**: https://modelcontextprotocol.io/docs/learn/server-concepts
- **Build a server guide**: https://modelcontextprotocol.io/docs/develop/build-server
- **Protocol spec**: https://github.com/modelcontextprotocol/specification
- **MCP Inspector**: `mcp dev` CLI tool
