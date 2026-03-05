from typer.testing import CliRunner

from webex_cli.cli import app
from webex_cli.runtime import get_current_profile, peek_request_id, peek_request_start
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


def test_data_subcommands_use_global_profile_flag_only() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["meeting", "list", "--help"])
    assert result.exit_code == 0
    assert result.stdout.count("--profile") <= 1


def test_cli_invocation_resets_runtime_context_vars() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["profile", "list", "--json"])
    assert result.exit_code == 0
    assert peek_request_id() is None
    assert peek_request_start() is None
    assert get_current_profile() is None
