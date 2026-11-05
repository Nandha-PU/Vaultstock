import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

DEMO_MODE = os.environ.get("VAULTSTOCK_DEMO_MODE") == "1"
DB_PATH = os.environ.get("VAULTSTOCK_DB_PATH", str(DATA_DIR / "vaultstock.db"))
ANCHOR_PATH = os.environ.get("VAULTSTOCK_ANCHOR_PATH", str(DATA_DIR / "audit_head.json"))
def _load_jwt_secret() -> str:
    env = os.environ.get("VAULTSTOCK_JWT_SECRET")
    if env:
        return env.strip()
    secret_file = DATA_DIR / ".jwt_secret"
    if not secret_file.exists():
        secret_file.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            os.chmod(secret_file, 0o600)
        except OSError:
            pass
    return secret_file.read_text(encoding="utf-8").strip()

JWT_SECRET = _load_jwt_secret()
JWT_TTL_SECONDS = int(os.environ.get("VAULTSTOCK_JWT_TTL", "3600"))
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "VAULTSTOCK_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]

def _load_audit_key() -> bytes:
    env = os.environ.get("VAULTSTOCK_AUDIT_KEY")
    if env:
        clean = env.strip()
        if all(c in "0123456789abcdefABCDEF" for c in clean) and len(clean) % 2 == 0:
            return bytes.fromhex(clean)
        return clean.encode("utf-8")
    key_file = DATA_DIR / ".audit_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
    raw = key_file.read_text(encoding="utf-8").strip()
    if all(c in "0123456789abcdefABCDEF" for c in raw) and len(raw) % 2 == 0:
        return bytes.fromhex(raw)
    return raw.encode("utf-8")

AUDIT_HMAC_KEY = _load_audit_key()
ADMIN_PASSWORD = os.environ.get("VAULTSTOCK_ADMIN_PASSWORD")
STAFF_PASSWORD = os.environ.get("VAULTSTOCK_STAFF_PASSWORD")

