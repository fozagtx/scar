(function () {
  "use strict";

  var graph;
  var graphData = null;
  var selectedErrorId = "";

  var $ = function (id) {
    return document.getElementById(id);
  };

  function setStatus(left, sel, right) {
    if (left) $("status-left").textContent = left;
    if (sel) $("status-sel").textContent = sel;
    if (right) $("status-right").textContent = right;
  }

  function escapeText(value) {
    return String(value == null ? "" : value);
  }

  function scarCard(hit) {
    var wrap = document.createElement("article");
    wrap.className = "scar";
    wrap.innerHTML = "";
    function row(k, v, cls) {
      var dk = document.createElement("div");
      dk.className = "k";
      dk.textContent = k;
      var dv = document.createElement("div");
      dv.className = "v" + (cls ? " " + cls : "");
      dv.textContent = v;
      wrap.appendChild(dk);
      wrap.appendChild(dv);
    }
    row("correction", hit.correction && hit.correction.id);
    row("instruction", hit.correction && hit.correction.text, "instruction");
    row("fixes", hit.error && hit.error.id);
    row("signature", hit.error && hit.error.signature);
    row("file", hit.file_path || "—");
    row("symbol", hit.symbol || "—");
    row("via", hit.via || "file");
    return wrap;
  }

  function renderHits(result) {
    var out = $("out");
    out.replaceChildren();
    var state = $("out-state");
    if (result.abstain) {
      state.textContent = "abstain";
      state.className = "out-state abstain";
      var box = document.createElement("div");
      box.className = "abstain-box";
      var strong = document.createElement("strong");
      strong.textContent = "ABSTAIN";
      var p = document.createElement("p");
      p.textContent = result.reason || "SCAR has no stored correction for this context. Do not invent a house rule.";
      box.appendChild(strong);
      box.appendChild(p);
      out.appendChild(box);
      return;
    }
    state.textContent = result.hits.length + " hit" + (result.hits.length === 1 ? "" : "s");
    state.className = "out-state hit";
    result.hits.forEach(function (hit) {
      out.appendChild(scarCard(hit));
    });
  }

  function renderBlast(result) {
    var out = $("out");
    out.replaceChildren();
    var state = $("out-state");
    state.textContent = "blast";
    state.className = "out-state blast";
    var box = document.createElement("div");
    box.className = "blast-box";
    var k = document.createElement("div");
    k.className = "k";
    k.textContent = "IMPORTS* from " + (result.signature || result.error_id || "error");
    box.appendChild(k);
    var ol = document.createElement("ol");
    var origins = new Set(result.origin_files || []);
    (result.files || []).forEach(function (path) {
      var li = document.createElement("li");
      li.textContent = path;
      if (origins.has(path)) li.className = "origin";
      ol.appendChild(li);
    });
    if (!(result.files || []).length) {
      var empty = document.createElement("p");
      empty.textContent = "no importers in graph";
      box.appendChild(empty);
    } else {
      box.appendChild(ol);
    }
    out.appendChild(box);
  }

  function renderError(message) {
    var out = $("out");
    out.replaceChildren();
    $("out-state").textContent = "error";
    $("out-state").className = "out-state abstain";
    var box = document.createElement("div");
    box.className = "err-box";
    box.textContent = message;
    out.appendChild(box);
  }

  function fillSessions() {
    var list = $("session-list");
    list.replaceChildren();
    (graphData.sessions || []).forEach(function (session, idx) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "session-btn" + (idx === 0 ? " active" : "");
      btn.innerHTML = "";
      var title = document.createElement("span");
      title.textContent = session.id;
      var small = document.createElement("small");
      small.textContent = (session.source || "session") + " · " + (session.started_at || "");
      btn.appendChild(title);
      btn.appendChild(small);
      btn.addEventListener("click", function () {
        list.querySelectorAll(".session-btn").forEach(function (el) {
          el.classList.remove("active");
        });
        btn.classList.add("active");
        $("in-repo").value = session.repo_id || (graphData.repo && graphData.repo.id) || "";
      });
      li.appendChild(btn);
      list.appendChild(li);
    });
    (graphData.turns || []).forEach(function (turn) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "session-btn";
      var title = document.createElement("span");
      title.textContent = turn.id;
      var small = document.createElement("small");
      small.textContent = turn.role + " · " + (turn.text || "").slice(0, 48);
      btn.appendChild(title);
      btn.appendChild(small);
      btn.addEventListener("click", function () {
        if (turn.file_id) {
          var file = (graphData.files || []).find(function (f) {
            return f.id === turn.file_id;
          });
          if (file) $("in-file").value = file.path;
        }
        if (turn.symbol_id) {
          var sym = (graphData.symbols || []).find(function (s) {
            return s.id === turn.symbol_id;
          });
          if (sym) $("in-symbol").value = sym.qualified_name;
        }
        if (turn.role === "assistant") $("in-error").value = turn.text || "";
        if (turn.role === "user" && turn.text) $("in-error").value = turn.text;
      });
      li.appendChild(btn);
      list.appendChild(li);
    });
  }

  function scarFileIds() {
    var ids = new Set();
    (graphData.errors || []).forEach(function (err) {
      if (err.file_id) ids.add(err.file_id);
    });
    return ids;
  }

  function fillFiles() {
    var list = $("file-list");
    list.replaceChildren();
    var scars = scarFileIds();
    (graphData.files || []).forEach(function (file) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "file-btn";
      if (file.path === $("in-file").value) btn.classList.add("active");
      var title = document.createElement("span");
      title.textContent = file.path;
      var small = document.createElement("small");
      if (scars.has(file.id)) {
        btn.classList.add("has-scar");
        small.textContent = "has scar";
      } else {
        btn.classList.add("quiet");
        small.textContent = "abstain target";
      }
      btn.appendChild(title);
      btn.appendChild(small);
      btn.addEventListener("click", function () {
        list.querySelectorAll(".file-btn").forEach(function (el) {
          el.classList.remove("active");
        });
        btn.classList.add("active");
        $("in-file").value = file.path;
        var err = (graphData.errors || []).find(function (e) {
          return e.file_id === file.id;
        });
        $("in-error").value = err ? (err.message || err.signature || "") : "";
        if (err) selectedErrorId = err.id;
        var sym = null;
        if (err && err.symbol_id) {
          sym = (graphData.symbols || []).find(function (s) {
            return s.id === err.symbol_id;
          });
        }
        $("in-symbol").value = sym ? (sym.qualified_name || "") : "";
        graph.select(file.id);
      });
      li.appendChild(btn);
      list.appendChild(li);
    });
  }

  function syncFileActive() {
    var path = $("in-file").value;
    document.querySelectorAll(".file-btn").forEach(function (btn) {
      btn.classList.toggle("active", btn.querySelector("span") && btn.querySelector("span").textContent === path);
    });
  }

  async function postJson(url, body) {
    var res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    var mode = res.headers.get("X-SCAR-Mode");
    if (mode) {
      $("mast-mode-label").textContent = mode.toUpperCase();
      $("mast-mode").classList.toggle("live", mode === "live");
    }
    var data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }

  async function doRecall(ev) {
    if (ev) ev.preventDefault();
    syncFileActive();
    setStatus("recalling…");
    try {
      var result = await postJson("/v1/recall", {
        repo_id: $("in-repo").value,
        file_path: $("in-file").value,
        symbol: $("in-symbol").value || null,
        error_text: $("in-error").value || null,
      });
      renderHits(result);
      if (result.abstain) {
        graph.clearHighlight();
        setStatus("abstain", $("in-file").value, "no house rule");
      } else {
        graph.highlightRecall(result.hits);
        if (result.hits[0] && result.hits[0].error) {
          selectedErrorId = result.hits[0].error.id;
        }
        setStatus("recall hit", $("in-file").value, (result.hits[0] && result.hits[0].via) || "file");
      }
    } catch (err) {
      renderError(String(err.message || err));
      setStatus("recall failed");
    }
  }

  async function doBlast() {
    setStatus("blast radius…");
    try {
      var result = await postJson("/v1/blast", { error_id: selectedErrorId });
      renderBlast(result);
      graph.highlightFiles(result.files || []);
      setStatus("blast", selectedErrorId, (result.files || []).length + " files");
    } catch (err) {
      renderError(String(err.message || err));
      setStatus("blast failed");
    }
  }

  function onSelect(node) {
    if (!node) return;
    setStatus(null, node.kind + " " + node.id);
    $("stage-hint").textContent = node.kind + " · " + node.id;
    if (node.kind === "File") {
      $("in-file").value = node.path || node.raw.path;
      syncFileActive();
    }
    if (node.kind === "Error") {
      selectedErrorId = node.id;
      $("in-error").value = node.raw.message || node.raw.signature || "";
      if (node.raw.file_id) {
        var file = (graphData.files || []).find(function (f) {
          return f.id === node.raw.file_id;
        });
        if (file) $("in-file").value = file.path;
      }
    }
    if (node.kind === "Symbol") {
      $("in-symbol").value = node.raw.qualified_name;
    }
    if (node.kind === "Correction") {
      var out = $("out");
      out.replaceChildren();
      $("out-state").textContent = node.superseded ? "superseded" : "correction";
      $("out-state").className = "out-state " + (node.superseded ? "abstain" : "hit");
      var fake = {
        correction: node.raw,
        error: { id: node.raw.fixes_error_id, signature: "", message: "" },
        file_path: (function () {
          var err = (graphData.errors || []).find(function (e) {
            return e.id === node.raw.fixes_error_id;
          });
          if (!err || !err.file_id) return "";
          var f = (graphData.files || []).find(function (row) {
            return row.id === err.file_id;
          });
          return f ? f.path : "";
        })(),
        symbol: "",
        via: node.superseded ? "SUPERSEDES" : "FIXES",
      };
      var card = scarCard(fake);
      if (node.superseded) {
        card.classList.add("dead");
        var badge = document.createElement("span");
        badge.className = "badge badge-dead";
        badge.textContent = "superseded";
        card.querySelector(".v").appendChild(badge);
      }
      out.appendChild(card);
    }
  }

  async function boot() {
    graph = new window.ScarGraph($("graph"));
    graph.on("select", onSelect);
    $("recall-form").addEventListener("submit", doRecall);
    $("btn-blast").addEventListener("click", doBlast);
    $("btn-fit").addEventListener("click", function () {
      graph.fit();
    });
    $("btn-clear").addEventListener("click", function () {
      graph.clearHighlight();
      setStatus("highlight cleared");
    });
    window.addEventListener("keydown", function (ev) {
      if (ev.target && (ev.target.tagName === "INPUT" || ev.target.tagName === "TEXTAREA")) {
        if (ev.key === "Escape") ev.target.blur();
        return;
      }
      if (ev.key === "r" || ev.key === "R") {
        ev.preventDefault();
        doRecall();
      }
      if (ev.key === "b" || ev.key === "B") {
        ev.preventDefault();
        doBlast();
      }
      if (ev.key === "f" || ev.key === "F") graph.fit();
      if (ev.key === "Escape") graph.clearHighlight();
    });

    setStatus("loading HydraDB");
    var fxRes = await fetch("/graph");
    if (!fxRes.ok) {
      var errBody = {};
      try {
        errBody = await fxRes.json();
      } catch (e) {
        errBody = {};
      }
      throw new Error(errBody.error || "GET /graph failed — is graph-node up?");
    }
    graphData = await fxRes.json();
    $("mast-mode-label").textContent = "LIVE";
    $("mast-mode").classList.add("live");

    var repo = graphData.repo || {};
    $("mast-repo").textContent = repo.id || "—";
    $("mast-lang").textContent = repo.language || "—";
    $("repo-id").textContent = repo.id || "—";
    $("repo-root").textContent = repo.root || "—";
    $("in-repo").value = repo.id || "";

    var firstFile = (graphData.files || [])[0];
    if (firstFile && firstFile.path) $("in-file").value = firstFile.path;
    var firstErr = (graphData.errors || [])[0];
    if (firstErr) {
      selectedErrorId = firstErr.id;
      $("in-error").value = firstErr.message || firstErr.signature || "";
    }

    var model = graph.load(graphData, null);
    $("graph-counts").textContent = model.nodes.length + "n " + model.edges.length + "e";
    fillSessions();
    fillFiles();
    setStatus(
      "HydraDB",
      "graph ready",
      escapeText(model.nodes.length) + " nodes · live"
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      boot().catch(function (err) {
        renderError(String(err.message || err));
        setStatus("boot failed");
      });
    });
  } else {
    boot().catch(function (err) {
      renderError(String(err.message || err));
      setStatus("boot failed");
    });
  }
})();
