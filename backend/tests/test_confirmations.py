from app.security.confirmations import APPROVED, DENIED, ConfirmationStore


def test_request_starts_pending():
    store = ConfirmationStore()
    record = store.request("terminal", "execute", {"command": "python --version"})
    assert record.status == "pending"
    assert len(store.pending()) == 1


def test_approve_then_claim_succeeds_once():
    store = ConfirmationStore()
    token = store.request("terminal", "execute", {"command": "python --version"}).token
    assert store.approve(token)["status"] == APPROVED

    record, error = store.claim(token)
    assert error is None
    assert record.arguments["command"] == "python --version"

    # An approval must not be replayable.
    record, error = store.claim(token)
    assert record is None
    assert error["status"] == "token_consumed"


def test_claim_without_approval_is_refused():
    store = ConfirmationStore()
    token = store.request("terminal", "execute", {"command": "python --version"}).token
    record, error = store.claim(token)
    assert record is None
    assert error["status"] == "awaiting_confirmation"


def test_denied_token_cannot_be_claimed():
    store = ConfirmationStore()
    token = store.request("terminal", "execute", {"command": "python --version"}).token
    assert store.deny(token)["status"] == DENIED
    record, error = store.claim(token)
    assert record is None
    assert error["status"] == "token_denied"


def test_unknown_token_is_refused():
    store = ConfirmationStore()
    record, error = store.claim("not-a-real-token")
    assert record is None
    assert error["status"] == "unknown_token"


def test_expired_token_cannot_be_claimed():
    store = ConfirmationStore(ttl_seconds=-1)
    token = store.request("terminal", "execute", {"command": "python --version"}).token
    store.approve(token)
    record, error = store.claim(token)
    assert record is None
    assert error["status"] == "expired"


def test_expired_request_is_not_listed_as_pending():
    store = ConfirmationStore(ttl_seconds=-1)
    store.request("terminal", "execute", {"command": "python --version"})
    assert store.pending() == []


def test_approving_twice_reports_already_resolved():
    store = ConfirmationStore()
    token = store.request("terminal", "execute", {"command": "python --version"}).token
    store.approve(token)
    assert store.approve(token)["status"] == "already_resolved"
