"""Prompt formatter: abstain verbatim, numbered active hits, no transcripts."""

from __future__ import annotations

from scar.serve.prompt import ABSTAIN_MESSAGE, format_recall

TRANSCRIPT = (
    "session dump: user said lots of things then assistant dumped a traceback "
    "and three prior turns of chat history that must never appear in recall"
)


def test_abstain_text_is_verbatim() -> None:
    text = format_recall({"hits": [], "abstain": True, "reason": ABSTAIN_MESSAGE})
    assert text == ABSTAIN_MESSAGE
    assert text == "SCAR has no stored correction for this context. Do not invent a house rule."


def test_empty_or_none_result_abstains() -> None:
    assert format_recall(None) == ABSTAIN_MESSAGE
    assert format_recall({}) == ABSTAIN_MESSAGE


def test_hits_print_correction_and_signature_not_transcripts() -> None:
    result = {
        "abstain": False,
        "reason": "",
        "hits": [
            {
                "correction": {
                    "id": "cor:utcnow-ban",
                    "kind": "human_instruction",
                    "text": "never use datetime.utcnow; use datetime.now(timezone.utc)",
                    "active": True,
                },
                "error": {
                    "id": "err:utcnow-attr",
                    "signature": "python|AttributeError|utcnow|src/timeutil.py",
                    "message": TRANSCRIPT,
                },
                "file_path": "src/timeutil.py",
                "symbol": "timeutil.now",
                "via": "CALLS",
                "active": True,
            }
        ],
    }
    text = format_recall(result)
    assert "1. never use datetime.utcnow; use datetime.now(timezone.utc)" in text
    assert "python|AttributeError|utcnow|src/timeutil.py" in text
    assert "src/timeutil.py" in text
    assert "timeutil.now" in text
    assert "CALLS" in text
    assert TRANSCRIPT not in text
    assert "session dump" not in text


def test_imports_neighborhood_and_active_only() -> None:
    result = {
        "abstain": False,
        "hits": [
            {
                "correction": {"text": "do not import utcnow helpers", "active": True},
                "error": {"signature": "python|ImportError|utcnow|src/api.py", "message": TRANSCRIPT},
                "file_path": "src/api.py",
                "symbol": None,
                "via": "IMPORTS",
                "active": True,
            },
            {
                "correction": {"text": "superseded advice", "active": False},
                "error": {"signature": "old-sig", "message": TRANSCRIPT},
                "file_path": "src/api.py",
                "via": "file",
                "active": False,
            },
        ],
    }
    text = format_recall(result)
    assert "1. do not import utcnow helpers" in text
    assert "IMPORTS" in text
    assert "superseded advice" not in text
    assert TRANSCRIPT not in text


def test_all_inactive_hits_abstain() -> None:
    text = format_recall(
        {
            "abstain": False,
            "hits": [
                {
                    "correction": {"text": "dead rule", "active": False},
                    "error": {"signature": "x"},
                    "via": "file",
                    "active": False,
                }
            ],
        }
    )
    assert text == ABSTAIN_MESSAGE
