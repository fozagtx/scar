/* Hand-rolled SVG graph for SCAR. No vis-network, no CDN.
 * If a CDN graph library is ever added, keep this file as the offline fallback.
 */
(function (global) {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var TYPE_ORDER = ["File", "Symbol", "Error", "Correction", "AntiPattern"];
  var NODE_W = {
    File: 168,
    Error: 172,
    Correction: 196,
    Symbol: 132,
    AntiPattern: 168,
  };
  var NODE_H = {
    File: 48,
    Error: 52,
    Correction: 52,
    Symbol: 48,
    AntiPattern: 48,
  };

  function el(name, attrs) {
    var node = document.createElementNS(NS, name);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        if (attrs[key] !== undefined && attrs[key] !== null) {
          node.setAttribute(key, String(attrs[key]));
        }
      });
    }
    return node;
  }

  function textEl(name, attrs, value) {
    var node = el(name, attrs);
    node.textContent = value;
    return node;
  }

  function shortLabel(kind, item) {
    if (kind === "File") return item.path || item.id;
    if (kind === "Symbol") return item.qualified_name || item.id;
    if (kind === "Error") {
      var msg = item.message || item.signature || item.id;
      return msg.length > 28 ? msg.slice(0, 26) + "…" : msg;
    }
    if (kind === "Correction") {
      var t = item.text || item.id;
      return t.length > 32 ? t.slice(0, 30) + "…" : t;
    }
    if (kind === "AntiPattern") return item.name || item.id;
    return item.id;
  }

  function kindLabel(kind) {
    if (kind === "AntiPattern") return "ANTIPATTERN";
    return kind.toUpperCase();
  }

  function isSuperseded(item, supersededIds) {
    if (supersededIds.has(item.id)) return true;
    if (item.active === false) return true;
    return false;
  }

  function collectSuperseded(payload) {
    var ids = new Set();
    (payload.relationships || []).forEach(function (rel) {
      if (String(rel.type || "").toUpperCase() === "SUPERSEDES" && rel.to) {
        ids.add(rel.to);
      }
    });
    (payload.corrections || []).forEach(function (row) {
      if (row.supersedes_correction_id) ids.add(row.supersedes_correction_id);
      if (row.active === false) ids.add(row.id);
    });
    return ids;
  }

  function addRel(list, type, from, to, seen) {
    if (!from || !to) return;
    var key = type + "|" + from + "|" + to;
    if (seen.has(key)) return;
    seen.add(key);
    list.push({ type: type, from: from, to: to, key: key });
  }

  function buildModel(payload) {
    var nodes = [];
    var edges = [];
    var seenE = new Set();
    var superseded = collectSuperseded(payload);

    (payload.files || []).forEach(function (row) {
      nodes.push({
        id: row.id,
        kind: "File",
        label: shortLabel("File", row),
        path: row.path,
        raw: row,
        superseded: false,
      });
    });
    (payload.symbols || []).forEach(function (row) {
      nodes.push({
        id: row.id,
        kind: "Symbol",
        label: shortLabel("Symbol", row),
        raw: row,
        superseded: false,
      });
    });
    (payload.errors || []).forEach(function (row) {
      nodes.push({
        id: row.id,
        kind: "Error",
        label: shortLabel("Error", row),
        raw: row,
        superseded: false,
      });
    });
    (payload.corrections || []).forEach(function (row) {
      nodes.push({
        id: row.id,
        kind: "Correction",
        label: shortLabel("Correction", row),
        raw: row,
        superseded: isSuperseded(row, superseded),
      });
    });
    (payload.antipatterns || []).forEach(function (row) {
      nodes.push({
        id: row.id,
        kind: "AntiPattern",
        label: shortLabel("AntiPattern", row),
        raw: row,
        superseded: false,
      });
    });

    (payload.relationships || []).forEach(function (rel) {
      addRel(edges, String(rel.type || "").toUpperCase(), rel.from, rel.to, seenE);
    });
    (payload.errors || []).forEach(function (row) {
      addRel(edges, "IN_FILE", row.id, row.file_id, seenE);
      addRel(edges, "ON_SYMBOL", row.id, row.symbol_id, seenE);
    });
    (payload.corrections || []).forEach(function (row) {
      addRel(edges, "FIXES", row.id, row.fixes_error_id, seenE);
      addRel(edges, "SUPERSEDES", row.id, row.supersedes_correction_id, seenE);
    });
    (payload.antipatterns || []).forEach(function (row) {
      (row.error_ids || []).forEach(function (eid) {
        addRel(edges, "INSTANCE_OF", eid, row.id, seenE);
      });
    });
    (payload.symbols || []).forEach(function (row) {
      if (row.file_id) addRel(edges, "IN_FILE", row.id, row.file_id, seenE);
    });

    var byId = {};
    nodes.forEach(function (n) {
      byId[n.id] = n;
    });
    edges = edges.filter(function (e) {
      return byId[e.from] && byId[e.to];
    });
    return { nodes: nodes, edges: edges, byId: byId, superseded: superseded };
  }

  function fallbackLayout(nodes) {
    var buckets = {};
    TYPE_ORDER.forEach(function (k) {
      buckets[k] = [];
    });
    nodes.forEach(function (n) {
      (buckets[n.kind] || (buckets[n.kind] = [])).push(n);
    });
    var xFor = { File: 150, Symbol: 400, Error: 700, Correction: 980, AntiPattern: 700 };
    var y0 = { File: 180, Symbol: 90, Error: 220, Correction: 90, AntiPattern: 520 };
    TYPE_ORDER.forEach(function (kind) {
      (buckets[kind] || []).forEach(function (node, i) {
        node.x = xFor[kind] || 400;
        node.y = (y0[kind] || 120) + i * 90;
      });
    });
  }

  function applyLayout(nodes, layout) {
    var placed = layout && layout.nodes ? layout.nodes : {};
    nodes.forEach(function (node) {
      var pos = placed[node.id];
      if (pos) {
        node.x = pos.x;
        node.y = pos.y;
      }
    });
    var missing = nodes.some(function (n) {
      return n.x == null || n.y == null;
    });
    if (missing) fallbackLayout(nodes);
  }

  function nodeBox(node) {
    var w = NODE_W[node.kind] || 140;
    var h = NODE_H[node.kind] || 44;
    return { w: w, h: h, x: node.x - w / 2, y: node.y - h / 2 };
  }

  function edgePoint(node, toward) {
    var box = nodeBox(node);
    var dx = toward.x - node.x;
    var dy = toward.y - node.y;
    if (dx === 0 && dy === 0) return { x: node.x, y: node.y };
    var hw = box.w / 2;
    var hh = box.h / 2;
    var sx = hw / Math.abs(dx || 0.0001);
    var sy = hh / Math.abs(dy || 0.0001);
    var t = Math.min(sx, sy);
    return { x: node.x + dx * t, y: node.y + dy * t };
  }

  function quadPath(a, b, lift) {
    var mx = (a.x + b.x) / 2;
    var my = (a.y + b.y) / 2;
    var dx = b.x - a.x;
    var dy = b.y - a.y;
    var len = Math.sqrt(dx * dx + dy * dy) || 1;
    var cx = mx - (dy / len) * lift;
    var cy = my + (dx / len) * lift;
    return {
      d: "M" + a.x + " " + a.y + " Q " + cx + " " + cy + " " + b.x + " " + b.y,
      lx: (a.x + 2 * cx + b.x) / 4,
      ly: (a.y + 2 * cy + b.y) / 4,
    };
  }

  function drawShape(group, node) {
    var box = nodeBox(node);
    var kind = node.kind;
    if (kind === "Symbol") {
      group.appendChild(
        el("ellipse", {
          class: "body",
          cx: node.x,
          cy: node.y,
          rx: box.w / 2,
          ry: box.h / 2,
        })
      );
      return;
    }
    if (kind === "Error") {
      var pts = [
        node.x + "," + (box.y + 4),
        box.x + box.w - 4 + "," + node.y,
        node.x + "," + (box.y + box.h - 4),
        box.x + 4 + "," + node.y,
      ].join(" ");
      group.appendChild(el("polygon", { class: "body", points: pts }));
      return;
    }
    if (kind === "AntiPattern") {
      var x = box.x;
      var y = box.y;
      var w = box.w;
      var h = box.h;
      var cut = 10;
      var pts2 = [
        x + cut + "," + y,
        x + w - cut + "," + y,
        x + w + "," + (y + cut),
        x + w + "," + (y + h - cut),
        x + w - cut + "," + (y + h),
        x + cut + "," + (y + h),
        x + "," + (y + h - cut),
        x + "," + (y + cut),
      ].join(" ");
      group.appendChild(el("polygon", { class: "body", points: pts2 }));
      return;
    }
    group.appendChild(
      el("rect", {
        class: "body",
        x: box.x,
        y: box.y,
        width: box.w,
        height: box.h,
      })
    );
  }

  function ScarGraph(svg) {
    this.svg = svg;
    this.viewport = svg.querySelector("#viewport");
    this.edgeLayer = svg.querySelector("#edges");
    this.nodeLayer = svg.querySelector("#nodes");
    this.model = { nodes: [], edges: [], byId: {} };
    this.view = { x: 0, y: 0, k: 1 };
    this.selected = null;
    this.hotIds = null;
    this.hotEdges = null;
    this.listeners = { select: [] };
    this._bind();
  }

  ScarGraph.prototype.on = function (name, fn) {
    (this.listeners[name] || (this.listeners[name] = [])).push(fn);
  };

  ScarGraph.prototype._emit = function (name, payload) {
    (this.listeners[name] || []).forEach(function (fn) {
      fn(payload);
    });
  };

  ScarGraph.prototype._bind = function () {
    var self = this;
    var drag = null;
    this.svg.addEventListener("pointerdown", function (ev) {
      if (ev.target.closest && ev.target.closest(".node")) return;
      drag = { x: ev.clientX, y: ev.clientY, vx: self.view.x, vy: self.view.y };
      self.svg.setPointerCapture(ev.pointerId);
    });
    this.svg.addEventListener("pointermove", function (ev) {
      if (!drag) return;
      self.view.x = drag.vx + (ev.clientX - drag.x);
      self.view.y = drag.vy + (ev.clientY - drag.y);
      self._applyView();
    });
    this.svg.addEventListener("pointerup", function () {
      drag = null;
    });
    this.svg.addEventListener(
      "wheel",
      function (ev) {
        ev.preventDefault();
        var rect = self.svg.getBoundingClientRect();
        var mx = ev.clientX - rect.left;
        var my = ev.clientY - rect.top;
        var factor = ev.deltaY < 0 ? 1.08 : 0.92;
        var next = Math.min(2.4, Math.max(0.45, self.view.k * factor));
        var wx = (mx - self.view.x) / self.view.k;
        var wy = (my - self.view.y) / self.view.k;
        self.view.k = next;
        self.view.x = mx - wx * next;
        self.view.y = my - wy * next;
        self._applyView();
      },
      { passive: false }
    );
  };

  ScarGraph.prototype._applyView = function () {
    this.viewport.setAttribute(
      "transform",
      "translate(" + this.view.x + "," + this.view.y + ") scale(" + this.view.k + ")"
    );
  };

  ScarGraph.prototype.load = function (payload, layout) {
    this.model = buildModel(payload);
    applyLayout(this.model.nodes, layout);
    this.render();
    this.fit();
    return this.model;
  };

  ScarGraph.prototype.fit = function () {
    if (!this.model.nodes.length) return;
    var minX = Infinity;
    var minY = Infinity;
    var maxX = -Infinity;
    var maxY = -Infinity;
    this.model.nodes.forEach(function (n) {
      var b = nodeBox(n);
      minX = Math.min(minX, b.x);
      minY = Math.min(minY, b.y);
      maxX = Math.max(maxX, b.x + b.w);
      maxY = Math.max(maxY, b.y + b.h);
    });
    var rect = this.svg.getBoundingClientRect();
    var pad = 48;
    var w = Math.max(rect.width, 100);
    var h = Math.max(rect.height, 100);
    var gw = maxX - minX || 1;
    var gh = maxY - minY || 1;
    var k = Math.min((w - pad * 2) / gw, (h - pad * 2) / gh, 1.35);
    this.view.k = k;
    this.view.x = (w - gw * k) / 2 - minX * k;
    this.view.y = (h - gh * k) / 2 - minY * k;
    this._applyView();
  };

  ScarGraph.prototype.render = function () {
    this.edgeLayer.replaceChildren();
    this.nodeLayer.replaceChildren();
    var self = this;
    var pairCount = {};
    this.model.edges.forEach(function (edge) {
      var a = self.model.byId[edge.from];
      var b = self.model.byId[edge.to];
      if (!a || !b) return;
      var pair = a.id < b.id ? a.id + "|" + b.id : b.id + "|" + a.id;
      pairCount[pair] = (pairCount[pair] || 0) + 1;
      var lift = (pairCount[pair] - 1) * 18 + (edge.type === "SUPERSEDES" ? 16 : 8);
      var p1 = edgePoint(a, b);
      var p2 = edgePoint(b, a);
      var q = quadPath(p1, p2, lift);
      var path = el("path", {
        class: "edge " + edge.type,
        d: q.d,
        "data-key": edge.key,
        "data-from": edge.from,
        "data-to": edge.to,
        "data-type": edge.type,
      });
      var label = textEl(
        "text",
        {
          class: "edge-label",
          x: q.lx,
          y: q.ly - 4,
          "text-anchor": "middle",
          "data-key": edge.key,
        },
        edge.type
      );
      self.edgeLayer.appendChild(path);
      self.edgeLayer.appendChild(label);
    });

    this.model.nodes.forEach(function (node) {
      var g = el("g", {
        class: "node " + node.kind + (node.superseded ? " superseded" : ""),
        "data-id": node.id,
        "data-kind": node.kind,
        transform: "translate(0,0)",
      });
      drawShape(g, node);
      var box = nodeBox(node);
      g.appendChild(
        textEl(
          "text",
          {
            class: "kind",
            x: node.x,
            y: box.y + 14,
            "text-anchor": "middle",
          },
          kindLabel(node.kind)
        )
      );
      g.appendChild(
        textEl(
          "text",
          {
            class: "label",
            x: node.x,
            y: node.y + 8,
            "text-anchor": "middle",
          },
          node.label
        )
      );
      if (node.superseded) {
        g.appendChild(
          textEl(
            "text",
            {
              class: "badge-text",
              x: node.x,
              y: box.y + box.h - 6,
              "text-anchor": "middle",
            },
            "superseded"
          )
        );
        g.appendChild(
          el("line", {
            class: "strike-line",
            x1: box.x + 12,
            y1: node.y + 4,
            x2: box.x + box.w - 12,
            y2: node.y + 4,
            stroke: "#6a675c",
            "stroke-width": "1.2",
          })
        );
      }
      g.addEventListener("click", function (ev) {
        ev.stopPropagation();
        self.select(node.id);
      });
      self.nodeLayer.appendChild(g);
    });
    this._paint();
  };

  ScarGraph.prototype.select = function (id) {
    this.selected = id;
    this._paint();
    this._emit("select", this.model.byId[id] || null);
  };

  ScarGraph.prototype.clearHighlight = function () {
    this.hotIds = null;
    this.hotEdges = null;
    this._paint();
  };

  ScarGraph.prototype.highlightIds = function (ids, edgeKeys) {
    this.hotIds = ids ? new Set(ids) : null;
    this.hotEdges = edgeKeys ? new Set(edgeKeys) : null;
    this._paint();
  };

  ScarGraph.prototype.highlightFiles = function (paths) {
    var set = new Set(paths || []);
    var ids = [];
    this.model.nodes.forEach(function (n) {
      if (n.kind === "File" && set.has(n.path || n.raw.path)) ids.push(n.id);
    });
    var keys = [];
    var idSet = new Set(ids);
    this.model.edges.forEach(function (e) {
      if (e.type === "IMPORTS" && idSet.has(e.from) && idSet.has(e.to)) keys.push(e.key);
    });
    this.highlightIds(ids, keys);
  };

  ScarGraph.prototype.highlightRecall = function (hits) {
    var ids = [];
    var keys = [];
    var self = this;
    (hits || []).forEach(function (hit) {
      if (hit.correction && hit.correction.id) ids.push(hit.correction.id);
      if (hit.error && hit.error.id) ids.push(hit.error.id);
      if (hit.file_path) {
        self.model.nodes.forEach(function (n) {
          if (n.kind === "File" && n.path === hit.file_path) ids.push(n.id);
        });
      }
      if (hit.symbol) {
        self.model.nodes.forEach(function (n) {
          if (n.kind === "Symbol" && n.raw.qualified_name === hit.symbol) ids.push(n.id);
        });
      }
      if (hit.correction && hit.error) {
        keys.push("FIXES|" + hit.correction.id + "|" + hit.error.id);
        keys.push("IN_FILE|" + hit.error.id + "|" + (hit.error.file_id || ""));
      }
    });
    this.model.edges.forEach(function (e) {
      if (e.type === "IN_FILE" && ids.indexOf(e.from) >= 0) keys.push(e.key);
      if (e.type === "FIXES" && ids.indexOf(e.from) >= 0) keys.push(e.key);
    });
    this.highlightIds(ids, keys);
  };

  ScarGraph.prototype._paint = function () {
    var hot = this.hotIds;
    var hotE = this.hotEdges;
    var selected = this.selected;
    this.nodeLayer.querySelectorAll(".node").forEach(function (g) {
      var id = g.getAttribute("data-id");
      g.classList.toggle("selected", id === selected);
      g.classList.toggle("dim", !!(hot && hot.size && !hot.has(id)));
    });
    this.edgeLayer.querySelectorAll(".edge").forEach(function (path) {
      var key = path.getAttribute("data-key");
      var from = path.getAttribute("data-from");
      var to = path.getAttribute("data-to");
      var isHot = hotE && hotE.has(key);
      if (!isHot && hot && hot.size && hot.has(from) && hot.has(to)) isHot = true;
      path.classList.toggle("hot", !!isHot);
      path.classList.toggle("dim", !!(hot && hot.size && !isHot));
    });
    this.edgeLayer.querySelectorAll(".edge-label").forEach(function (label) {
      var key = label.getAttribute("data-key");
      var dim = !!(hot && hot.size && !(hotE && hotE.has(key)));
      label.classList.toggle("dim", dim);
    });
  };

  ScarGraph.prototype.get = function (id) {
    return this.model.byId[id] || null;
  };

  global.ScarGraph = ScarGraph;
})(window);
