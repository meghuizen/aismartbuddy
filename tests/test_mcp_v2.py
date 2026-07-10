from __future__ import annotations

import importlib.metadata
from typing import Any, cast

import pytest
from mcp import Client
from mcp.server.auth.middleware.auth_context import (
    auth_context_var,
)
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver import MCPServer
from mcp_types import TextContent

from aismartbuddy.identity import resolve_identity
from aismartbuddy.server import mcp


def test_mcp_v2_is_exactly_pinned_and_server_uses_new_class():
    assert importlib.metadata.version("mcp") == "2.0.0b1"
    assert isinstance(mcp, MCPServer)


def test_bearer_identity_overrides_request_metadata_and_parameters():
    class FakeContext:
        client_id = "untrusted-request-metadata"

    access_token = AccessToken(
        token="token",
        client_id="entra-object-id",
        scopes=["mcp.invoke"],
    )
    token = auth_context_var.set(AuthenticatedUser(access_token))
    try:
        user_id, project_id = resolve_identity(
            ctx=cast(Any, FakeContext()),
            user_id="spoofed-parameter",
            project_id="project",
        )
    finally:
        auth_context_var.reset(token)

    assert user_id == "entra-object-id"
    assert project_id == "project"


@pytest.mark.anyio
async def test_v2_client_negotiates_modern_protocol_and_calls_tool():
    async with Client(mcp, mode="auto") as client:
        tools = await client.list_tools()
        prompts = await client.list_prompts()
        resource_templates = await client.list_resource_templates()
        guide = await client.get_prompt("aismartbuddy-guide")
        sessions = await client.read_resource(
            "aismartbuddy://sessions/default/default"
        )
        names = {tool.name for tool in tools.tools}
        result = await client.call_tool(
            "suggest_database",
            {"use_case": "Aggregate a CSV by month"},
        )

        assert client.protocol_version == "2026-07-28"
        assert "web_crawl" in names
        assert all(tool.input_schema.get("type") == "object" for tool in tools.tools)
        assert any(prompt.name == "aismartbuddy-guide" for prompt in prompts.prompts)
        assert any(
            template.uri_template == "aismartbuddy://sessions/{user_id}/{project_id}"
            for template in resource_templates.resource_templates
        )
        assert guide.messages
        assert sessions.contents
        assert result.is_error is False
        assert result.content
        assert isinstance(result.content[0], TextContent)
        assert "SQL database" in result.content[0].text
