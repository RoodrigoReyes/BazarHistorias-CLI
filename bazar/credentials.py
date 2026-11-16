"""Local credentials and session storage."""

import json
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
SESSION_FILE = Path.home() / ".config" / "bazar-historias" / "cookies.json"


def read_credentials():
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values[key.strip()] = value
    email = os.environ.get("BAZAR_EMAIL", values.get("BAZAR_EMAIL", ""))
    password = os.environ.get("BAZAR_PASSWORD", values.get("BAZAR_PASSWORD", ""))
    if not email or not password:
        raise RuntimeError(f"Set BAZAR_EMAIL and BAZAR_PASSWORD in {ENV_FILE}.")
    return email, password


def save_cookies(cookies):
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(SESSION_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        json.dump(cookies, file)
    SESSION_FILE.chmod(0o600)


def load_cookies():
    if not SESSION_FILE.exists():
        return []
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError
        return data
    except (ValueError, OSError) as exc:
        raise RuntimeError("Unable to read the saved session. Run bazar auth login.") from exc
