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


class CredentialStore:
    def __init__(self, profile: str = DEFAULT_PROFILE) -> None:
        self.profile = profile

    def _metadata_path(self) -> Path:
        return config_dir() / f"{self.profile}-metadata.json"

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
            payload[self.profile] = {"token_dpapi": base64.b64encode(encrypted).decode("ascii")}
        else:
            payload[self.profile] = {"token": token}
        self._write_json(path, payload)

    def _load_fallback(self) -> str | None:
        path = fallback_credentials_path()
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        item = payload.get(self.profile)
        if not item:
            return None
        if isinstance(item, dict) and item.get("token_dpapi") and os.name == "nt":
            try:
                encrypted = base64.b64decode(str(item["token_dpapi"]))
                return self._dpapi_decrypt(encrypted).decode("utf-8")
            except Exception:
                return None
        return item.get("token")

    def save(self, record: CredentialRecord) -> str:
        backend = "file_fallback"
        if self._keyring_available():
            try:
                import keyring

                keyring.set_password(SERVICE_NAME, self.profile, record.token)
                backend = "keyring"
            except Exception:
                self._save_fallback(record.token)
        else:
            self._save_fallback(record.token)
        self._save_metadata(
            {
                "credential_backend": backend,
            }
        )
        return backend

    def load(self) -> CredentialRecord:
        token: str | None = None
        if self._keyring_available():
            try:
                import keyring

                token = keyring.get_password(SERVICE_NAME, self.profile)
            except Exception:
                token = self._load_fallback()
        else:
            token = self._load_fallback()

        if not token:
            raise CliError(DomainCode.AUTH_REQUIRED, "No credentials found. Run `webex auth login`.")

        metadata = self._load_metadata()
        return CredentialRecord(
            token=token,
            backend=metadata.get("credential_backend"),
        )

    def clear(self) -> None:
        if self._keyring_available():
            try:
                import keyring

                keyring.delete_password(SERVICE_NAME, self.profile)
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
