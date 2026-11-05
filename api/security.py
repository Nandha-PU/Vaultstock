import hashlib
import hmac
import os

PBKDF2_ITERATIONS = 150_000
_DUMMY_HASH: str | None = None

def hash_password(password: str) -> str:
    """Hashes a password using salted PBKDF2-HMAC-SHA256."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    """Verifies a plaintext password against a stored PBKDF2 hash in constant time."""
    try:
        algo, iterations, salt_hex, dk_hex = stored_hash.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iter_count = int(iterations)
        if not (10_000 <= iter_count <= 1_000_000):
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iter_count
        )
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False

def dummy_verify(password: str) -> None:
    """Equalizes response time when a username does not exist."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("timing-equalization-placeholder")
    verify_password(password, _DUMMY_HASH)
