from webex_cli.errors import DomainCode, exit_code_for, retryable_for


def test_exit_code_mapping_completeness() -> None:
    for code in DomainCode:
        assert isinstance(exit_code_for(code), int)


def test_retryable_mapping_completeness() -> None:
    for code in DomainCode:
        assert isinstance(retryable_for(code), bool)


def test_ambiguous_recording_is_usage_error() -> None:
    assert exit_code_for(DomainCode.AMBIGUOUS_RECORDING) == 2


def test_new_phase2x_domain_mappings_are_deterministic() -> None:
    assert exit_code_for(DomainCode.CAPABILITY_ERROR) == 5
    assert retryable_for(DomainCode.CAPABILITY_ERROR) is False
    assert exit_code_for(DomainCode.STATE_ERROR) == 2
    assert retryable_for(DomainCode.STATE_ERROR) is True
    assert exit_code_for(DomainCode.CONFLICT_ERROR) == 8
    assert retryable_for(DomainCode.CONFLICT_ERROR) is False
