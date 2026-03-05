import json
import shutil
from pathlib import Path
import uuid

from webex_cli.capabilities import CapabilityResult, capability_unavailable, probe_capability
from webex_cli.errors import CliError, DomainCode


def _temp_root() -> Path:
    root = Path(".test_tmp") / f"capabilities-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_probe_capability_uses_cache_until_ttl_expires(monkeypatch) -> None:
    root = _temp_root()
    try:
        monkeypatch.setattr("webex_cli.capabilities.capabilities_cache_path", lambda: root / "capabilities.json")
        times = iter([1_000.0, 1_005.0, 2_000.0, 2_001.0])
        monkeypatch.setattr("webex_cli.capabilities.time.time", lambda: next(times))
        calls = {"count": 0}

        def _probe() -> bool:
            calls["count"] += 1
            return True

        first = probe_capability("templates", profile="default", probe_fn=_probe, ttl_seconds=900)
        second = probe_capability("templates", profile="default", probe_fn=_probe, ttl_seconds=900)
        third = probe_capability("templates", profile="default", probe_fn=_probe, ttl_seconds=900)

        assert first.available is True
        assert second.available is True
        assert third.available is True
        assert calls["count"] == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_probe_capability_persists_negative_results(monkeypatch) -> None:
    root = _temp_root()
    try:
        cache_path = root / "capabilities.json"
        monkeypatch.setattr("webex_cli.capabilities.capabilities_cache_path", lambda: cache_path)
        monkeypatch.setattr("webex_cli.capabilities.time.time", lambda: 1_000.0)

        result = probe_capability(
            "transcript_search",
            profile="work",
            probe_fn=lambda: CapabilityResult(
                available=False,
                checked_at=1_000.0,
                reason_code="SEARCH_CAPABILITY_UNAVAILABLE",
                details={"fallback_command": "webex transcript index rebuild"},
            ),
            ttl_seconds=900,
        )

        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        stored = payload["work"]["transcript_search"]
        assert result.available is False
        assert stored["reason_code"] == "SEARCH_CAPABILITY_UNAVAILABLE"
        assert stored["details"]["fallback_command"] == "webex transcript index rebuild"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_capability_unavailable_uses_new_domain_and_specific_code() -> None:
    error = capability_unavailable(
        "TEMPLATE_CAPABILITY_UNAVAILABLE",
        "Templates are not available for this account.",
        details={"fallback_command": "webex meeting create"},
    )
    assert isinstance(error, CliError)
    assert error.code == DomainCode.CAPABILITY_ERROR
    assert error.error_code == "TEMPLATE_CAPABILITY_UNAVAILABLE"
