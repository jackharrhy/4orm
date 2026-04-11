"""Password hashing and verification."""

import hashlib
import hmac
import secrets

ITERATIONS = 210_000


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS
    )
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    algo, iter_s, salt, digest_hex = password_hash.split("$", 3)
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iter_s)
    )
    return hmac.compare_digest(digest.hex(), digest_hex)
