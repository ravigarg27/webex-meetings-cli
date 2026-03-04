from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any

from webex_cli.config.paths import config_dir, fallback_credentials_path
from webex_cli.errors import CliError, DomainCode
from webex_cli.utils.files import replace_file_atomic

SERVICE_NAME = "webex-cli"
DEFAULT_PROFILE = "default"
FALLBACK_POLICY_ENV = "WEBEX_CREDENTIAL_FALLBACK_POLICY"
FALLBACK_POLICY_DEFAULT = "ci_strict"
FALLBACK_POLICY_ALLOW = "allow_file_fallback"
ALLOW_PLAINTEXT_REFRESH_ENV = "WEBEX_ALLOW_PLAINTEXT_REFRESH_TOKEN"

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _WinDataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


@dataclass
class CredentialRecord:
    token: str
    backend: str | None = None
    auth_type: str = "pat"
    refresh_token: str | None = None
    expires_at: str | None = None
    scopes: list[str] | None = None
    invalid_reason: str | None = None
    oauth_client_id: str | None = None
    oauth_device_authorize_url: str | None = None
    oauth_token_url: str | None = None
    oauth_scope: str | None = None
    oauth_poll_interval_seconds: int | None = None
    oauth_timeout_seconds: int | None = None


class CredentialStore:
    def __init__(self, profile: str = DEFAULT_PROFILE) -> None:
        self.profile = profile

    def _metadata_path(self) -> Path:
        return config_dir() / f"{self.profile}-metadata.json"

    def _keyring_account_access(self) -> str:
        return self.profile

    def _keyring_account_refresh(self) -> str:
        return f"{self.profile}:refresh"

    def _keyring_available(self) -> bool:
        try:
            import keyring  # noqa: F401

            return True
        except Exception:
            return False

    def _save_metadata(self, data: dict[str, Any]) -> None:
        cfg = config_dir()
        cfg.mkdir(parents=True, exist_ok=True)
        path = self._metadata_path()
        self._write_json(path, data)

    def _load_metadata(self) -> dict[str, Any]:
        path = self._metadata_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_fallback(self, token: str) -> None:
        self._save_fallback_bundle(token=token, refresh_token=None)

    def _save_fallback_bundle(self, *, token: str, refresh_token: str | None) -> bool:
        self._ensure_fallback_allowed()
        cfg = config_dir()
        cfg.mkdir(parents=True, exist_ok=True)
        path = fallback_credentials_path()
        payload: dict[str, Any] = {}
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
        if os.name == "nt":
            refresh_persisted = False
            try:
                encrypted = self._dpapi_encrypt(token.encode("utf-8"))
            except Exception as exc:
                raise CliError(
                    DomainCode.INTERNAL_ERROR,
                    "Unable to securely store token in Windows fallback store.",
                ) from exc
            item: dict[str, str] = {"token_dpapi": base64.b64encode(encrypted).decode("ascii")}
            if refresh_token:
                try:
                    refresh_encrypted = self._dpapi_encrypt(refresh_token.encode("utf-8"))
                except Exception as exc:
                    raise CliError(
                        DomainCode.INTERNAL_ERROR,
                        "Unable to securely store refresh token in Windows fallback store.",
                    ) from exc
                item["refresh_token_dpapi"] = base64.b64encode(refresh_encrypted).decode("ascii")
                refresh_persisted = True
            payload[self.profile] = item
        else:
            item = {"token": token}
            refresh_persisted = False
            if refresh_token and self._allow_plaintext_refresh_token():
                item["refresh_token"] = refresh_token
                refresh_persisted = True
            payload[self.profile] = item
        self._write_json(path, payload)
        return refresh_persisted

    def _load_fallback(self) -> str | None:
        return self._load_fallback_bundle().get("token")

    def _allow_plaintext_refresh_token(self) -> bool:
        return self._truthy(os.environ.get(ALLOW_PLAINTEXT_REFRESH_ENV))

    def _load_keyring_bundle(self) -> dict[str, str | None]:
        if not self._keyring_available():
            return {"token": None, "refresh_token": None}
        try:
            import keyring

            return {
                "token": keyring.get_password(SERVICE_NAME, self._keyring_account_access()),
                "refresh_token": keyring.get_password(SERVICE_NAME, self._keyring_account_refresh()),
            }
        except Exception:
            return {"token": None, "refresh_token": None}

    def _clear_keyring_credentials_best_effort(self) -> None:
        if not self._keyring_available():
            return
        try:
            import keyring
        except Exception:
            return

        for account in (self._keyring_account_access(), self._keyring_account_refresh()):
            try:
                keyring.delete_password(SERVICE_NAME, account)
            except Exception:
                pass

    def _load_fallback_bundle(self) -> dict[str, str | None]:
        path = fallback_credentials_path()
        if not path.exists():
            return {"token": None, "refresh_token": None}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"token": None, "refresh_token": None}
        item = payload.get(self.profile)
        if not item:
            return {"token": None, "refresh_token": None}
        if isinstance(item, dict) and item.get("token_dpapi") and os.name == "nt":
            try:
                encrypted = base64.b64decode(str(item["token_dpapi"]))
                token = self._dpapi_decrypt(encrypted).decode("utf-8")
                refresh_token: str | None = None
                if item.get("refresh_token_dpapi"):
                    refresh_encrypted = base64.b64decode(str(item["refresh_token_dpapi"]))
                    refresh_token = self._dpapi_decrypt(refresh_encrypted).decode("utf-8")
                return {"token": token, "refresh_token": refresh_token}
            except Exception:
                return {"token": None, "refresh_token": None}
        if isinstance(item, dict):
            return {
                "token": item.get("token"),
                "refresh_token": item.get("refresh_token"),
            }
        return {"token": None, "refresh_token": None}

    def save(self, record: CredentialRecord) -> str:
        backend = "file_fallback"
        refresh_persisted = bool(record.refresh_token)
        if self._keyring_available():
            try:
                import keyring

                keyring.set_password(SERVICE_NAME, self._keyring_account_access(), record.token)
                if record.refresh_token:
                    keyring.set_password(SERVICE_NAME, self._keyring_account_refresh(), record.refresh_token)
                else:
                    try:
                        keyring.delete_password(SERVICE_NAME, self._keyring_account_refresh())
                    except Exception:
                        pass
                backend = "keyring"
            except Exception:
                self._clear_keyring_credentials_best_effort()
                self._ensure_fallback_allowed()
                refresh_persisted = self._save_fallback_bundle(token=record.token, refresh_token=record.refresh_token)
        else:
            self._ensure_fallback_allowed()
            refresh_persisted = self._save_fallback_bundle(token=record.token, refresh_token=record.refresh_token)
        self._save_metadata(
            {
                "credential_backend": backend,
                "auth_type": record.auth_type,
                "expires_at": record.expires_at,
                "scopes": record.scopes or [],
                "invalid_reason": record.invalid_reason,
                "fallback_policy": self._fallback_policy(),
                "refresh_token_persisted": refresh_persisted,
                "oauth_client_id": record.oauth_client_id,
                "oauth_device_authorize_url": record.oauth_device_authorize_url,
                "oauth_token_url": record.oauth_token_url,
                "oauth_scope": record.oauth_scope,
                "oauth_poll_interval_seconds": record.oauth_poll_interval_seconds,
                "oauth_timeout_seconds": record.oauth_timeout_seconds,
            }
        )
        return backend

    def load(self) -> CredentialRecord:
        metadata = self._load_metadata()
        preferred_backend = str(metadata.get("credential_backend") or "").strip().lower()
        token: str | None = None
        refresh_token: str | None = None
        if preferred_backend == "file_fallback":
            fallback = self._load_fallback_bundle()
            token = fallback.get("token")
            refresh_token = fallback.get("refresh_token")
        elif preferred_backend == "keyring":
            keyring_bundle = self._load_keyring_bundle()
            token = keyring_bundle.get("token")
            refresh_token = keyring_bundle.get("refresh_token")
            if not token:
                fallback = self._load_fallback_bundle()
                token = fallback.get("token")
                refresh_token = fallback.get("refresh_token")
        else:
            keyring_bundle = self._load_keyring_bundle()
            token = keyring_bundle.get("token")
            refresh_token = keyring_bundle.get("refresh_token")
            if not token:
                fallback = self._load_fallback_bundle()
                token = fallback.get("token")
                refresh_token = fallback.get("refresh_token")

        if not token:
            raise CliError(DomainCode.AUTH_REQUIRED, "No credentials found. Run `webex auth login`.")

        scopes = metadata.get("scopes")
        if not isinstance(scopes, list):
            scopes = []
        poll_interval = metadata.get("oauth_poll_interval_seconds")
        if not isinstance(poll_interval, int):
            poll_interval = None
        timeout_seconds = metadata.get("oauth_timeout_seconds")
        if not isinstance(timeout_seconds, int):
            timeout_seconds = None
        auth_type = str(metadata.get("auth_type") or "pat")
        return CredentialRecord(
            token=token,
            backend=metadata.get("credential_backend"),
            auth_type=auth_type,
            refresh_token=refresh_token,
            expires_at=metadata.get("expires_at"),
            scopes=[str(scope) for scope in scopes],
            invalid_reason=metadata.get("invalid_reason"),
            oauth_client_id=metadata.get("oauth_client_id"),
            oauth_device_authorize_url=metadata.get("oauth_device_authorize_url"),
            oauth_token_url=metadata.get("oauth_token_url"),
            oauth_scope=metadata.get("oauth_scope"),
            oauth_poll_interval_seconds=poll_interval,
            oauth_timeout_seconds=timeout_seconds,
        )

    def clear(self) -> None:
        self._clear_keyring_credentials_best_effort()
        path = fallback_credentials_path()
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            if self.profile in payload:
                payload.pop(self.profile)
                self._write_json(path, payload)
        metadata = self._metadata_path()
        if metadata.exists():
            metadata.unlink()

    def mark_invalid(self, reason: str) -> None:
        metadata = self._load_metadata()
        metadata["invalid_reason"] = reason
        self._save_metadata(metadata)

    def clear_invalid(self) -> None:
        metadata = self._load_metadata()
        if "invalid_reason" in metadata:
            metadata.pop("invalid_reason")
            self._save_metadata(metadata)

    @staticmethod
    def _truthy(value: str | None) -> bool:
        if not value:
            return False
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _fallback_policy(self) -> str:
        return (os.environ.get(FALLBACK_POLICY_ENV) or FALLBACK_POLICY_DEFAULT).strip().lower()

    def _ensure_fallback_allowed(self) -> None:
        policy = self._fallback_policy()
        if policy in {"", FALLBACK_POLICY_ALLOW}:
            return
        if policy != FALLBACK_POLICY_DEFAULT:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Invalid credential fallback policy.",
                details={FALLBACK_POLICY_ENV: policy},
            )
        in_ci = self._truthy(os.environ.get("CI"))
        is_interactive = (
            sys.stdin is not None
            and hasattr(sys.stdin, "isatty")
            and sys.stdin.isatty()
            and sys.stdout is not None
            and hasattr(sys.stdout, "isatty")
            and sys.stdout.isatty()
        )
        if in_ci or not is_interactive:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Secure keyring is required in CI/non-interactive sessions (ci_strict policy).",
                details={"fallback_policy": policy, "in_ci": in_ci, "interactive": is_interactive},
            )

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, indent=2)
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            replace_file_atomic(Path(tmp_path), path)
            if os.name != "nt":
                os.chmod(path, 0o600)
        finally:
            tmp = Path(tmp_path)
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    @staticmethod
    def _dpapi_encrypt(data: bytes) -> bytes:
        in_buffer = ctypes.create_string_buffer(data)
        in_blob = _WinDataBlob(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char)))
        out_blob = _WinDataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if crypt32.CryptProtectData(ctypes.byref(in_blob), "webex-cli", None, None, None, 0, ctypes.byref(out_blob)) == 0:
            raise OSError("CryptProtectData failed")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    @staticmethod
    def _dpapi_decrypt(data: bytes) -> bytes:
        in_buffer = ctypes.create_string_buffer(data)
        in_blob = _WinDataBlob(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char)))
        out_blob = _WinDataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)) == 0:
            raise OSError("CryptUnprotectData failed")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
