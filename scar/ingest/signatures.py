"""Deterministic error signatures used as graph join keys.

Format: ``{language}|{error_class}|{normalized_token}|{normalized_path}``

No Hydra / LLM imports. Pure string heuristics so the same failure
class + token + path always hashes to the same node.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_ERROR_CLASS = re.compile(
    r"\b([A-Za-z_]*Error|[A-Za-z_]*Exception)\b"
)
_FAILED = re.compile(r"\bFAILED\b")
_COMPILER_TS = re.compile(r"\b(TS\d+)\b")
_COMPILER_E = re.compile(r"\berror\[(E\d+)\]|\b(E\d+)\b", re.IGNORECASE)
_EXIT = re.compile(
    r"\bexit(?:[_ ]code)?[:\s]+(\d+)\b|\bexited with (?:status |code )?(\d+)\b",
    re.IGNORECASE,
)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_QUOTED = re.compile(r"['\"`]([A-Za-z_][A-Za-z0-9_]*)['\"`]")
_DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
_MODULE_STOP = frozenset(
    {
        "datetime",
        "json",
        "os",
        "sys",
        "typing",
        "pathlib",
        "time",
        "collections",
        "itertools",
        "functools",
        "math",
        "abc",
        "builtins",
        "builtin",
    }
)
_ATTR_NAME = re.compile(
    r"\battribute\s+['\"`]?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_HOME_PREFIX = re.compile(r"^(?:/Users/[^/]+|/home/[^/]+|/root)(?=/|$)")

_TOKEN_STOP = frozenset(
    {
        "error",
        "exception",
        "failed",
        "failure",
        "traceback",
        "file",
        "line",
        "module",
        "attribute",
        "type",
        "object",
        "none",
        "null",
        "undefined",
        "self",
        "this",
        "true",
        "false",
        "return",
        "has",
        "not",
        "and",
        "the",
        "exit",
        "code",
        "shell",
        "command",
        "python",
        "node",
        "test",
        "assert",
        "assertion",
        "stderr",
        "stdout",
        "process",
        "called",
        "recent",
        "most",
        "stack",
        "frame",
        "in",
        "at",
        "of",
        "to",
        "from",
        "with",
        "for",
        "is",
        "no",
        "an",
        "or",
        "if",
        "else",
        "class",
        "function",
        "def",
        "import",
        "name",
        "value",
        "key",
        "item",
        "index",
        "length",
        "str",
        "int",
        "bool",
        "list",
        "dict",
        "set",
        "tuple",
        "string",
        "number",
        "boolean",
        "void",
        "var",
        "let",
        "const",
        "async",
        "await",
        "info",
        "warning",
        "warn",
        "debug",
        "msg",
        "message",
        "text",
        "data",
        "result",
        "output",
        "input",
        "arg",
        "args",
        "kwargs",
        "param",
        "params",
        "err",
        "errno",
        "tests",
        "testing",
        "pytest",
        "unittest",
        "cannot",
        "could",
        "does",
        "did",
        "was",
        "were",
        "been",
        "being",
        "fatal",
        "status",
        "trace",
        "call",
        "last",
        "during",
        "handling",
        "above",
        "exception",
    }
)


def normalize_path(path: str | None, project_path: str | None = None) -> str:
    """Return a repo-relative POSIX path with home-directory prefixes removed."""
    if not path:
        return ""
    raw = str(path).strip().replace("\\", "/")
    if not raw:
        return ""

    home = str(Path.home()).replace("\\", "/")
    if raw.startswith("~/"):
        raw = f"{home}/{raw[2:]}"
    elif raw == "~":
        raw = home

    project = (project_path or "").strip().replace("\\", "/")
    if project.startswith("~/"):
        project = f"{home}/{project[2:]}"
    elif project == "~":
        project = home
    project = project.rstrip("/")

    if project and (raw == project or raw.startswith(project + "/")):
        raw = raw[len(project) :].lstrip("/")
    elif home and (raw == home or raw.startswith(home + "/")):
        raw = raw[len(home) :].lstrip("/")

    raw = _HOME_PREFIX.sub("", raw).lstrip("/")
    while raw.startswith("./"):
        raw = raw[2:]
    return raw


def infer_error_class(message: str | None) -> str:
    """First Error/Exception/FAILED/compiler code/exit:N token in ``message``."""
    text = message or ""
    hits: list[tuple[int, str]] = []
    for match in _ERROR_CLASS.finditer(text):
        hits.append((match.start(), match.group(1)))
    for match in _FAILED.finditer(text):
        hits.append((match.start(), "FAILED"))
    for match in _COMPILER_TS.finditer(text):
        hits.append((match.start(), match.group(1)))
    for match in _COMPILER_E.finditer(text):
        code = match.group(1) or match.group(2)
        if code:
            hits.append((match.start(), code.upper() if code.upper().startswith("E") else code))
    for match in _EXIT.finditer(text):
        n = match.group(1) or match.group(2)
        hits.append((match.start(), f"exit:{n}"))
    if not hits:
        return "Error"
    named = [
        (pos, name)
        for pos, name in hits
        if name.endswith("Error") or name.endswith("Exception")
    ]
    if named:
        named.sort(key=lambda item: item[0])
        return named[0][1]
    hits.sort(key=lambda item: item[0])
    return hits[0][1]


def _path_identifiers(path: str | None) -> set[str]:
    ids: set[str] = set()
    for part in normalize_path(path, None).split("/"):
        stem = part.rsplit(".", 1)[0]
        for ident in _IDENT.findall(stem):
            ids.add(ident.lower())
    return ids


def _usable(token: str) -> bool:
    lowered = token.lower()
    if len(lowered) < 2:
        return False
    if lowered in _TOKEN_STOP:
        return False
    if lowered.endswith("error") or lowered.endswith("exception"):
        return False
    if re.fullmatch(r"(?:e|ts)\d+", lowered):
        return False
    return True


def infer_normalized_token(message: str | None, path: str | None = None) -> str:
    """Lowercase identifier from the error (and path, if shared) or ``generic``."""
    text = message or ""
    attr = _ATTR_NAME.search(text)
    if attr and _usable(attr.group(1)):
        return attr.group(1).lower()

    quoted = [m.group(1).lower() for m in _QUOTED.finditer(text) if _usable(m.group(1))]
    quoted_specific = [q for q in quoted if q not in _MODULE_STOP]
    dotted_last = [
        m.group(0).split(".")[-1].lower()
        for m in _DOTTED.finditer(text)
        if _usable(m.group(0).split(".")[-1])
    ]
    msg_ids = [m.group(0).lower() for m in _IDENT.finditer(text) if _usable(m.group(0))]
    path_ids = _path_identifiers(path)
    shared = [ident for ident in msg_ids if ident in path_ids]

    for pool in (quoted_specific, dotted_last, shared, quoted, msg_ids):
        for token in pool:
            return token
    return "generic"


def error_signature(
    message: str | None,
    path: str | None,
    language: str | None,
) -> str:
    """Stable join key: language | error class | token | repo-relative path."""
    lang = (language or "unknown").strip().lower() or "unknown"
    klass = infer_error_class(message)
    token = infer_normalized_token(message, path)
    npath = normalize_path(path, None)
    return f"{lang}|{klass}|{token}|{npath}"


def llm_enabled() -> bool:
    """Optional enrichment switch. Default off so demos work offline."""
    return os.environ.get("SCAR_LLM", "0").strip().lower() in {"1", "true", "yes", "on"}
