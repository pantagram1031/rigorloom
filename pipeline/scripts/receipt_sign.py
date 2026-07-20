#!/usr/bin/env python3
"""Reusable keyed integrity helpers for local operator receipts.

Keys are private profile state.  They are never stored beside receipts or
generated reports.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import subprocess
from pathlib import Path
from typing import Iterable


PROFILE_ROOT_ENV = "RIGORLOOM_PROFILE_ROOT"
DEFAULT_KEY_NAME = "render_cert.key"
GENERATED_KEY_BYTES = 32


class ReceiptKeyError(ValueError):
    """Base error for unavailable or unusable operator receipt keys."""


class ReceiptKeyMissing(ReceiptKeyError):
    """The configured private profile or requested key does not exist."""


class ReceiptKeyInvalid(ReceiptKeyError):
    """The requested key exists but cannot safely authenticate receipts."""


def canonical_json_bytes(payload, *, omit_fields: Iterable[str] = ()) -> bytes:
    """Return stable UTF-8 JSON bytes, omitting top-level integrity fields."""
    if not isinstance(payload, dict):
        raise TypeError("signed receipt payload must be an object")
    body = dict(payload)
    for field in omit_fields:
        body.pop(field, None)
    return json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def operator_key_path(
    *, profile_root: str | Path | None = None,
    key_name: str = DEFAULT_KEY_NAME,
) -> Path:
    """Resolve an operator key below the configured private profile root."""
    configured = profile_root
    if configured is None:
        configured = os.environ.get(PROFILE_ROOT_ENV)
    if not configured:
        raise ReceiptKeyMissing(f"{PROFILE_ROOT_ENV} is not configured")
    root = Path(configured).expanduser()
    if not root.is_dir():
        raise ReceiptKeyMissing(f"{PROFILE_ROOT_ENV} is not an existing directory")
    if not key_name or Path(key_name).name != key_name:
        raise ReceiptKeyInvalid("operator key name must be a single file name")
    return root / "keys" / key_name


def _create_key(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(secrets.token_bytes(GENERATED_KEY_BYTES))
        # Authoritative 0600 on POSIX.  On Windows, harden the private-profile
        # file to an owner-only DACL when the host token permits ACL changes.
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        if os.name == "nt":
            username = os.environ.get("USERNAME")
            domain = os.environ.get("USERDOMAIN")
            principal = chr(92).join((domain, username)) if domain and username else username
            if not principal:
                raise ReceiptKeyInvalid("cannot identify the Windows key owner")
            completed = subprocess.run(
                [
                    "icacls", str(path), "/inheritance:r", "/grant:r",
                    f"{principal}:(F)",
                ],
                capture_output=True, text=True, check=False,
            )
            if completed.returncode != 0:
                raise ReceiptKeyInvalid("cannot restrict the Windows key ACL")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load_operator_key(
    *, profile_root: str | Path | None = None,
    key_name: str = DEFAULT_KEY_NAME,
    create: bool = False,
) -> bytes:
    """Load a private operator key, creating it atomically only when requested."""
    path = operator_key_path(profile_root=profile_root, key_name=key_name)
    if path.is_symlink():
        raise ReceiptKeyInvalid("operator key must not be a symlink")
    if not path.exists() and create:
        try:
            _create_key(path)
        except FileExistsError:
            pass
    if path.is_symlink():
        raise ReceiptKeyInvalid("operator key must not be a symlink")
    try:
        key = path.read_bytes()
    except FileNotFoundError as exc:
        raise ReceiptKeyMissing(f"operator key is missing: {path}") from exc
    except OSError as exc:
        raise ReceiptKeyInvalid(f"operator key is unreadable: {path}") from exc
    if len(key) < 16:
        raise ReceiptKeyInvalid("operator key must contain at least 16 bytes")
    return key


def hmac_sha256(
    payload: dict, key: bytes, *, omit_fields: Iterable[str] = (),
) -> str:
    """Return an HMAC-SHA256 hex digest over canonical receipt bytes."""
    return hmac.new(
        key, canonical_json_bytes(payload, omit_fields=omit_fields), hashlib.sha256,
    ).hexdigest()


def verify_hmac_sha256(
    payload: dict, key: bytes, expected: str, *,
    omit_fields: Iterable[str] = (),
) -> bool:
    """Constant-time verification for a canonical receipt HMAC."""
    if not isinstance(expected, str):
        return False
    actual = hmac_sha256(payload, key, omit_fields=omit_fields)
    return hmac.compare_digest(actual, expected)
