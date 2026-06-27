"""
crypto_utils.py — Fernet encryption, keyring integration, hash generation.

Clean Architecture — Core Layer.
No external dependencies on infrastructure or domain.
"""

import hashlib
import base64
import os
import logging
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

DEFAULT_KEY_FILE = Path("data/key.key")
SALT_FILE = Path("data/salt.bin")


class CryptoManager:
    """Manages encryption/decryption using Fernet (AES-128-CBC) with PBKDF2 key derivation.

    Supports:
    - File-based key storage
    - OS keyring integration (optional)
    - SHA-256 hashing for integrity verification
    """

    def __init__(self, key_file: Optional[Path] = None, use_keyring: bool = False):
        self._key_file = key_file or DEFAULT_KEY_FILE
        self._use_keyring = use_keyring
        self._cipher: Optional[Fernet] = None
        self._init_cipher()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string. Returns base64-encoded ciphertext."""
        if not self._cipher:
            raise RuntimeError("Cipher not initialized.")
        return self._cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a base64-encoded ciphertext string."""
        if not self._cipher:
            raise RuntimeError("Cipher not initialized.")
        return self._cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")

    @staticmethod
    def hash_content(data: bytes) -> str:
        """Return SHA-256 hex digest of *data*."""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def hash_file(path: Path) -> str:
        """Return SHA-256 hex digest of file contents (stream-friendly)."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def mask_email(email: str) -> str:
        """Mask an email address for logging: u***@domain.com"""
        if "@" not in email:
            return email
        local, domain = email.split("@", 1)
        if len(local) <= 2:
            masked = local[0] + "***"
        else:
            masked = local[0] + "***" + local[-1]
        return f"{masked}@{domain}"

    @staticmethod
    def mask_password(password: str) -> str:
        """Return a masked version of a password: ****"""
        return "****" if password else ""

    # ------------------------------------------------------------------
    # Key management
    # ------------------------------------------------------------------

    def _init_cipher(self) -> None:
        if self._use_keyring:
            # TODO: OS keyring integration
            # key = keyring.get_password("mail_archive", "fernet_key")
            logger.warning("Keyring support not yet implemented. Falling back to file.")
            self._cipher = self._load_or_create_key()
        else:
            self._cipher = self._load_or_create_key()

    def _load_or_create_key(self) -> Fernet:
        if self._key_file.exists():
            key = self._key_file.read_bytes()
            logger.info("Encryption key loaded from %s", self._key_file)
        else:
            key = Fernet.generate_key()
            self._key_file.parent.mkdir(parents=True, exist_ok=True)
            # TODO: Store salt in separate file for PBKDF2
            self._key_file.write_bytes(key)
            logger.info("New encryption key generated and saved to %s", self._key_file)
        return Fernet(key)

    def rotate_key(self) -> None:
        """Generate a new key and re-encrypt all stored secrets.

        TODO: Implement full key rotation — read all encrypted fields from DB,
        decrypt with old key, encrypt with new key, write back.
        """
        raise NotImplementedError("Key rotation is not yet implemented.")


# ------------------------------------------------------------------
# Convenience helpers
# ------------------------------------------------------------------

def sha256(data: bytes) -> str:
    return CryptoManager.hash_content(data)


def hash_email(email: str) -> str:
    """Return SHA-256 hash of an email for anonymized logging."""
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]
