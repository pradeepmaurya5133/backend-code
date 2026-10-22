"""Encryption at rest and credential hashing (Phase 6).

Secrets stored by operators (API keys for third-party services) are encrypted
with Fernet - AES-128-CBC plus an HMAC, so a tampered ciphertext fails to
decrypt rather than decrypting to garbage.

The data key comes from DATA_ENCRYPTION_KEY. When unset it is derived from
SECRET_KEY so development works out of the box; that derivation is flagged as
insecure because rotating SECRET_KEY would then silently orphan every secret.
"""

import base64
import hashlib
import hmac
import secrets as secrets_module

from cryptography.fernet import Fernet, InvalidToken

PBKDF2_ROUNDS = 390_000
API_KEY_BYTES = 32


def derive_key(secret_key: str) -> bytes:
    """Turn an arbitrary passphrase into a valid 32-byte Fernet key."""
    digest = hashlib.pbkdf2_hmac("sha256", secret_key.encode(), b"subh-ai-data-key", PBKDF2_ROUNDS)
    return base64.urlsafe_b64encode(digest)


class Crypto:
    def __init__(self, data_key: str = "", secret_key: str = "change-me"):
        if data_key:
            self.key = data_key.encode() if isinstance(data_key, str) else data_key
            self.derived = False
        else:
            self.key = derive_key(secret_key)
            self.derived = True
        self._fernet = Fernet(self.key)

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str | None:
        """Returns None on a tampered or wrong-key ciphertext rather than raising."""
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, ValueError):
            return None


def new_api_key() -> str:
    """A fresh operator key. Shown once; only its hash is stored."""
    return "subh_" + secrets_module.token_urlsafe(API_KEY_BYTES)


def hash_api_key(key: str, secret_key: str) -> str:
    """Keyed hash, so a leaked database alone cannot be brute-forced offline."""
    return hmac.new(secret_key.encode(), key.encode(), hashlib.sha256).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
