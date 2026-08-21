"""Demo UI server talks to HydraDB (FakeClient in tests). No fixture JSON."""

from __future__ import annotations

import importlib.util
import json
import threading
from http.client import HTTPConnection
from pathlib import Path

from tests.test_graph_queries import _seed_utcnow

ROOT = Path(__file__).resolve().parents[1]


def _load_demo_api():
    path = ROOT / "scripts" / "demo_api.py"
    spec = importlib.util.spec_from_file_location("demo_api", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


demo_api = _load_demo_api()


def test_ui_files_exist_and_stay_vanilla() -> None:
    index = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    assert "graph.js" in index
    assert "vis-network" not in index
    assert "react" not in index.lower()
    assert "FIXTURE" not in index
    assert "demo_graph.json" not in index
    assert (ROOT / "ui" / "styles.css").is_file()
    assert (ROOT / "ui" / "graph.js").is_file()
    assert (ROOT / "ui" / "app.js").is_file()
    graph_js = (ROOT / "ui" / "graph.js").read_text(encoding="utf-8")
    assert "Hand-rolled SVG" in graph_js
    assert "createElementNS" in graph_js
    app_js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    assert "/graph" in app_js
    assert "/fixture" not in app_js


def test_export_and_http_use_hydradb_client(fake_client) -> None:
    _seed_utcnow(fake_client)
    demo_api.bind_client(fake_client)
    try:
        dumped = demo_api.live_graph()
        paths = {row["path"] for row in dumped["files"]}
        assert "src/timeutil.py" in paths
        assert dumped["repo"]["id"] == "demo-repo"

        hit = demo_api.live_recall(
            {"repo_id": "demo-repo", "file_path": "src/timeutil.py", "error_text": "AttributeError utcnow"}
        )
        assert hit["abstain"] is False
        silent = demo_api.live_recall({"repo_id": "demo-repo", "file_path": "src/unrelated.py"})
        assert silent["abstain"] is True

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

            conn.request("GET", "/graph")
            fx = conn.getresponse()
            payload = json.loads(fx.read().decode("utf-8"))
            assert fx.status == 200
            assert payload["repo"]["id"] == "demo-repo"
            assert fx.getheader("X-SCAR-Mode") == "live"

            conn.request(
                "POST",
                "/v1/recall",
                body=json.dumps({"repo_id": "demo-repo", "file_path": "src/timeutil.py"}),
                headers={"Content-Type": "application/json"},
            )
            recall = json.loads(conn.getresponse().read().decode("utf-8"))
            assert recall["abstain"] is False

            conn.request(
                "POST",
                "/v1/recall",
                body=json.dumps({"repo_id": "demo-repo", "file_path": "src/unrelated.py"}),
                headers={"Content-Type": "application/json"},
            )
            abstain = json.loads(conn.getresponse().read().decode("utf-8"))
            assert abstain["abstain"] is True

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
    finally:
        demo_api.bind_client(None)


def test_demo_seed_script_is_gone() -> None:
    assert not (ROOT / "scripts" / "seed_fixture_graph.py").exists()
    assert not (ROOT / "fixtures" / "demo_graph.json").exists()
    assert not (ROOT / "fixtures" / "demo_ui_layout.json").exists()
