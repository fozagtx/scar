"""Stable error signatures and repo-relative path normalization."""

from __future__ import annotations

from pathlib import Path

from scar.ingest.signatures import (
    error_signature,
    infer_error_class,
    infer_normalized_token,
    normalize_path,
)


def test_signature_stable_for_same_class_path_token() -> None:
    first = error_signature(
        "AttributeError: module 'datetime' has no attribute 'utcnow'",
        "src/timeutil.py",
        "python",
    )
    second = error_signature(
        "Traceback (most recent call last):\nAttributeError: type object has no attribute 'utcnow'",
        "src/timeutil.py",
        "python",
    )
    assert first == second
    assert first == "python|AttributeError|utcnow|src/timeutil.py"


def test_signature_identical_when_called_twice() -> None:
    message = "FAILED tests/test_parser.py - ValueError: Invalid JSON"
    path = "src/parser.py"
    assert error_signature(message, path, "python") == error_signature(
        message, path, "python"
    )


def test_compiler_and_exit_classes() -> None:
    assert infer_error_class("error TS2322: Type 'X' is not assignable") == "TS2322"
    assert infer_error_class("error[E0308]: mismatched types") == "E0308"
    assert infer_error_class("command failed, exit code 2") == "exit:2"
    assert infer_error_class("tests FAILED in 1.2s") == "FAILED"
    assert (
        infer_error_class("FAILED tests/x.py - AttributeError: utcnow")
        == "AttributeError"
    )


def test_token_falls_back_to_generic() -> None:
    assert infer_normalized_token("the file has no type", None) == "generic"
    assert infer_normalized_token("AttributeError: utcnow", "src/timeutil.py") == "utcnow"


def test_normalize_path_is_repo_relative_and_strips_home() -> None:
    home = str(Path.home())
    project = f"{home}/proj"
    assert normalize_path(f"{project}/src/a.py", project) == "src/a.py"
    assert normalize_path("~/proj/src/a.py", "~/proj") == "src/a.py"
    normalized = normalize_path(f"{home}/proj/src/a.py", project)
    assert not normalized.startswith("/")
    assert "Users/" not in normalized
    assert home not in normalized
    assert normalize_path("src/a.py", project) == "src/a.py"


def test_language_and_path_participate_in_join_key() -> None:
    python_sig = error_signature("TypeError: boom", "src/a.py", "python")
    ts_sig = error_signature("TypeError: boom", "src/a.ts", "typescript")
    assert python_sig != ts_sig
    assert python_sig.startswith("python|")
    assert ts_sig.startswith("typescript|")
