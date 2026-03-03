from webex_cli.errors import DomainCode, exit_code_for, retryable_for


def test_exit_code_mapping_completeness() -> None:
    for code in DomainCode:
        assert isinstance(exit_code_for(code), int)


def test_retryable_mapping_completeness() -> None:
    for code in DomainCode:
        assert isinstance(retryable_for(code), bool)


def test_ambiguous_recording_is_usage_error() -> None:
    assert exit_code_for(DomainCode.AMBIGUOUS_RECORDING) == 2

