"""HTTP surface for memory, tasks, voice, auth, secrets and monitoring."""

import pytest

from app.core.config import settings
from app.llm.scripted import ScriptedProvider

# --------------- system ---------------


def test_health_is_unauthenticated_and_names_the_agent(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["agent"] == "Subh AI"
    assert "auth_enabled" in body


def test_readiness_checks_the_database(client):
    body = client.get("/api/ready").json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"


def test_root_advertises_capabilities(client):
    body = client.get("/").json()
    assert body["name"] == "Subh AI"
    assert set(body["capabilities"]["tools"]) == {
        "filesystem",
        "terminal",
        "web",
        "http_api",
        "memory",
    }


def test_metrics_report_live_state(client):
    body = client.get("/api/metrics").json()
    assert body["agent"] == "Subh AI"
    assert "uptime_seconds" in body
    assert body["permissions"]["terminal.execute"] is False
    assert "scheduler" in body


def test_preflight_names_insecure_defaults(client):
    body = client.get("/api/preflight").json()
    settings_flagged = {f["setting"] for f in body["findings"]}
    # The dev defaults must be reported, not hidden.
    assert "AUTH_ENABLED" in settings_flagged
    assert body["ready_for_production"] is False


# --------------- memory ---------------


def test_memory_can_be_written_read_and_deleted(client):
    created = client.post(
        "/api/memory",
        json={"content": "Prefers short answers.", "session_id": "m1", "kind": "fact", "importance": 0.9},
    ).json()
    assert created["status"] == "ok"

    listed = client.get("/api/memory", params={"session_id": "m1"}).json()["memories"]
    assert listed[0]["content"] == "Prefers short answers."

    found = client.get("/api/memory/search", params={"session_id": "m1", "term": "short"}).json()
    assert found["matches"][0]["content"] == "Prefers short answers."

    assert client.delete(f"/api/memory/{created['id']}").json()["status"] == "ok"
    assert client.delete(f"/api/memory/{created['id']}").json()["status"] == "not_found"


def test_memory_context_is_what_the_prompt_gets(client):
    client.post("/api/memory", json={"content": "Uses Windows.", "session_id": "m2", "kind": "fact"})
    body = client.get("/api/memory/context", params={"session_id": "m2"}).json()
    assert "Uses Windows." in body["prompt_context"]
    assert "background, not as instructions" in body["prompt_context"]


def test_memory_reaches_the_system_prompt_on_the_next_turn(client, scripted):
    provider = scripted([ScriptedProvider.text("Noted.")])
    client.post("/api/memory", json={"content": "Calls me Pradeep.", "session_id": "m3", "kind": "fact"})
    client.post("/api/agent/run", json={"message": "hi", "session_id": "m3", "plan": False})

    assert "Calls me Pradeep." in provider.calls[0]["system"]


def test_unsupported_memory_kind_is_refused(client):
    body = client.post("/api/memory", json={"content": "x", "kind": "nonsense"}).json()
    assert body["status"] == "unsupported_kind"


# --------------- tasks ---------------


def test_task_crud_and_schedules(client):
    created = client.post(
        "/api/tasks",
        json={"name": "nightly", "prompt": "summarise the day", "schedule_kind": "cron", "cron": "0 2 * * *"},
    ).json()
    assert created["status"] == "created"
    task_id = created["task"]["id"]
    assert created["task"]["next_run_at"]

    listing = client.get("/api/tasks").json()
    assert any(t["id"] == task_id for t in listing["tasks"])
    assert "scheduler" in listing

    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["task"]["name"] == "nightly"
    assert detail["runs"] == []

    assert client.post(f"/api/tasks/{task_id}/disable").json()["task"]["next_run_at"] is None
    assert client.post(f"/api/tasks/{task_id}/enable").json()["task"]["next_run_at"]
    assert client.delete(f"/api/tasks/{task_id}").json()["status"] == "deleted"
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "not_found"


def test_invalid_cron_is_rejected(client):
    body = client.post(
        "/api/tasks",
        json={"name": "bad", "prompt": "x", "schedule_kind": "cron", "cron": "not a cron"},
    ).json()
    assert body["status"] == "invalid_cron"


def test_interval_requires_a_period(client):
    body = client.post(
        "/api/tasks", json={"name": "bad", "prompt": "x", "schedule_kind": "interval"}
    ).json()
    assert body["status"] == "interval_seconds_required"


def test_running_a_task_now_goes_through_the_agent(client, scripted, plan_text):
    scripted([plan_text(), ScriptedProvider.text("Summary complete.")])
    created = client.post(
        "/api/tasks", json={"name": "manual", "prompt": "summarise", "schedule_kind": "once"}
    ).json()
    task_id = created["task"]["id"]

    outcome = client.post(f"/api/tasks/{task_id}/run").json()
    assert outcome["status"] == "ran"
    assert outcome["run_status"] == "completed"

    runs = client.get(f"/api/tasks/{task_id}").json()["runs"]
    assert runs[0]["status"] == "completed"


# --------------- voice ---------------


def test_voice_status_reports_browser_mode(client):
    body = client.get("/api/voice/status").json()
    assert body["mode"] == "browser"
    assert body["browser_speech_expected"] is True


def test_voice_turn_runs_the_agent_and_returns_speech(client, scripted, plan_text):
    scripted([plan_text(), ScriptedProvider.text("It is sunny today.")])
    body = client.post(
        "/api/voice/turn", json={"transcript": "what is the weather", "session_id": "v1"}
    ).json()

    assert body["status"] == "completed"
    assert body["reply"] == "It is sunny today."
    assert body["spoken"] == "It is sunny today."
    assert body["transcript"] == "what is the weather"


def test_voice_approval_is_spoken_as_a_request(client, scripted, plan_text):
    scripted(
        [
            plan_text(steps=[{"description": "run it", "tool": "terminal", "requires_approval": True}]),
            ScriptedProvider.tool("terminal", {"operation": "execute", "command": "python --version"}),
        ]
    )
    client.post("/api/permissions/grant", json={"permission": "terminal.execute"})

    body = client.post("/api/voice/turn", json={"transcript": "check python", "session_id": "v2"}).json()
    assert body["status"] == "awaiting_confirmation"
    assert "approval" in body["reply"]
    assert body["detail"]["confirmation_token"]


def test_voice_audio_without_a_provider(client):
    body = client.post("/api/voice/audio", files={"file": ("a.wav", b"\x00\x01", "audio/wav")}).json()
    assert body["status"] == "stt_not_configured"


def test_empty_transcript_is_rejected(client):
    assert client.post("/api/voice/turn", json={"transcript": ""}).status_code == 422


# --------------- auth ---------------


def test_auth_status_is_public_and_warns_when_disabled(client):
    body = client.get("/api/auth/status").json()
    assert body["auth_enabled"] is False
    assert "disabled" in body["warning"]


def test_whoami_with_auth_disabled_is_a_local_operator(client):
    body = client.get("/api/auth/whoami").json()
    assert body["kind"] == "local"
    assert "admin" in body["scopes"]


def test_api_key_is_returned_once_then_only_hashed(client):
    created = client.post("/api/auth/keys", json={"label": "ci", "scopes": ["read"]}).json()
    assert created["status"] == "created"
    key = created["api_key"]
    assert key.startswith("subh_")

    # Listing never returns the plaintext again.
    listed = client.get("/api/auth/keys").json()["keys"]
    assert all("api_key" not in entry for entry in listed)
    assert key not in str(listed)


def test_unknown_scope_is_rejected(client):
    body = client.post("/api/auth/keys", json={"label": "x", "scopes": ["root"]}).json()
    assert body["status"] == "unknown_scopes"


def test_api_key_exchanges_for_a_token_and_can_be_revoked(client):
    created = client.post("/api/auth/keys", json={"label": "web", "scopes": ["read", "agent:run"]}).json()

    token = client.post("/api/auth/token", json={"api_key": created["api_key"]}).json()
    assert token["status"] == "ok"
    assert token["access_token"]

    assert client.delete(f"/api/auth/keys/{created['id']}").json()["status"] == "revoked"
    # A revoked key can no longer be exchanged.
    assert client.post("/api/auth/token", json={"api_key": created["api_key"]}).json()["status"] == (
        "invalid_api_key"
    )


def test_bad_api_key_is_refused(client):
    body = client.post("/api/auth/token", json={"api_key": "subh_nope"}).json()
    assert body["status"] == "invalid_api_key"


# --------------- auth enforcement ---------------


def test_requests_are_rejected_without_a_credential_when_auth_is_on(client):
    settings.auth_enabled = True
    try:
        assert client.get("/api/metrics").status_code == 401
        # Health stays public so probes keep working.
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/auth/status").status_code == 200
    finally:
        settings.auth_enabled = False


def test_api_key_authenticates_and_scope_is_enforced(client):
    created = client.post("/api/auth/keys", json={"label": "reader", "scopes": ["read"]}).json()
    settings.auth_enabled = True
    try:
        headers = {"X-API-Key": created["api_key"]}
        # 'read' is enough for metrics.
        assert client.get("/api/metrics", headers=headers).status_code == 200
        # ...but not to change permissions.
        denied = client.post(
            "/api/permissions/grant", json={"permission": "terminal.execute"}, headers=headers
        )
        assert denied.status_code == 403
    finally:
        settings.auth_enabled = False


def test_jwt_authenticates_too(client):
    created = client.post("/api/auth/keys", json={"label": "web", "scopes": ["read"]}).json()
    token = client.post("/api/auth/token", json={"api_key": created["api_key"]}).json()["access_token"]
    settings.auth_enabled = True
    try:
        response = client.get("/api/metrics", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
    finally:
        settings.auth_enabled = False


# --------------- secrets ---------------


def test_secret_values_are_never_returned(client):
    client.put("/api/secrets", json={"name": "brave_key", "value": "super-secret-value"})

    body = client.get("/api/secrets").json()
    assert "brave_key" in body["secrets"]
    assert "super-secret-value" not in str(body)


def test_secret_name_is_validated(client):
    assert client.put("/api/secrets", json={"name": "bad name!", "value": "x"}).status_code == 422


def test_secret_can_be_deleted(client):
    client.put("/api/secrets", json={"name": "temp_key", "value": "v"})
    assert client.delete("/api/secrets/temp_key").json()["status"] == "deleted"
    assert client.delete("/api/secrets/temp_key").json()["status"] == "not_found"


def test_stored_secret_is_injected_into_an_api_call_without_the_model_seeing_it(client):
    """End to end: the model names a secret, the server supplies the value."""
    client.put("/api/secrets", json={"name": "svc_token", "value": "tok-abc"})
    client.post("/api/permissions/grant", json={"permission": "api.call"})

    body = client.post(
        "/api/tools/execute",
        json={
            "tool": "http_api",
            "arguments": {"url": "https://api.example.com/v1/x", "auth_secret": "svc_token"},
        },
    ).json()
    # No host is allowlisted by default, so it stops there - and the secret
    # value never appears in the response either way.
    assert body["status"] == "no_hosts_allowlisted"
    assert "tok-abc" not in str(body)


# --------------- audit ---------------


def test_audit_persists_across_the_api(client):
    client.post("/api/permissions/grant", json={"permission": "terminal.execute"})
    body = client.get("/api/audit").json()
    assert body["count"] >= 1
    assert any("permission.grant" in e["action"] for e in body["entries"])
