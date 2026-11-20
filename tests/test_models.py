from tbv.core.models import VERDICT_EXIT, ExitCode, OverallVerdict


def test_verdict_exit_codes_match_spec() -> None:
    assert VERDICT_EXIT[OverallVerdict.PASS] == 0
    assert VERDICT_EXIT[OverallVerdict.BLOCK] == 1
    assert VERDICT_EXIT[OverallVerdict.WARN] == 2


def test_non_verdict_codes_never_collide_with_verdicts() -> None:
    verdict_codes = {int(c) for c in VERDICT_EXIT.values()}
    others = {
        ExitCode.NOT_IMPLEMENTED,
        ExitCode.VALIDATION_FAILED,
        ExitCode.USAGE,
        ExitCode.ENV_UNAVAILABLE,
        ExitCode.INTERNAL,
    }
    assert not verdict_codes & {int(c) for c in others}
