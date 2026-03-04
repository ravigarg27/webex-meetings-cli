from typer.testing import CliRunner

from webex_cli.cli import app
from webex_cli.version import __version__


def test_cli_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_cli_rejects_invalid_log_format() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--log-format", "xml", "auth", "whoami", "--json"])
    assert result.exit_code != 0
