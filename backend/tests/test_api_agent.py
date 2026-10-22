import json

from app.llm.scripted import ScriptedProvider


def test_status_reports_the_provider(client):
    body = client.get("/api/agent/status").json()
    assert body["agent_name"] == "Subh AI"
    assert "configured" in body
    assert body["max_iterations"] >= 1


def test_run_without_a_key_explains_itself(client):
    """With no provider configured the agent reports it instead of erroring."""
    from app.core import runtime
    from app.llm.scripted import UnconfiguredProvider

    runtime.set_provider(UnconfiguredProvider())
    body = client.post("/api/agent/run", json={"message": "hello", "session_id": "t1"}).json()
    assert body["status"] == "llm_not_configured"


def test_natural_language_request_runs_a_tool(client, scripted):
    scripted(
        [
            ScriptedProvider.tool("filesystem", {"operation": "list", "path": "."}),
            ScriptedProvider.text("The workspace is listed above."),
        ]
    )
    body = client.post(
        "/api/agent/run",
        json={"message": "what is in my workspace?", "session_id": "t2", "plan": False},
    ).json()

    assert body["status"] == "completed"
    assert body["answer"] == "The workspace is listed above."
    assert body["results"][0]["tool"] == "filesystem"


def test_plan_is_returned_alongside_the_answer(client, scripted):
    plan = {
        "understanding": "List the workspace.",
        "steps": [{"description": "List files", "tool": "filesystem", "requires_approval": False}],
        "clarification_needed": None,
    }
    scripted(
        [
            ScriptedProvider.text(json.dumps(plan)),  # planning call
            ScriptedProvider.tool("filesystem", {"operation": "list", "path": "."}),
            ScriptedProvider.text("Done."),
        ]
    )
    body = client.post("/api/agent/run", json={"message": "list my files", "session_id": "t3"}).json()

    assert body["plan"]["understanding"] == "List the workspace."
    assert body["plan"]["steps"][0]["tool"] == "filesystem"
    assert body["status"] == "completed"


def test_clarification_short_circuits_before_any_tool_runs(client, scripted):
    vague = {"understanding": "Unclear", "steps": [], "clarification_needed": "Which file?"}
    provider = scripted([ScriptedProvider.text(json.dumps(vague))])
    body = client.post("/api/agent/run", json={"message": "fix it", "session_id": "t4"}).json()

    assert body["status"] == "clarification_needed"
    assert body["question"] == "Which file?"
    # Only the planning call was made - the executor never ran.
    assert len(provider.calls) == 1


def test_confirmation_flow_over_http(client, scripted):
    scripted(
        [
            ScriptedProvider.tool("terminal", {"operation": "execute", "command": "python --version"}),
            ScriptedProvider.text("Python is installed."),
        ]
    )
    client.post("/api/permissions/grant", json={"permission": "terminal.execute"})

    suspended = client.post(
        "/api/agent/run",
        json={"message": "what python version do I have?", "session_id": "t5", "plan": False},
    ).json()
    assert suspended["status"] == "awaiting_confirmation"
    token = suspended["confirmation_token"]

    pending = client.get("/api/agent/pending", params={"session_id": "t5"}).json()
    assert pending["confirmation_token"] == token

    # Resuming before approval must not run the command.
    early = client.post("/api/agent/resume", json={"session_id": "t5"}).json()
    assert early["status"] == "awaiting_confirmation"

    client.post("/api/confirmations/approve", json={"token": token})
    done = client.post("/api/agent/resume", json={"session_id": "t5"}).json()

    assert done["status"] == "completed"
    assert done["results"][-1]["result"]["exit_code"] == 0


def test_resume_with_nothing_pending(client, scripted):
    scripted([ScriptedProvider.text("ok")])
    body = client.post("/api/agent/resume", json={"session_id": "t6"}).json()
    assert body["status"] == "nothing_to_resume"


def test_session_history_persists_across_requests(client, scripted):
    provider = scripted([ScriptedProvider.text("first"), ScriptedProvider.text("second")])
    client.post("/api/agent/run", json={"message": "one", "session_id": "t7", "plan": False})
    client.post("/api/agent/run", json={"message": "two", "session_id": "t7", "plan": False})

    # The second request must carry the first exchange.
    second_messages = provider.calls[1]["messages"]
    assert len(second_messages) >= 3
    assert second_messages[0]["content"] == "one"


def test_transcript_is_available_for_a_chat_ui(client, scripted):
    scripted([ScriptedProvider.text("Hello there.")])
    client.post("/api/agent/run", json={"message": "hi", "session_id": "t8", "plan": False})

    messages = client.get("/api/agent/transcript", params={"session_id": "t8"}).json()["messages"]
    assert [(m["role"], m["text"]) for m in messages] == [("user", "hi"), ("assistant", "Hello there.")]


def test_sessions_and_reset(client, scripted):
    scripted([ScriptedProvider.text("hi")])
    client.post("/api/agent/run", json={"message": "one", "session_id": "t9", "plan": False})

    sessions = client.get("/api/agent/sessions").json()["sessions"]
    assert any(s["session_id"] == "t9" for s in sessions)

    assert client.post("/api/agent/reset", json={"session_id": "t9"}).json()["status"] == "reset"
    assert client.post("/api/agent/reset", json={"session_id": "t9"}).json()["status"] == "no_such_session"


def test_empty_message_is_rejected(client):
    assert client.post("/api/agent/run", json={"message": "", "session_id": "tx"}).status_code == 422
