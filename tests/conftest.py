"""Hydra skip/live fixtures and an in-memory FakeClient that records Cypher."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest

from scar.graph.client import GraphClient, hydra_is_ready

NODE_RE = re.compile(r"\((\w+)(?::(\w+))?(?:\s*\{([^}]+)\})?\)")
REL_RE = re.compile(
    r"\((\w+)(?::(\w+))?(?:\s*\{([^}]+)\})?\)"
    r"\s*(<?)-\[:([A-Z_]+)(\*(\d+)\.\.(\d+))?\]-(>?)\s*"
    r"\((\w+)(?::(\w+))?(?:\s*\{([^}]+)\})?\)"
)
PROP_RE = re.compile(r"(\w+)\s*:\s*\$(\w+)")
SET_PARAM_RE = re.compile(r"(\w+)\.(\w+)\s*=\s*\$(\w+)")
SET_BOOL_RE = re.compile(r"(\w+)\.(\w+)\s*=\s*(true|false)", re.I)
RETURN_ITEM_RE = re.compile(r"(\w+)\.(\w+)(?:\s+AS\s+(\w+))?", re.I)
CLAUSE_SPLIT = re.compile(r"\b(MATCH|MERGE|CREATE|SET|RETURN|WHERE|WITH)\b", re.I)


def _eval_props(raw: str | None, params: dict[str, Any]) -> dict[str, Any]:
    if not raw:
        return {}
    props: dict[str, Any] = {}
    for key, pname in PROP_RE.findall(raw):
        props[key] = params.get(pname)
    return props


class FakeClient:
    """Records every query and executes the MERGE/MATCH subset SCAR emits."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.nodes: dict[str, dict[str, Any]] = {}
        self.rels: list[tuple[str, str, str]] = []

    def close(self) -> None:
        return None

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def session(self) -> FakeClient:
        return self

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        payload = dict(params or {})
        self.calls.append((cypher, payload))
        return self._execute(cypher, payload)

    def _ensure(self, node_id: str, label: str | None) -> dict[str, Any]:
        node = self.nodes.setdefault(str(node_id), {"id": str(node_id), "_labels": set()})
        if label:
            node["_labels"].add(label)
        return node

    def _add_rel(self, start: str, rel: str, end: str) -> None:
        edge = (str(start), rel, str(end))
        if edge not in self.rels:
            self.rels.append(edge)

    def _nodes_matching(self, label: str | None, props: dict[str, Any]) -> list[str]:
        found: list[str] = []
        for node_id, data in self.nodes.items():
            if label and label not in data.get("_labels", set()):
                continue
            if all(data.get(key) == value for key, value in props.items()):
                found.append(node_id)
        return found

    def _neighbors(
        self,
        node_id: str,
        rel: str,
        *,
        directed: bool,
        outgoing: bool,
        min_h: int,
        max_h: int,
    ) -> list[str]:
        seen: set[tuple[str, int]] = set()
        found: list[str] = []
        stack: list[tuple[str, int]] = [(node_id, 0)]
        while stack:
            current, hops = stack.pop()
            if hops >= max_h:
                continue
            for start, typ, end in self.rels:
                if typ != rel:
                    continue
                nxt = None
                if start == current and (not directed or outgoing):
                    nxt = end
                elif end == current and (not directed or not outgoing):
                    nxt = start
                if nxt is None:
                    continue
                nxt_hops = hops + 1
                key = (nxt, nxt_hops)
                if key in seen:
                    continue
                seen.add(key)
                if nxt_hops >= min_h:
                    found.append(nxt)
                stack.append((nxt, nxt_hops))
        return found

    def _execute(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        stripped = cypher.strip()
        if stripped.upper().startswith("CREATE CONSTRAINT"):
            return []
        parts = CLAUSE_SPLIT.split(cypher)
        clauses: list[tuple[str, str]] = []
        index = 1
        while index < len(parts) - 1:
            clauses.append((parts[index].upper(), parts[index + 1].strip()))
            index += 2
        rows: list[dict[str, str]] = [{}]
        returned: list[dict[str, Any]] | None = None
        for keyword, body in clauses:
            if keyword == "MATCH":
                rows = self._apply_pattern(rows, body, params, create=False)
            elif keyword == "MERGE":
                rel_match = REL_RE.search(body)
                node_match = NODE_RE.search(body)
                if rel_match:
                    rows = self._apply_pattern(rows, body, params, create=True)
                elif node_match:
                    var, label, raw_props = node_match.group(1), node_match.group(2), node_match.group(3)
                    props = _eval_props(raw_props, params)
                    node_id = props.get("id")
                    if node_id is None:
                        continue
                    self._ensure(str(node_id), label)
                    for key, value in props.items():
                        self.nodes[str(node_id)][key] = value
                    for row in rows:
                        row[var] = str(node_id)
            elif keyword == "CREATE":
                if REL_RE.search(body):
                    rows = self._apply_pattern(rows, body, params, create=True)
            elif keyword == "SET":
                self._apply_set(rows, body, params)
            elif keyword == "RETURN":
                returned = self._project(rows, body)
        return returned or []

    def _apply_pattern(
        self,
        rows: list[dict[str, str]],
        body: str,
        params: dict[str, Any],
        *,
        create: bool,
    ) -> list[dict[str, str]]:
        rel_match = REL_RE.search(body)
        if not rel_match:
            node_match = NODE_RE.search(body)
            if not node_match:
                return rows
            var, label, raw_props = node_match.group(1), node_match.group(2), node_match.group(3)
            props = _eval_props(raw_props, params)
            candidates = self._nodes_matching(label, props)
            next_rows: list[dict[str, str]] = []
            for row in rows:
                if var in row:
                    if row[var] in candidates:
                        next_rows.append(row)
                    continue
                for candidate in candidates:
                    next_rows.append({**row, var: candidate})
            return next_rows

        a_var = rel_match.group(1)
        a_label = rel_match.group(2)
        a_props = _eval_props(rel_match.group(3), params)
        incoming = bool(rel_match.group(4))
        rel = rel_match.group(5)
        varlen = rel_match.group(6)
        min_h = int(rel_match.group(7) or 1)
        max_h = int(rel_match.group(8) or 1)
        outgoing_arrow = bool(rel_match.group(9))
        b_var = rel_match.group(10)
        b_label = rel_match.group(11)
        b_props = _eval_props(rel_match.group(12), params)
        directed = incoming or outgoing_arrow
        outgoing = outgoing_arrow and not incoming

        a_ids = {nid: None for nid in self._nodes_matching(a_label, a_props)} if a_label or a_props else None
        b_ids = {nid: None for nid in self._nodes_matching(b_label, b_props)} if b_label or b_props else None

        if create and not varlen:
            next_rows: list[dict[str, str]] = []
            for row in rows:
                start = row.get(a_var)
                end = row.get(b_var)
                if start is None and a_props.get("id") is not None:
                    start = str(a_props["id"])
                    node = self._ensure(start, a_label)
                    node.update(a_props)
                elif start is None:
                    starts = [nid for nid in (a_ids or {})]
                    start = starts[0] if len(starts) == 1 else None
                if end is None and b_props.get("id") is not None:
                    end = str(b_props["id"])
                    node = self._ensure(end, b_label)
                    node.update(b_props)
                elif end is None:
                    ends = [nid for nid in (b_ids or {})]
                    end = ends[0] if len(ends) == 1 else None
                if start and end:
                    self._add_rel(start, rel, end)
                    next_rows.append({**row, a_var: start, b_var: end})
            return next_rows or rows

        next_rows = []
        for row in rows:
            starts = [row[a_var]] if a_var in row else list(a_ids or [])
            if a_ids is not None:
                starts = [nid for nid in starts if nid in a_ids]
            for start in starts:
                if varlen:
                    ends = self._neighbors(
                        start,
                        rel,
                        directed=directed,
                        outgoing=outgoing,
                        min_h=min_h,
                        max_h=max_h,
                    )
                else:
                    ends = []
                    for src, typ, dst in self.rels:
                        if typ != rel:
                            continue
                        if directed and outgoing:
                            if src == start:
                                ends.append(dst)
                        elif directed and not outgoing:
                            if dst == start:
                                ends.append(src)
                        elif src == start:
                            ends.append(dst)
                        elif dst == start:
                            ends.append(src)
                if b_ids is not None:
                    ends = [nid for nid in ends if nid in b_ids]
                if b_var in row:
                    ends = [nid for nid in ends if nid == row[b_var]]
                for end in ends:
                    next_rows.append({**row, a_var: start, b_var: end})
        return next_rows

    def _apply_set(self, rows: list[dict[str, str]], body: str, params: dict[str, Any]) -> None:
        for var, prop, pname in SET_PARAM_RE.findall(body):
            for row in rows:
                node_id = row.get(var)
                if not node_id:
                    continue
                self._ensure(node_id, None)[prop] = params.get(pname)
        for var, prop, lit in SET_BOOL_RE.findall(body):
            for row in rows:
                node_id = row.get(var)
                if not node_id:
                    continue
                self._ensure(node_id, None)[prop] = lit.lower() == "true"

    def _project(self, rows: list[dict[str, str]], body: str) -> list[dict[str, Any]]:
        items = RETURN_ITEM_RE.findall(body)
        projected: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        distinct = "DISTINCT" in body.upper()
        for row in rows:
            record: dict[str, Any] = {}
            for var, prop, alias in items:
                node_id = row.get(var)
                node = self.nodes.get(node_id or "", {})
                record[alias or prop] = node.get(prop)
            key = tuple(record.get(alias or prop) for var, prop, alias in items)
            if distinct and key in seen:
                continue
            seen.add(key)
            projected.append(record)
        return projected


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def live_client() -> Iterator[GraphClient]:
    if not hydra_is_ready():
        pytest.skip("HydraDB graph-node is not running on 127.0.0.1:9090")
    client = GraphClient.from_env()
    try:
        yield client
    finally:
        client.close()
