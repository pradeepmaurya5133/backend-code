"""Encrypted credential store.

Values go in and are never read back out over the API - `reveal()` exists for
the tool layer to inject a credential into an outbound request, so a key can be
used without ever entering the model's context or an API response.
"""

from app.db.repository import SecretRepository
from app.security.crypto import Crypto


class SecretService:
    def __init__(self, crypto: Crypto, repository: SecretRepository = None):
        self.crypto = crypto
        self.repository = repository if repository is not None else SecretRepository()

    async def put(self, name: str, value: str):
        await self.repository.put(name, self.crypto.encrypt(value))

    async def reveal(self, name: str) -> str | None:
        """Decrypt for server-side use only. Never return this to a client."""
        ciphertext = await self.repository.get(name)
        if ciphertext is None:
            return None
        return self.crypto.decrypt(ciphertext)

    async def names(self) -> list[str]:
        return await self.repository.names()

    async def delete(self, name: str) -> bool:
        return await self.repository.delete(name)

    async def exists(self, name: str) -> bool:
        return await self.repository.get(name) is not None
