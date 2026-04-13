# AISmartBuddy

An MCP (Model Context Protocol) server that gives AI assistants on-demand SQL, graph, structured-thinking, holonic, scoring, and YouTube ingestion capabilities — with token-optimized output, multi-tenant isolation, and Arrow/Polars-backed performance.

**Repo**: https://github.com/meghuizen/aismartbuddy

---

## What you get

- **49 MCP tools** across seven domains (SQL · Graph · Think · Holon · Score · YouTube · Meta)
- **Token-optimized output** — Arrow → Polars → CSV pipeline (10-100× faster than `csv.writer`); transcripts in compact `[MM:SS] text` Markdown
- **Multi-tenant** — every session bound to `(user_id, project_id)` with per-session locks
- **Cursor-based pagination** — page through huge result sets without re-running queries
- **YouTube ingestion** — `get_youtube_information` returns title, description, available languages, and the full timed transcript in one call; lxml-cached on disk; gracefully degrades on partial failures
- **Three transports** — `stdio` (default, for desktop clients), `sse` (for remote)

---

## Run instantly with `uvx` (no clone, no install)

The fastest way to use AISmartBuddy is with `uvx`, which fetches and runs the latest `main` from GitHub on demand:

```bash
# stdio (default — for Claude Code / Claude Desktop)
uvx --from git+https://github.com/meghuizen/aismartbuddy aismartbuddy

# Pin a specific tag for reproducibility
uvx --from git+https://github.com/meghuizen/aismartbuddy@v0.1.0 aismartbuddy

# SSE for remote use
uvx --from git+https://github.com/meghuizen/aismartbuddy aismartbuddy \
    --transport sse --host 0.0.0.0 --port 8000
```

`uv` caches the build, so subsequent runs are instant. Force a refresh with `--reinstall` or `uv cache clean`.

---

## Connect to Claude Code

The `claude mcp add` CLI is the simplest path:

```bash
claude mcp add aismartbuddy uvx --from git+https://github.com/meghuizen/aismartbuddy aismartbuddy
```

Or hand-edit `~/.claude.json` (project-scoped) / `~/.claude/settings.json` (user-scoped):

```json
{
  "mcpServers": {
    "aismartbuddy": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/meghuizen/aismartbuddy",
        "aismartbuddy"
      ],
      "env": {
        "AISMARTBUDDY_DEFAULT_USER_ID": "your-name",
        "AISMARTBUDDY_DEFAULT_PROJECT_ID": "scratch"
      }
    }
  }
}
```

Verify with `/mcp` inside Claude Code, or:

```bash
claude mcp list
claude mcp get aismartbuddy
```

---

## Connect to Claude Desktop

Edit your `claude_desktop_config.json`:

| OS | Path |
|---|---|
| **macOS** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Windows** | `%APPDATA%\Claude\claude_desktop_config.json` |
| **Linux** | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "aismartbuddy": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/meghuizen/aismartbuddy",
        "aismartbuddy"
      ]
    }
  }
}
```

Restart Claude Desktop. The 49 tools should appear in the tool inventory icon.

> **Windows note**: if `uvx` isn't on `%PATH%` for the desktop process, use the absolute path: `"command": "C:\\Users\\<you>\\.local\\bin\\uvx.exe"`.

---

## Debugging

### 1. Logs

The server prints startup info and warnings to **stderr** (stdout is reserved for the JSON-RPC stream on stdio). Capture them while running through Claude clients via your shell:

```bash
# Run manually with stderr captured to a file
uvx --from git+https://github.com/meghuizen/aismartbuddy aismartbuddy 2>aismartbuddy.log

# In another terminal
tail -f aismartbuddy.log
```

Increase Python logging verbosity with the standard `LOGLEVEL`:

```bash
LOGLEVEL=DEBUG uvx --from git+https://github.com/meghuizen/aismartbuddy aismartbuddy 2>aismartbuddy.log
```

### 2. MCP Inspector (UI)

The official MCP inspector lets you click through tools, prompts, and resources:

```bash
npx @modelcontextprotocol/inspector \
    uvx --from git+https://github.com/meghuizen/aismartbuddy aismartbuddy
