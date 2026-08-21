"""HydraDB OSS client: Bolt first, HTTP OpenCypher fallback."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BOLT_URI = "bolt://127.0.0.1:7687"
DEFAULT_HTTP_URI = "http://127.0.0.1:8443"
DEFAULT_ADMIN_URI = "http://127.0.0.1:9090"
DEFAULT_TOKEN = "local-development-token-32-bytes"
LOCAL_TOKEN_CANDIDATES = (
    Path("hydradb-data/auth-token"),
    Path(".hydradb/auth-token"),
)


def _read_token_file() -> str | None:
    for path in LOCAL_TOKEN_CANDIDATES:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    env_path = os.environ.get("GRAPH_AUTH_TOKEN_FILE")
    if env_path and Path(env_path).is_file():
        text = Path(env_path).read_text(encoding="utf-8").strip()
        if text:
            return text
    return None


def load_auth_token() -> str:
    token = os.environ.get("HYDRA_AUTH_TOKEN")
    if token:
        return token.strip()
    file_token = _read_token_file()
    if file_token:
        return file_token
    return DEFAULT_TOKEN


def unwrap_hydra_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value and "type" in value:
        return unwrap_hydra_value(value["value"])
    if isinstance(value, list):
        return [unwrap_hydra_value(item) for item in value]
    return value


def cypher_literal(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def inline_params(cypher: str, params: Mapping[str, Any] | None) -> str:
    if not params:
        return cypher
    rendered = cypher
    for key in sorted(params, key=len, reverse=True):
        rendered = rendered.replace(f"${key}", cypher_literal(params[key]))
    return rendered


def hydra_is_ready(admin_uri: str | None = None, timeout: float = 1.0) -> bool:
    uri = (admin_uri or os.environ.get("HYDRA_ADMIN_URI") or DEFAULT_ADMIN_URI).rstrip("/")
    try:
        response = httpx.get(f"{uri}/readyz", timeout=timeout)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


class GraphClient:
    """One ``query(cypher, params)`` over Bolt, with HTTP JSON fallback."""

    def __init__(
        self,
        bolt_uri: str | None = None,
        http_uri: str | None = None,
        auth_token: str | None = None,
        graph_id: str = "default",
        namespace: str = "default",
        cell_id: str = "cell-0",
        admin_uri: str | None = None,
    ) -> None:
        self.bolt_uri = bolt_uri or DEFAULT_BOLT_URI
        self.http_uri = (http_uri or DEFAULT_HTTP_URI).rstrip("/")
        self.auth_token = auth_token or load_auth_token()
        self.graph_id = graph_id
        self.namespace = namespace
        self.cell_id = cell_id
        self.admin_uri = (admin_uri or DEFAULT_ADMIN_URI).rstrip("/")
        self._driver = None
        self._http: httpx.Client | None = None
        self._bolt_ok = True
        self._init_bolt()

    @classmethod
    def from_env(cls) -> GraphClient:
        return cls(
            bolt_uri=os.environ.get("HYDRA_BOLT_URI", DEFAULT_BOLT_URI),
            http_uri=os.environ.get("HYDRA_HTTP_URI", DEFAULT_HTTP_URI),
            auth_token=load_auth_token(),
            graph_id=os.environ.get("HYDRA_GRAPH_ID", "default"),
            namespace=os.environ.get("HYDRA_NAMESPACE", "default"),
            cell_id=os.environ.get("HYDRA_CELL_ID", "cell-0"),
            admin_uri=os.environ.get("HYDRA_ADMIN_URI", DEFAULT_ADMIN_URI),
        )

    def _init_bolt(self) -> None:
        try:
            from neo4j import GraphDatabase
        except ImportError:
            self._bolt_ok = False
            return
        try:
            self._driver = GraphDatabase.driver(
                self.bolt_uri,
                auth=("neo4j", self.auth_token),
                connection_timeout=2.0,
                connection_acquisition_timeout=2.0,
            )
        except Exception:
            self._driver = None
            self._bolt_ok = False

    def _http_client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                timeout=20.0,
                headers={
                    "Authorization": f"Bearer {self.auth_token}",
                    "X-Graph-Namespace": self.namespace,
                    "Content-Type": "application/json",
                },
            )
        return self._http

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None
        if self._http is not None:
            self._http.close()
            self._http = None

    def __enter__(self) -> GraphClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @contextmanager
    def session(self) -> Iterator[GraphClient]:
        yield self

    def query(self, cypher: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        payload = dict(params or {})
        if self._bolt_ok and self._driver is not None:
            try:
                return self._query_bolt(cypher, payload)
            except Exception:
                self._bolt_ok = False
        return self._query_http(cypher, payload)

    def _query_bolt(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        assert self._driver is not None
        with self._driver.session(database=self.graph_id) as session:
            result = session.run(cypher, params)
            rows: list[dict[str, Any]] = []
            for record in result:
                rows.append({key: unwrap_hydra_value(record[key]) for key in record.keys()})
            return rows

    def _query_http(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        url = f"{self.http_uri}/v1/graphs/{self.graph_id}/query"
        body = {
            "cell_id": self.cell_id,
            "query": cypher,
            "parameters": params,
            "consistency": "causal",
        }
        client = self._http_client()
        response = client.post(url, content=json.dumps(body))
        if response.status_code >= 400:
            inlined = inline_params(cypher, params)
            response = client.post(
                url,
                content=json.dumps(
                    {
                        "cell_id": self.cell_id,
                        "query": inlined,
                        "consistency": "causal",
                    }
                ),
            )
        response.raise_for_status()
        return self._parse_http_rows(response.json())

    def _parse_http_rows(self, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        columns = payload.get("columns") or []
        rows = payload.get("rows") or []
        parsed: list[dict[str, Any]] = []
        for row in rows:
            values = unwrap_hydra_value(row)
            if isinstance(values, list):
                parsed.append(
                    {
                        str(columns[i] if i < len(columns) else i): values[i]
                        for i in range(len(values))
                    }
                )
            elif isinstance(values, dict):
                parsed.append({k: unwrap_hydra_value(v) for k, v in values.items()})
        return parsed
