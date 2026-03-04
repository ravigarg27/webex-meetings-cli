from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
from urllib.parse import urlparse

from webex_cli.config.paths import (
    config_dir,
    fallback_credentials_path,
    legacy_metadata_path,
    profile_migration_marker_path,
    profiles_path,
)
from webex_cli.config.settings import load_settings
from webex_cli.errors import CliError, DomainCode
from webex_cli.utils.files import replace_file_atomic

DEFAULT_PROFILE_KEY = "default"
PROFILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,50}$")
_RESERVED_NAMES = {
    ".",
    "..",
    "null",
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_profile_name(name: str) -> str:
    candidate = name.strip()
    if not PROFILE_NAME_PATTERN.match(candidate):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "Invalid profile name.",
            details={"profile": name},
        )
    key = candidate.lower()
    if key in _RESERVED_NAMES:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "Profile name is reserved.",
            details={"profile": name},
        )
    return key


@dataclass
class ProfileRecord:
    key: str
    name: str
    default_tz: str | None
    site_url: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("key", None)
        return payload


@dataclass
class ProfileRegistry:
    active_profile: str
    profiles: dict[str, ProfileRecord]


class ProfileStore:
    def ensure_initialized(self) -> ProfileRegistry:
        self._auto_migrate_to_default_profile()
        path = profiles_path()
        if path.exists():
            return self._load_registry()
        cfg = config_dir()
        cfg.mkdir(parents=True, exist_ok=True)

        settings = load_settings()
        now = _utc_now_iso()
        default = ProfileRecord(
            key=DEFAULT_PROFILE_KEY,
            name=DEFAULT_PROFILE_KEY,
            default_tz=settings.default_tz,
            site_url=None,
            created_at=now,
            updated_at=now,
        )
        registry = ProfileRegistry(
            active_profile=DEFAULT_PROFILE_KEY,
            profiles={DEFAULT_PROFILE_KEY: default},
        )
        self._write_registry(registry)
        return registry

    def _auto_migrate_to_default_profile(self) -> None:
        cfg = config_dir()
        cfg.mkdir(parents=True, exist_ok=True)
        marker_path = profile_migration_marker_path()
        if marker_path.exists():
            return

        backups: list[tuple[Path, Path]] = []
        migrated: list[str] = []

        def _backup(path: Path) -> Path:
            backup_path = path.with_suffix(path.suffix + ".phase-1.1.bak")
            if not backup_path.exists():
                shutil.copy2(path, backup_path)
            backups.append((path, backup_path))
            return backup_path

        try:
            credentials_path = fallback_credentials_path()
            if credentials_path.exists():
                _backup(credentials_path)
                migrated_credential_payload = self._migrate_legacy_credentials_payload(credentials_path)
                if migrated_credential_payload is not None:
                    self._write_json_atomic(credentials_path, migrated_credential_payload)
                    migrated.append(str(credentials_path))

            legacy_metadata = legacy_metadata_path()
            if legacy_metadata.exists():
                target_metadata = cfg / f"{DEFAULT_PROFILE_KEY}-metadata.json"
                if not target_metadata.exists():
                    _backup(legacy_metadata)
                    shutil.copy2(legacy_metadata, target_metadata)
                    migrated.append(str(target_metadata))

            self._write_json_atomic(
                marker_path,
                {
                    "version": "1.1",
                    "completed_at": _utc_now_iso(),
                    "migrated_paths": migrated,
                },
            )
        except Exception as exc:
            for original, backup in reversed(backups):
                if backup.exists():
                    shutil.copy2(backup, original)
            raise CliError(
                DomainCode.INTERNAL_ERROR,
                "Profile auto-migration failed and was rolled back.",
                details={"reason": type(exc).__name__},
            ) from exc

    def _migrate_legacy_credentials_payload(self, credentials_path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(credentials_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        if DEFAULT_PROFILE_KEY in payload:
            return None

        legacy_tokens = {}
        if isinstance(payload.get("token"), str):
            legacy_tokens["token"] = payload["token"]
        if isinstance(payload.get("token_dpapi"), str):
            legacy_tokens["token_dpapi"] = payload["token_dpapi"]
        if isinstance(payload.get("refresh_token"), str):
            legacy_tokens["refresh_token"] = payload["refresh_token"]
        if isinstance(payload.get("refresh_token_dpapi"), str):
            legacy_tokens["refresh_token_dpapi"] = payload["refresh_token_dpapi"]
        if not legacy_tokens:
            return None
        return {DEFAULT_PROFILE_KEY: legacy_tokens}

    def resolve(self, preferred: str | None = None) -> str:
        registry = self.ensure_initialized()
        if preferred is None or preferred.strip() == "":
            return registry.active_profile
        key = _canonical_profile_name(preferred)
        if key not in registry.profiles:
            raise CliError(
                DomainCode.NOT_FOUND,
                "Profile not found.",
                details={"profile": preferred},
            )
        return key

    def list_profiles(self) -> list[dict[str, Any]]:
        registry = self.ensure_initialized()
        rows: list[dict[str, Any]] = []
        for key, record in sorted(registry.profiles.items(), key=lambda kv: kv[1].name.lower()):
            rows.append(
                {
                    "name": record.name,
                    "key": key,
                    "is_active": key == registry.active_profile,
                    "default_tz": record.default_tz,
                    "site_url": record.site_url,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                }
            )
        return rows

    def create_profile(self, name: str, default_tz: str | None, site_url: str | None) -> dict[str, Any]:
        registry = self.ensure_initialized()
        key = _canonical_profile_name(name)
        if key in registry.profiles:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Profile already exists.",
                details={"profile": name},
            )
        if site_url:
            parsed = urlparse(site_url)
            if parsed.scheme.lower() != "https" or not parsed.netloc:
                raise CliError(
                    DomainCode.VALIDATION_ERROR,
                    "`--site-url` must be a valid https URL.",
                    details={"site_url": site_url},
                )
        now = _utc_now_iso()
        display_name = name.strip()
        registry.profiles[key] = ProfileRecord(
            key=key,
            name=display_name,
            default_tz=default_tz,
            site_url=site_url,
            created_at=now,
            updated_at=now,
        )
        self._write_registry(registry)
        return {
            "name": display_name,
            "key": key,
            "is_active": key == registry.active_profile,
            "default_tz": default_tz,
            "site_url": site_url,
            "created_at": now,
            "updated_at": now,
        }

    def show_profile(self, name: str | None = None) -> dict[str, Any]:
        registry = self.ensure_initialized()
        key = registry.active_profile if not name else _canonical_profile_name(name)
        record = registry.profiles.get(key)
        if record is None:
            raise CliError(
                DomainCode.NOT_FOUND,
                "Profile not found.",
                details={"profile": name},
            )
        return {
            "name": record.name,
            "key": key,
            "is_active": key == registry.active_profile,
            "default_tz": record.default_tz,
            "site_url": record.site_url,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def use_profile(self, name: str) -> dict[str, Any]:
        registry = self.ensure_initialized()
        key = _canonical_profile_name(name)
        record = registry.profiles.get(key)
        if record is None:
            raise CliError(
                DomainCode.NOT_FOUND,
                "Profile not found.",
                details={"profile": name},
            )
        registry.active_profile = key
        record.updated_at = _utc_now_iso()
        self._write_registry(registry)
        return self.show_profile(name=record.name)

    def delete_profile(self, name: str) -> dict[str, Any]:
        registry = self.ensure_initialized()
        key = _canonical_profile_name(name)
        if key == registry.active_profile:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Cannot delete the active profile.",
                details={"profile": name},
            )
        record = registry.profiles.get(key)
        if record is None:
            raise CliError(
                DomainCode.NOT_FOUND,
                "Profile not found.",
                details={"profile": name},
            )
        from webex_cli.config.credentials import CredentialStore  # local import to avoid module cycle

        CredentialStore(profile=key).clear()
        registry.profiles.pop(key, None)
        self._write_registry(registry)
        return {
            "name": record.name,
            "key": key,
            "deleted_local_credentials": True,
            "deleted_local_settings": True,
        }

    def profile_default_tz(self, profile_key: str) -> str | None:
        registry = self.ensure_initialized()
        record = registry.profiles.get(profile_key)
        if record is None:
            return None
        return record.default_tz

    def _load_registry(self) -> ProfileRegistry:
        path = profiles_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Profile registry is invalid JSON.",
                details={"path": str(path)},
            ) from exc
        if not isinstance(payload, dict):
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Profile registry must be a JSON object.",
                details={"path": str(path)},
            )

        raw_profiles = payload.get("profiles")
        if not isinstance(raw_profiles, dict):
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Profile registry missing profiles map.",
                details={"path": str(path)},
            )
        profiles: dict[str, ProfileRecord] = {}
        for key, value in raw_profiles.items():
            if not isinstance(value, dict):
                raise CliError(DomainCode.VALIDATION_ERROR, "Profile entry must be an object.")
            canonical = _canonical_profile_name(key)
            profiles[canonical] = ProfileRecord(
                key=canonical,
                name=str(value.get("name") or key),
                default_tz=value.get("default_tz"),
                site_url=value.get("site_url"),
                created_at=str(value.get("created_at") or _utc_now_iso()),
                updated_at=str(value.get("updated_at") or _utc_now_iso()),
            )
        if not profiles:
            now = _utc_now_iso()
            profiles[DEFAULT_PROFILE_KEY] = ProfileRecord(
                key=DEFAULT_PROFILE_KEY,
                name=DEFAULT_PROFILE_KEY,
                default_tz=None,
                site_url=None,
                created_at=now,
                updated_at=now,
            )
        active = str(payload.get("active_profile") or DEFAULT_PROFILE_KEY).lower()
        if active not in profiles:
            active = DEFAULT_PROFILE_KEY if DEFAULT_PROFILE_KEY in profiles else next(iter(profiles))
        return ProfileRegistry(active_profile=active, profiles=profiles)

    def _write_registry(self, registry: ProfileRegistry) -> None:
        cfg = config_dir()
        cfg.mkdir(parents=True, exist_ok=True)
        path = profiles_path()
        payload = {
            "active_profile": registry.active_profile,
            "profiles": {key: value.to_dict() for key, value in registry.profiles.items()},
        }
        self._write_json_atomic(path, payload)

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
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