```

It opens a local web UI; you can call any tool with arbitrary arguments and inspect the JSON-RPC traffic.

### 3. Talk to it as SSE manually

When debugging tool wiring, run as SSE so you can poke at it with `curl`:

```bash
uvx --from git+https://github.com/meghuizen/aismartbuddy aismartbuddy \
    --transport sse --host 127.0.0.1 --port 8000

# Open the SSE event stream in another terminal
curl -N http://127.0.0.1:8000/sse
```

### 4. Attach a Python debugger

For deep dives into a specific tool, install once and attach `debugpy`:

```bash
git clone https://github.com/meghuizen/aismartbuddy
cd aismartbuddy
uv sync --all-extras
uv pip install debugpy

# Run with debugpy listening on port 5678
uv run python -m debugpy --listen 5678 --wait-for-client \
    -m aismartbuddy --transport sse --port 8000
```

In VS Code, add a launch config:

```json
{
  "type": "debugpy",
  "request": "attach",
  "name": "Attach to AISmartBuddy",
  "connect": { "host": "localhost", "port": 5678 }
}
```

### 5. Smoke test in Python

A one-liner end-to-end check (uses the actual server):

```bash
uv run python -c "
import anyio
from aismartbuddy import youtube_client as yt_mod
from aismartbuddy.tools.youtube import get_youtube_information

async def main():
    yt_mod.youtube_client = yt_mod.YouTubeClient.create()
    try:
        out = await get_youtube_information('https://www.youtube.com/watch?v=LM7DByKOHBs')
        print(out[:400])
    finally:
        yt_mod.youtube_client.close()

anyio.run(main)
"
```

### 6. Common issues

| Symptom | Likely cause | Fix |
|---|---|---|
| `Session 'X' not found` | Session expired (default 1h idle) or owned by a different user_id | Re-create or pass the right `user_id` parameter |
| `cache=miss-degraded` in YouTube response | YouTube returned no transcript (disabled / processing / rate-limited) | Read the `## Transcript` block — it explains what to do (retry / different language / skip) |
| Tool not visible in client | Client didn't restart, or stdio config wrong | Restart client; check `claude mcp get aismartbuddy` for status |
| `YouTubeClient init failed` in logs | Network blocked at startup | Server still works for non-YouTube tools; YouTube tool returns clear error at call time |

---

## Local development

```bash
git clone https://github.com/meghuizen/aismartbuddy
cd aismartbuddy
uv sync --all-extras

# Run server (stdio)
uv run python -m aismartbuddy

# Tests
uv run pytest -v                       # unit tests (skips integration)
uv run pytest -m integration -v        # network-dependent integration tests

# Lint + type
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run pyright
```

---

## Remote deployment

There are two paths depending on your authentication needs:

| Need | Choice |
|---|---|
| Just expose it on a private network, no auth | `--transport sse` behind a VPN / private DNS |
| Production with Entra ID OAuth | **App Service for Containers + Easy Auth** (recommended — Easy Auth handles OAuth) **OR** Container Apps with a TokenVerifier wired into FastMCP |

### Option A — App Service for Containers + Entra ID Easy Auth (recommended)

This is the lowest-friction production path: Easy Auth performs the entire OAuth dance, validates the token, and forwards the user identity in `X-MS-CLIENT-PRINCIPAL-*` headers. Your server doesn't have to implement OAuth itself.

**Architecture:**

```
┌────────────┐        ┌─────────────────────────┐        ┌──────────────────────┐
│ MCP client │──HTTPS─│ App Service Easy Auth   │────────│ AISmartBuddy (SSE)   │
│ (browser/  │  +OAuth│ (Entra ID, OIDC, OAuth) │ Trusted│ /sse, /messages/     │
│  agent)    │        │ injects X-MS-CLIENT-*   │ network│ Reads headers as     │
└────────────┘        └─────────────────────────┘        │ user_id              │
                                                         └──────────────────────┘
```

**Step 1 — Register the app in Entra ID**

