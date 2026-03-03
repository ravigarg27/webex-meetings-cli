from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webex_cli.config.paths import config_dir, fallback_credentials_path
from webex_cli.errors import CliError, DomainCode

SERVICE_NAME = "webex-cli"
DEFAULT_PROFILE = "default"


@dataclass
class CredentialRecord:
    token: str
    user_id: str | None = None
    display_name: str | None = None
    primary_email: str | None = None
    org_id: str | None = None
    site_url: str | None = None
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
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_metadata(self) -> dict[str, Any]:
        path = self._metadata_path()
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_fallback(self, token: str) -> None:
        cfg = config_dir()
        cfg.mkdir(parents=True, exist_ok=True)
        path = fallback_credentials_path()
        payload: dict[str, Any] = {}
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        payload[self.profile] = {"token": token}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if os.name != "nt":
            os.chmod(path, 0o600)

    def _load_fallback(self) -> str | None:
        path = fallback_credentials_path()
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        item = payload.get(self.profile)
        if not item:
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
                "user_id": record.user_id,
                "display_name": record.display_name,
                "primary_email": record.primary_email,
                "org_id": record.org_id,
                "site_url": record.site_url,
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
            user_id=metadata.get("user_id"),
            display_name=metadata.get("display_name"),
            primary_email=metadata.get("primary_email"),
            org_id=metadata.get("org_id"),
            site_url=metadata.get("site_url"),
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
            payload = json.loads(path.read_text(encoding="utf-8"))
            if self.profile in payload:
                payload.pop(self.profile)
                path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        metadata = self._metadata_path()
        if metadata.exists():
            metadata.unlink()
