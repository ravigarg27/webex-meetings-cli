import json
from pathlib import Path

from webex_cli.errors import DomainCode, exit_code_for


def test_exit_code_matrix_matches_v1_1_fixture() -> None:
    path = Path(__file__).resolve().parent / "fixtures" / "exit_code_matrix_v1_1.json"
    expected = json.loads(path.read_text(encoding="utf-8"))
    actual = {code.value: exit_code_for(code) for code in DomainCode}
    assert actual == expected
