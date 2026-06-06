"""SSH key generation and management for GitCode authentication."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from .api import api_request, gitcode_keys
from .common import BootstrapError, ensure_tool, run
from .config import require_token


def ensure_ssh_available() -> None:
    ensure_tool("ssh", "ssh must be available in PATH for ssh-based git pushes")


def generate_ed25519_keypair(
    private_key: Path, public_key: Path, comment: str
) -> None:
    private = ed25519.Ed25519PrivateKey.generate()
    private_bytes = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    private_key.parent.mkdir(parents=True, exist_ok=True)
    private_key.write_bytes(private_bytes)
    public_key.write_text(public_bytes.decode("utf-8") + f" {comment}\n", encoding="utf-8")
    os.chmod(private_key, 0o600)
    os.chmod(public_key, 0o644)


def ensure_ssh_key(config: Dict[str, Any]) -> Dict[str, Any]:
    private_key = Path(config["ssh"]["private_key_path"]).expanduser()
    public_key = Path(config["ssh"]["public_key_path"]).expanduser()
    title = config["ssh"]["title"]
    comment = config["ssh"]["comment"]
    created = False
    generation_method = "existing"
    if not private_key.exists() or not public_key.exists():
        if shutil.which("ssh-keygen"):
            private_key.parent.mkdir(parents=True, exist_ok=True)
            run(
                [
                    "ssh-keygen", "-t", "ed25519", "-C", comment,
                    "-f", str(private_key), "-N", "",
                ],
                check=True,
            )
            os.chmod(private_key, 0o600)
            if public_key.exists():
                os.chmod(public_key, 0o644)
            generation_method = "ssh-keygen"
        else:
            generate_ed25519_keypair(private_key, public_key, comment)
            generation_method = "python-cryptography"
        created = True
    public_value = public_key.read_text(encoding="utf-8").strip()
    existing = next(
        (item for item in gitcode_keys(config) if item.get("key", "").strip() == public_value),
        None,
    )
    uploaded = False
    key_id = existing.get("id") if existing else None
    if existing is None:
        created_key = api_request(
            config["gitcode"]["api_base"], "POST", "/user/keys",
            require_token(config),
            {"key": public_value, "title": title},
        )
        key_id = created_key.get("id")
        uploaded = True
    return {
        "private_key_path": str(private_key),
        "public_key_path": str(public_key),
        "title": title,
        "created_locally": created,
        "generation_method": generation_method,
        "uploaded_to_gitcode": uploaded,
        "public_key_id": key_id,
    }
