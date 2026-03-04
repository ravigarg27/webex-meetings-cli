from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any

from webex_cli.config.paths import config_dir, fallback_credentials_path
from webex_cli.errors import CliError, DomainCode

SERVICE_NAME = "webex-cli"
DEFAULT_PROFILE = "default"

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

    def _save_fallback_bundle(self, *, token: str, refresh_token: str | None) -> None:
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
            payload[self.profile] = item
        else:
            item = {"token": token}
            if refresh_token:
                item["refresh_token"] = refresh_token
            payload[self.profile] = item
        self._write_json(path, payload)

    def _load_fallback(self) -> str | None:
        return self._load_fallback_bundle().get("token")

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
                self._save_fallback_bundle(token=record.token, refresh_token=record.refresh_token)
        else:
            self._save_fallback_bundle(token=record.token, refresh_token=record.refresh_token)
        self._save_metadata(
            {
                "credential_backend": backend,
                "auth_type": record.auth_type,
                "expires_at": record.expires_at,
                "scopes": record.scopes or [],
                "invalid_reason": record.invalid_reason,
            }
        )
        return backend

    def load(self) -> CredentialRecord:
        token: str | None = None
        refresh_token: str | None = None
        if self._keyring_available():
            try:
                import keyring

                token = keyring.get_password(SERVICE_NAME, self._keyring_account_access())
                refresh_token = keyring.get_password(SERVICE_NAME, self._keyring_account_refresh())
            except Exception:
                fallback = self._load_fallback_bundle()
                token = fallback.get("token")
                refresh_token = fallback.get("refresh_token")
        else:
            fallback = self._load_fallback_bundle()
            token = fallback.get("token")
            refresh_token = fallback.get("refresh_token")

        if not token:
            raise CliError(DomainCode.AUTH_REQUIRED, "No credentials found. Run `webex auth login`.")

        metadata = self._load_metadata()
        scopes = metadata.get("scopes")
        if not isinstance(scopes, list):
            scopes = []
        auth_type = str(metadata.get("auth_type") or "pat")
        return CredentialRecord(
            token=token,
            backend=metadata.get("credential_backend"),
            auth_type=auth_type,
            refresh_token=refresh_token,
            expires_at=metadata.get("expires_at"),
            scopes=[str(scope) for scope in scopes],
            invalid_reason=metadata.get("invalid_reason"),
        )

    def clear(self) -> None:
        if self._keyring_available():
            try:
                import keyring

                keyring.delete_password(SERVICE_NAME, self._keyring_account_access())
            except Exception:
                pass
            try:
                keyring.delete_password(SERVICE_NAME, self._keyring_account_refresh())
            except Exception:
                pass
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
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, indent=2)
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            Path(tmp_path).replace(path)
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
