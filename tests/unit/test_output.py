import pytest

from omdall import output


def test_safe_text_keeps_newlines_and_tabs() -> None:
    assert output.safe_text("a\tb\nc\n") == "a\tb\nc\n"


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("\x1b]52;c;ZXZpbA==\x07", "\\x1b]52;c;ZXZpbA==\\x07"),
        ("over\rwrite", "over\\rwrite"),
        ("\u202eevil", "\\u202eevil"),
        ("zero\u200bwidth", "zero\\u200bwidth"),
        ("caf\u00e9", "caf\u00e9"),
    ],
)
def test_safe_text_escapes_control_characters(raw: str, shown: str) -> None:
    assert output.safe_text(f"{raw}\n{raw}") == f"{shown}\n{shown}"


def test_indented_escapes_each_line(capsys: pytest.CaptureFixture[str]) -> None:
    output.indented(["one \x1b[2K", "two\ttab"], 2)
    assert capsys.readouterr().out == "  one \\x1b[2K\n  two\\ttab\n"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (output.GateError, "error"),
        (output.Busy, "busy"),
        (output.ConfigError, "config"),
        (output.NotFound, "not_found"),
        (output.NotInstalled, "not_installed"),
        (output.AlreadyGuarded, "already_guarded"),
        (output.AlreadyInstalled, "already_installed"),
        (output.RefusedUrl, "refused_url"),
        (output.NameTaken, "name_taken"),
        (output.IdMismatch, "id_mismatch"),
    ],
)
def test_error_codes(error: type[output.GateError], code: str) -> None:
    assert error.code == code
    assert issubclass(error, output.GateError)
