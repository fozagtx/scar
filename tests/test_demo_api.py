"""Fixture-mode recall/blast and demo HTTP server."""

from __future__ import annotations

import importlib.util
import json
import threading
from http.client import HTTPConnection
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_demo_api():
    path = ROOT / "scripts" / "demo_api.py"
    spec = importlib.util.spec_from_file_location("demo_api", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


demo_api = _load_demo_api()


def _fixture() -> dict:
    return json.loads((ROOT / "fixtures" / "demo_graph.json").read_text(encoding="utf-8"))


def test_ui_files_exist_and_stay_vanilla() -> None:
    index = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    assert "graph.js" in index
    assert "vis-network" not in index
    assert "react" not in index.lower()
    assert (ROOT / "ui" / "styles.css").is_file()
    assert (ROOT / "ui" / "graph.js").is_file()
    assert (ROOT / "ui" / "app.js").is_file()
    graph_js = (ROOT / "ui" / "graph.js").read_text(encoding="utf-8")
    assert "Hand-rolled SVG" in graph_js
    assert "createElementNS" in graph_js


def test_recall_utcnow_file_returns_active_ban() -> None:
    result = demo_api.fixture_recall(
        _fixture(),
        "demo-repo",
        "src/timeutil.py",
        symbol="timeutil.now",
        error_text="AttributeError utcnow",
    )
    assert result["abstain"] is False
    texts = [hit["correction"]["text"] for hit in result["hits"]]
    assert "never use datetime.utcnow; use datetime.now(timezone.utc)" in texts
    ids = [hit["correction"]["id"] for hit in result["hits"]]
    assert "cor:utcnow-ban" in ids
    assert "cor:old-utcnow" not in ids
    assert all(hit["active"] is True for hit in result["hits"])


def test_superseded_correction_is_hidden() -> None:
    result = demo_api.fixture_recall(_fixture(), "demo-repo", "src/timeutil.py")
    texts = [hit["correction"]["text"] for hit in result["hits"]]
    assert "use datetime.utcnow for naive UTC timestamps" not in texts


def test_unrelated_file_abstains() -> None:
    result = demo_api.fixture_recall(_fixture(), "demo-repo", "src/unrelated.py")
    assert result["abstain"] is True
    assert result["hits"] == []
    assert "Do not invent a house rule" in result["reason"]


def test_imports_neighborhood_from_api_py() -> None:
    result = demo_api.fixture_recall(_fixture(), "demo-repo", "src/api.py")
    assert result["abstain"] is False
    vias = {hit["via"] for hit in result["hits"]}
    assert "IMPORTS" in vias
    assert any("timezone.utc" in hit["correction"]["text"] for hit in result["hits"])


def test_blast_radius_includes_importer_not_unrelated() -> None:
    radius = demo_api.fixture_blast(_fixture(), "err:utcnow-attr")
    assert radius["signature"] == "python|AttributeError|utcnow|src/timeutil.py"
    assert "src/timeutil.py" in radius["origin_files"]
    assert "src/api.py" in radius["files"]
    assert "src/unrelated.py" not in radius["files"]


def test_layout_fixture_is_positions_only() -> None:
    layout = json.loads((ROOT / "fixtures" / "demo_ui_layout.json").read_text(encoding="utf-8"))
    graph = _fixture()
    ids = {row["id"] for row in graph["files"] + graph["errors"] + graph["corrections"]}
    for node_id, pos in layout["nodes"].items():
        assert "x" in pos and "y" in pos
        assert set(pos) <= {"x", "y"}
    assert "file:src/timeutil.py" in layout["nodes"]
    assert ids & set(layout["nodes"])


def test_http_server_fixture_recall_and_ui() -> None:
    httpd = demo_api.serve("127.0.0.1", 0)
    host, port = httpd.server_address[:2]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/")
        page = conn.getresponse()
        html = page.read().decode("utf-8")
        assert page.status == 200
        assert "SCAR" in html
        assert "Recall" in html

        conn.request("GET", "/fixture")
        fx = conn.getresponse()
        payload = json.loads(fx.read().decode("utf-8"))
        assert fx.status == 200
        assert payload["repo"]["id"] == "demo-repo"

        conn.request(
            "POST",
            "/v1/recall",
            body=json.dumps({"repo_id": "demo-repo", "file_path": "src/timeutil.py"}),
            headers={"Content-Type": "application/json"},
        )
        hit = json.loads(conn.getresponse().read().decode("utf-8"))
        assert hit["abstain"] is False

        conn.request(
            "POST",
            "/v1/recall",
            body=json.dumps({"repo_id": "demo-repo", "file_path": "src/unrelated.py"}),
            headers={"Content-Type": "application/json"},
        )
        silent = json.loads(conn.getresponse().read().decode("utf-8"))
        assert silent["abstain"] is True

        conn.request(
            "POST",
            "/v1/blast",
            body=json.dumps({"error_id": "err:utcnow-attr"}),
            headers={"Content-Type": "application/json"},
        )
        blast = json.loads(conn.getresponse().read().decode("utf-8"))
        assert "src/api.py" in blast["files"]
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