```bash
# Set variables
APP_NAME="aismartbuddy-mcp"
TENANT_ID="<your-tenant-id>"
WEBAPP_NAME="aismartbuddy"           # globally unique
RG="rg-aismartbuddy"
LOCATION="westeurope"

# Create resource group
az group create -n $RG -l $LOCATION

# Register app in Entra ID
APP_ID=$(az ad app create --display-name $APP_NAME \
    --sign-in-audience AzureADMyOrg \
    --query appId -o tsv)

# Add a client secret (or use a federated credential / managed identity)
SECRET=$(az ad app credential reset --id $APP_ID --query password -o tsv)
```

**Step 2 — Build and push the container**

The repo already has a Dockerfile. Switch its `CMD` to SSE and push to ACR:

```bash
# Override CMD at runtime — no Dockerfile edit needed
ACR=$(az acr create -n acr$RANDOM -g $RG --sku Basic --query name -o tsv)
az acr login -n $ACR

docker build -t $ACR.azurecr.io/aismartbuddy:latest .
docker push $ACR.azurecr.io/aismartbuddy:latest
```

**Step 3 — Create the App Service**

```bash
PLAN=$(az appservice plan create -n plan-$WEBAPP_NAME -g $RG \
    --is-linux --sku B1 --query name -o tsv)

az webapp create -n $WEBAPP_NAME -g $RG -p $PLAN \
    --container-image-name $ACR.azurecr.io/aismartbuddy:latest

# Override the entrypoint to run SSE
az webapp config container set -n $WEBAPP_NAME -g $RG \
    --container-startup-command "aismartbuddy --transport sse --host 0.0.0.0 --port 8000"

# App Service expects port 80; map our SSE port
az webapp config appsettings set -n $WEBAPP_NAME -g $RG --settings WEBSITES_PORT=8000
```

**Step 4 — Enable Easy Auth (Entra ID)**

In Azure Portal: **App Service → Authentication → Add identity provider → Microsoft**.
- **App registration**: pick the one created in Step 1
- **Restrict access**: "Require authentication"
- **Unauthenticated requests**: HTTP 401 Unauthorized
- **Token store**: enabled

After save, every request to your app must carry a valid Entra ID token. Easy Auth validates it and injects:
- `X-MS-CLIENT-PRINCIPAL-NAME` — user's UPN (e.g. `alice@contoso.com`)
- `X-MS-CLIENT-PRINCIPAL-ID` — object ID (stable across renames)
- `X-MS-TOKEN-AAD-ACCESS-TOKEN` — pass-through token if you need to call downstream APIs

**Step 5 — Map the principal to AISmartBuddy `user_id`**

The current code reads `user_id` from `ctx.client_id` (Bearer token via MCP SDK), the explicit `user_id` parameter, or the `AISMARTBUDDY_DEFAULT_USER_ID` env var (in that priority). With Easy Auth, the simplest wire-up is a tiny middleware in `server.py` that reads `X-MS-CLIENT-PRINCIPAL-ID` and stores it on the request context.

Add this to `server.py` (near where `mcp = FastMCP(...)` is created):

```python
# server.py — middleware to bind Easy Auth identity to MCP ctx.client_id
from starlette.middleware.base import BaseHTTPMiddleware

class _EasyAuthIdentityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        principal_id = request.headers.get("x-ms-client-principal-id")
        if principal_id:
            # Stash on scope so MCP request context can pick it up.
            request.scope["mcp_client_id"] = principal_id
        return await call_next(request)

mcp = FastMCP(SERVER_NAME, lifespan=app_lifespan)
# Inject into the SSE app's middleware stack at startup
@mcp.app.on_event("startup")
async def _wire_middleware():
    mcp.app.add_middleware(_EasyAuthIdentityMiddleware)
```

Then update `identity.py:resolve_identity` to also check `request.scope` for `mcp_client_id` (1-line change). With this in place, every SQL/graph/think session is bound to the authenticated Entra principal — tenants are properly isolated.

**Step 6 — Connect from a client**

For Claude Code / Desktop pointed at the remote SSE endpoint:

```json
{
  "mcpServers": {
    "aismartbuddy-prod": {
      "url": "https://aismartbuddy.azurewebsites.net/sse",
      "headers": {
        "Authorization": "Bearer <your-entra-token>"
      }
    }
  }
}
```

