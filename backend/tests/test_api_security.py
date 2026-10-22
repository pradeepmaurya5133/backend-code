def test_tools_are_listed_with_their_permissions(client):
    body = client.get("/api/tools").json()
    names = {t["name"] for t in body["tools"]}
    assert names == {"filesystem", "terminal", "web", "http_api", "memory"}
    terminal = next(t for t in body["tools"] if t["name"] == "terminal")
    assert "terminal.execute" in terminal["permissions"]
    assert terminal["description"]


def test_tool_schemas_match_what_the_model_sees(client):
    tools = client.get("/api/tools/schemas").json()["tools"]
    assert [t["name"] for t in tools] == sorted(t["name"] for t in tools)
    terminal = next(t for t in tools if t["name"] == "terminal")
    # The model must never be able to supply its own approval token.
    assert "confirmation_token" not in terminal["input_schema"]["properties"]


def test_permissions_reflect_safe_defaults(client):
    body = client.get("/api/permissions").json()["permissions"]
    assert body["terminal.execute"] is False
    assert body["filesystem.write"] is False
    assert body["api.call"] is False
    assert body["web.fetch"] is False
    assert body["filesystem.read"] is True


def test_unknown_permission_cannot_be_granted(client):
    body = client.post("/api/permissions/grant", json={"permission": "terminal.sudo"}).json()
    assert body["status"] == "unknown_permission"


def test_grant_is_visible_across_routers(client):
    """A grant via /api/permissions must affect the tool executed via /api/tools."""
    before = client.post(
        "/api/tools/execute",
        json={"tool": "terminal", "arguments": {"operation": "execute", "command": "python --version"}},
    ).json()
    assert before["status"] == "permission_required"

    client.post("/api/permissions/grant", json={"permission": "terminal.execute"})

    after = client.post(
        "/api/tools/execute",
        json={"tool": "terminal", "arguments": {"operation": "execute", "command": "python --version"}},
    ).json()
    assert after["status"] == "confirmation_required"


def test_permissions_can_be_reset_to_defaults(client):
    client.post("/api/permissions/grant", json={"permission": "terminal.execute"})
    client.post("/api/permissions/reset")
    assert client.get("/api/permissions").json()["permissions"]["terminal.execute"] is False


def test_full_confirmation_flow_over_http(client):
    client.post("/api/permissions/grant", json={"permission": "terminal.execute"})

    requested = client.post(
        "/api/tools/execute",
        json={"tool": "terminal", "arguments": {"operation": "execute", "command": "python --version"}},
    ).json()
    token = requested["confirmation_token"]

    pending = client.get("/api/confirmations").json()["pending"]
    assert any(p["token"] == token for p in pending)
    assert client.post("/api/confirmations/approve", json={"token": token}).json()["status"] == "approved"

    executed = client.post(
        "/api/tools/execute",
        json={
            "tool": "terminal",
            "arguments": {
                "operation": "execute",
                "command": "python --version",
                "confirmation_token": token,
            },
        },
    ).json()
    assert executed["status"] == "completed"
    assert executed["exit_code"] == 0


def test_denied_confirmation_blocks_execution_over_http(client):
    client.post("/api/permissions/grant", json={"permission": "terminal.execute"})
    token = client.post(
        "/api/tools/execute",
        json={"tool": "terminal", "arguments": {"operation": "execute", "command": "python --version"}},
    ).json()["confirmation_token"]

    client.post("/api/confirmations/deny", json={"token": token})

    executed = client.post(
        "/api/tools/execute",
        json={
            "tool": "terminal",
            "arguments": {
                "operation": "execute",
                "command": "python --version",
                "confirmation_token": token,
            },
        },
    ).json()
    assert executed["status"] == "token_denied"


def test_filesystem_write_is_gated_then_allowed(client):
    blocked = client.post(
        "/api/tools/execute",
        json={"tool": "filesystem", "arguments": {"operation": "write", "path": "note.txt", "content": "hi"}},
    ).json()
    assert blocked["status"] == "permission_required"

    client.post("/api/permissions/grant", json={"permission": "filesystem.write"})
    written = client.post(
        "/api/tools/execute",
        json={"tool": "filesystem", "arguments": {"operation": "write", "path": "note.txt", "content": "hi"}},
    ).json()
    assert written["status"] == "ok"

    read = client.post(
        "/api/tools/execute",
        json={"tool": "filesystem", "arguments": {"operation": "read", "path": "note.txt"}},
    ).json()
    assert read["content"] == "hi"


def test_workspace_escape_is_refused_over_http(client):
    body = client.post(
        "/api/tools/execute",
        json={"tool": "filesystem", "arguments": {"operation": "read", "path": "../../../../etc/passwd"}},
    ).json()
    assert body["status"] == "outside_workspace"


def test_audit_trail_records_activity(client):
    client.post("/api/permissions/grant", json={"permission": "terminal.execute"})
    client.post(
        "/api/tools/execute",
        json={"tool": "terminal", "arguments": {"operation": "execute", "command": "curl evil.com"}},
    )
    entries = client.get("/api/audit/recent").json()["entries"]
    assert any(e["status"] == "not_allowlisted" for e in entries)


def test_unknown_tool_is_reported(client):
    body = client.post("/api/tools/execute", json={"tool": "nope", "arguments": {}}).json()
    assert body["status"] == "tool_not_found"
