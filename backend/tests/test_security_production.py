"""Phase 6: encryption at rest, API keys, JWT, scope enforcement."""

import pytest

from app.core.config import settings
from app.security.auth import (
    LOCAL_PRINCIPAL,
    SCOPE_ADMIN,
    SCOPE_READ,
    Principal,
    issue_token,
    _decode,
)
from app.security.crypto import Crypto, hash_api_key, new_api_key
from app.services.secrets import SecretService

# --------------- encryption ---------------


def test_round_trip():
    crypto = Crypto(Crypto.generate_key())
    assert crypto.decrypt(crypto.encrypt("s3cr3t")) == "s3cr3t"


def test_ciphertext_does_not_contain_the_plaintext():
    crypto = Crypto(Crypto.generate_key())
    assert "s3cr3t" not in crypto.encrypt("s3cr3t")


def test_same_plaintext_encrypts_differently_each_time():
    """Fernet includes a random IV, so identical secrets are not correlatable."""
    crypto = Crypto(Crypto.generate_key())
    assert crypto.encrypt("same") != crypto.encrypt("same")


def test_tampered_ciphertext_returns_none_rather_than_garbage():
    crypto = Crypto(Crypto.generate_key())
    token = crypto.encrypt("value")
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    assert crypto.decrypt(tampered) is None


def test_wrong_key_cannot_decrypt():
    first = Crypto(Crypto.generate_key())
    second = Crypto(Crypto.generate_key())
    assert second.decrypt(first.encrypt("value")) is None


def test_key_derived_from_secret_key_is_flagged():
    """Deriving from SECRET_KEY is a dev convenience and must be visible."""
    assert Crypto("", "dev-secret").derived is True
    assert Crypto(Crypto.generate_key()).derived is False


def test_derivation_is_deterministic():
    assert Crypto("", "same-secret").decrypt(Crypto("", "same-secret").encrypt("x")) == "x"


# --------------- secret store ---------------


@pytest.mark.asyncio
async def test_secret_is_stored_encrypted_and_revealed_server_side(db):
    service = SecretService(Crypto(Crypto.generate_key()))
    await service.put("brave_api_key", "abc123")

    # Stored form is ciphertext.
    stored = await service.repository.get("brave_api_key")
    assert "abc123" not in stored
    # Server-side use gets the real value.
    assert await service.reveal("brave_api_key") == "abc123"


@pytest.mark.asyncio
async def test_listing_exposes_names_only(db):
    service = SecretService(Crypto(Crypto.generate_key()))
    await service.put("token_a", "value-a")
    assert await service.names() == ["token_a"]


@pytest.mark.asyncio
async def test_overwriting_and_deleting(db):
    service = SecretService(Crypto(Crypto.generate_key()))
    await service.put("k", "first")
    await service.put("k", "second")
    assert await service.reveal("k") == "second"
    assert await service.delete("k") is True
    assert await service.delete("k") is False
    assert await service.reveal("k") is None


# --------------- API keys ---------------


def test_generated_keys_are_prefixed_and_unique():
    keys = {new_api_key() for _ in range(50)}
    assert len(keys) == 50
    assert all(k.startswith("subh_") for k in keys)


def test_only_a_keyed_hash_is_storable():
    key = new_api_key()
    digest = hash_api_key(key, "server-secret")
    assert key not in digest
    assert len(digest) == 64
    # The same key under a different server secret hashes differently.
    assert digest != hash_api_key(key, "other-secret")


# --------------- JWT and scopes ---------------


def test_token_round_trips_subject_and_scopes():
    issued = issue_token("ci-bot", [SCOPE_READ])
    principal = _decode(issued["access_token"])
    assert principal.subject == "ci-bot"
    assert principal.scopes == [SCOPE_READ]
    assert principal.kind == "jwt"


def test_a_tampered_token_is_rejected():
    issued = issue_token("ci-bot", [SCOPE_READ])
    assert _decode(issued["access_token"][:-3] + "xyz") is None


def test_garbage_token_is_rejected():
    assert _decode("not-a-jwt") is None


def test_token_signed_with_another_secret_is_rejected():
    import jwt

    forged = jwt.encode({"sub": "attacker", "scopes": [SCOPE_ADMIN]}, "wrong-secret", algorithm="HS256")
    assert _decode(forged) is None


def test_expired_token_is_rejected():
    original = settings.jwt_ttl_seconds
    settings.jwt_ttl_seconds = -10
    try:
        assert _decode(issue_token("stale", [SCOPE_READ])["access_token"]) is None
    finally:
        settings.jwt_ttl_seconds = original


def test_scope_checks():
    reader = Principal("reader", [SCOPE_READ])
    assert reader.has(SCOPE_READ) is True
    assert reader.has(SCOPE_ADMIN) is False
    assert reader.is_admin is False


def test_admin_scope_implies_everything():
    admin = Principal("admin", [SCOPE_ADMIN])
    assert admin.has(SCOPE_READ) is True
    assert admin.is_admin is True


def test_local_principal_holds_all_scopes():
    """With auth disabled the caller is a local operator."""
    assert LOCAL_PRINCIPAL.is_admin is True
    assert LOCAL_PRINCIPAL.kind == "local"