Acquire the bearer token from your IdP flow (e.g. `az account get-access-token --resource <APP_ID>`).

### Option B — Container Apps with built-in Entra ID OAuth (recommended for MCP-native OAuth)

The repo ships a `TokenVerifier` for Microsoft Entra ID at `src/aismartbuddy/auth.py`. **No code changes required** — activate via environment variables. The server validates incoming Bearer tokens against the configured Entra tenant's JWKS, and `ctx.client_id` becomes the Entra `oid` (stable principal ID), which the multi-tenant model (`identity.py`) automatically picks up to scope every session per user.

**Step 1 — Register an Entra app + expose a scope**

```bash
APP_NAME="aismartbuddy-mcp"
TENANT_ID="<your-tenant-id>"
RG="rg-aismartbuddy"
LOCATION="westeurope"

az group create -n $RG -l $LOCATION

# Create app registration
APP_ID=$(az ad app create --display-name $APP_NAME \
    --sign-in-audience AzureADMyOrg --query appId -o tsv)

# Set the Application ID URI (used as the audience claim)
APP_URI="api://$APP_ID"
az ad app update --id $APP_ID --identifier-uris $APP_URI

# Expose the mcp.invoke scope (one-shot via the manifest)
SCOPE_ID=$(uuidgen)  # or python -c "import uuid; print(uuid.uuid4())"
cat > scopes.json <<EOF
{
  "api": {
    "oauth2PermissionScopes": [{
      "id": "$SCOPE_ID",
      "value": "mcp.invoke",
      "type": "User",
      "adminConsentDisplayName": "Invoke AISmartBuddy MCP tools",
      "adminConsentDescription": "Allows the calling app to invoke MCP tools.",
      "userConsentDisplayName": "Use AISmartBuddy MCP",
      "userConsentDescription": "Use AISmartBuddy MCP on your behalf.",
      "isEnabled": true
    }]
  }
}
EOF
az ad app update --id $APP_ID --set @scopes.json
```

**Step 2 — Build the container with the [entra] extra**

The extra adds `pyjwt[crypto]` + `httpx` (the latter is already a transitive dep). Update the Dockerfile or override at install time:

```dockerfile
# Dockerfile — add this line if not already there
RUN uv pip install --system "aismartbuddy[entra] @ git+https://github.com/meghuizen/aismartbuddy"
```

Or for the existing Dockerfile (which uses `uv pip install --system .`), append `[entra]`:

```dockerfile
RUN uv pip install --system ".[entra]"
```

Build and push:

```bash
ACR=$(az acr create -n acr$RANDOM -g $RG --sku Basic --query name -o tsv)
az acr login -n $ACR
docker build -t $ACR.azurecr.io/aismartbuddy:latest .
docker push $ACR.azurecr.io/aismartbuddy:latest
```

**Step 3 — Deploy to Container Apps with the OAuth env vars**

```bash
ENV="env-aismartbuddy"
az containerapp env create -n $ENV -g $RG -l $LOCATION

az containerapp create -n aismartbuddy -g $RG --environment $ENV \
    --image $ACR.azurecr.io/aismartbuddy:latest \
    --target-port 8000 --ingress external \
    --registry-server $ACR.azurecr.io \
    --command "aismartbuddy" \
    --args "--transport sse --host 0.0.0.0 --port 8000" \
    --env-vars \
        AISMARTBUDDY_ENTRA_TENANT=$TENANT_ID \
        AISMARTBUDDY_ENTRA_AUDIENCE=$APP_URI \
        AISMARTBUDDY_ENTRA_REQUIRED_SCOPE=mcp.invoke

# Get the public URL
FQDN=$(az containerapp show -n aismartbuddy -g $RG --query properties.configuration.ingress.fqdn -o tsv)
echo "https://$FQDN/sse"
```

Optional: pass `AISMARTBUDDY_ENTRA_RESOURCE_SERVER_URL=https://$FQDN` so the OAuth resource-server metadata advertises the public hostname (used by clients during dynamic discovery).

**Behavior at runtime:**
- Both env vars set + `[entra]` extra installed → server validates every Bearer token against your tenant.
- Both env vars set + extra NOT installed → server exits at startup with a clear "install aismartbuddy[entra]" error.
- Only one of the two env vars set → server logs a warning and runs **without** auth (treats partial config as not-configured). Set both or neither.
- Neither env var set → server runs without auth (current default — fine for stdio / single-user).

