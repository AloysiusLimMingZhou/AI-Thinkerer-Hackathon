"""Consume Recall's short-lived secret download URLs without displaying secrets."""

import argparse
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from dotenv import dotenv_values, set_key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key-url", required=True)
    parser.add_argument("--verification-secret-url", required=True)
    args = parser.parse_args()
    env = Path(__file__).resolve().parents[1] / ".env"
    current = dotenv_values(env)
    values = {}
    for key, url in (
        ("RECALL_API_KEY", args.api_key_url),
        ("RECALL_WEBHOOK_VERIFICATION_SECRET", args.verification_secret_url),
    ):
        if current.get(key):
            continue  # Never overwrite an existing credential.
        if urlparse(url).scheme != "https":
            raise SystemExit("Secret download must use HTTPS")
        with urlopen(url, timeout=20) as response:
            raw = response.read(16384).decode().strip()
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        if isinstance(value, dict):
            candidates = [
                value[k]
                for k in (
                    "api_key",
                    "key",
                    "secret",
                    "verification_secret",
                    "webhook_verification_secret",
                )
                if k in value
            ]
            if len(candidates) != 1:
                raise SystemExit(
                    "Unknown secret download format; no credentials written"
                )
            value = candidates[0]
        if not isinstance(value, str) or not value or any(c.isspace() for c in value):
            raise SystemExit("Invalid secret download; no credentials written")
        values[key] = value
    fd = os.open(env, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.close(fd)
    os.chmod(env, 0o600)
    for key in ("BACKEND_API_TOKEN", "OAUTH_ENCRYPTION_KEY"):
        if not current.get(key):
            values[key] = secrets.token_urlsafe(32)
    if not current.get("RECALL_REGION"):
        values["RECALL_REGION"] = "ap-northeast-1"
    for key, value in values.items():
        set_key(env, key, value)
    print(
        "Saved Recall configuration and local protection keys to ignored .env (mode 0600)."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Credential setup failed; no secret details logged. Retry the same download if unexpired."
        )
