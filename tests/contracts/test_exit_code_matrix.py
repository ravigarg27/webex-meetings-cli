import json
from pathlib import Path

from webex_cli.errors import DomainCode, exit_code_for
from webex_cli.version import SCHEMA_VERSION


def test_exit_code_matrix_matches_current_fixture() -> None:
    version_token = SCHEMA_VERSION.replace(".", "_")
    path = Path(__file__).resolve().parent / "fixtures" / f"exit_code_matrix_v{version_token}.json"
    expected = json.loads(path.read_text(encoding="utf-8"))
    actual = {code.value: exit_code_for(code) for code in DomainCode}
    assert actual == expected


def test_historical_exit_code_matrix_fixtures_remain_loadable() -> None:
    fixtures_dir = Path(__file__).resolve().parent / "fixtures"
    for name in ("exit_code_matrix_v1_1.json", "exit_code_matrix_v1_2.json", "exit_code_matrix_v1_3.json"):
        payload = json.loads((fixtures_dir / name).read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