**Step 4 — Connect a client**

Acquire an access token for the scope:

```bash
TOKEN=$(az account get-access-token --resource $APP_URI --query accessToken -o tsv)
```

Then in Claude Code/Desktop config:

```json
{
  "mcpServers": {
    "aismartbuddy-prod": {
      "url": "https://<your-fqdn>/sse",
      "headers": {
        "Authorization": "Bearer <paste-token-here>"
      }
    }
  }
}
```

Inside Claude Code, the `client_id` you'll see in `aismartbuddy://sessions` resources will be your Entra `oid` — every session is now scoped per-principal automatically.

> **Note**: at the time of writing, the `streamable-http` transport is not wired in `__main__.py` (only `stdio` and `sse`). Streamable-HTTP is the modern recommendation for remote MCP and a small follow-up to add. Built-in Entra OAuth via `auth.py` works with SSE today.

---

## CLI options

```text
Usage: aismartbuddy [OPTIONS]

Options:
  --transport [stdio|sse]            Transport (default: stdio)
  --port INTEGER                     SSE port (default: 8000)
  --host TEXT                        SSE host (default: 127.0.0.1)
  --temp-dir TEXT                    Override temp directory
  --max-rows INTEGER                 Max rows per query result (default: 1000)
  --max-chars INTEGER                Max chars per response (default: 50000)
  --session-timeout INTEGER          Session idle timeout (default: 3600)
  --cursor-timeout INTEGER           Pagination cursor timeout (default: 300)
  --duckdb-threads INTEGER           DuckDB worker threads (0=auto)
  --duckdb-memory-limit TEXT         DuckDB memory limit (default: 256MB)
  --ladybug-buffer-size INTEGER      LadybugDB buffer pool bytes (default: 256MB)
  --ladybug-threads INTEGER          LadybugDB worker threads (0=auto)
  --default-user-id TEXT             Fallback user_id (default: "default")
  --default-project-id TEXT          Fallback project_id (default: "default")
```

Every option also reads from an `AISMARTBUDDY_*` environment variable (e.g. `AISMARTBUDDY_TRANSPORT=sse`). Useful for Docker / Container Apps configuration without rebuilding.

---

## Tools at a glance

| Group | Tools |
|---|---|
| **SQL (DuckDB)** | `sql_create_session`, `sql_query`, `sql_query_next`, `sql_import`, `sql_import_batch`, `sql_schema`, `sql_destroy_session` |
| **Graph (LadybugDB)** | `graph_create_session`, `graph_query`, `graph_query_next`, `graph_import`, `graph_schema`, `graph_destroy_session`, `graph_statistics`, `graph_neighbors`, `graph_find_connections`, `graph_analyze`, `graph_compare`, `graph_cross_reference`, `graph_knowledge_add`, `graph_knowledge_relate`, `graph_knowledge_infer`, `graph_knowledge_summary` |
| **Thinking** | `think_create_session`, `think_graph`, `think_graph_validate`, `think_graph_delegate`, `think_decide`, `think_model`, `think_debug`, `think_argue`, `think_collaborate`, `think_science`, `think_monitor`, `think_visualize`, `think_summarize`, `think_destroy_session`, `think_interfere`, `think_interfere_state` |
| **Holonic** | `holon_create`, `holon_update`, `holon_view`, `holon_analyze`, `holon_query` |
| **Scoring** | `score_rubric`, `score_evaluate`, `score_gate` |
| **YouTube** | `get_youtube_information` |
| **Meta** | `suggest_database` |

See `CLAUDE.md` for tool descriptions and usage patterns. The server also exposes 5 prompts (guides) and 2 resources (sessions listing).

---

## Token efficiency

CSV defaults for SQL/graph results — typically 2-3× fewer tokens than JSON. Transcripts use `[MM:SS] text` (auto-promotes to `[H:MM:SS]` for ≥1 hour videos). Pagination keeps responses bounded; cursor-based paging streams without re-running the query.

---

## License

MIT
