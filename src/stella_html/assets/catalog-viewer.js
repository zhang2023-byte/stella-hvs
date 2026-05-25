(function () {
  "use strict";

  const FIELD_LABELS = {
    ra: "RA",
    dec: "Dec",
    parallax: "plx",
    proper_motion_ra: "pmRA",
    proper_motion_dec: "pmDec",
    radial_velocity: "RV",
    total_velocity: "total velocity",
    unbound_probability: "P(unbound)",
    teff: "Teff",
    log_g: "log g",
    metallicity: "[Fe/H]",
    mass: "mass",
    radius: "radius",
    age: "age",
    luminosity: "luminosity",
    spectral_type: "spectral type"
  };

  const OBSERVED_FIELDS = [
    "ra",
    "dec",
    "parallax",
    "proper_motion_ra",
    "proper_motion_dec",
    "radial_velocity"
  ];

  const GROUP_LABELS = {
    observed_phase_space: "Observed phase space",
    derived_kinematics: "Derived kinematics",
    bound_assessment: "Bound assessment",
    photometry: "Photometry",
    spectroscopy: "Spectroscopy",
    stellar_parameters: "Stellar parameters",
    abundances: "Abundances",
    quality_flags: "Quality flags",
    orbit: "Orbit",
    astrophysical_origin: "Astrophysical origin",
    hypothesis_metrics: "Hypothesis metrics",
    extra: "Extra"
  };

  const app = document.getElementById("app");
  const state = {
    index: null,
    objects: [],
    objectMap: new Map(),
    rows: [],
    filter: "",
    sortKey: "identifier",
    sortDir: "asc",
    selectedStep: null,
    activeLineage: null
  };

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function compact(value) {
    return String(value == null ? "" : value).trim();
  }

  function uniq(values) {
    const out = [];
    const seen = new Set();
    values.forEach((value) => {
      const text = compact(value);
      if (text && !seen.has(text)) {
        seen.add(text);
        out.push(text);
      }
    });
    return out;
  }

  function quantityText(quantity, options) {
    if (!quantity || typeof quantity !== "object") {
      return "";
    }
    const value = compact(quantity.value);
    if (!value) {
      return "";
    }
    let text = value;
    const error = compact(quantity.error);
    const lower = compact(quantity.lower_error);
    const upper = compact(quantity.upper_error);
    if (error) {
      text += " ± " + error;
    } else if (lower || upper) {
      const lowerText = lower && (lower.startsWith("-") || lower.startsWith("+")) ? lower : "-" + (lower || "?");
      const upperText = upper && (upper.startsWith("-") || upper.startsWith("+")) ? upper : "+" + (upper || "?");
      text += " " + lowerText + " " + upperText;
    }
    const unit = compact(quantity.unit);
    if (unit && (!options || options.includeUnit !== false)) {
      text += " " + unit;
    }
    return text;
  }

  function candidateForSource(record, sourceId) {
    return (record.candidates || []).find((candidate) => candidate && candidate.source === sourceId) || null;
  }

  function sourceSummary(record, source) {
    const sourceId = compact(source.source);
    const candidate = candidateForSource(record, sourceId) || {};
    const core = candidate.core || {};
    const observed = core.observed_phase_space || {};
    const derived = core.derived_kinematics || {};
    const boundAssessment = core.bound_assessment || {};
    const paper = source.paper || {};
    const phaseSpace = {};
    OBSERVED_FIELDS.forEach((field) => {
      phaseSpace[field] = quantityText(observed[field], { includeUnit: false });
    });
    return {
      source: sourceId,
      record_id: compact(source.record_id),
      paper_candidate_id: compact(source.paper_candidate_id),
      gaia_source_id: compact(source.gaia_source_id),
      arxiv_id: compact(paper.arxiv_id),
      bibcode: compact(paper.bibcode),
      phase_space: phaseSpace,
      total_velocity: quantityText(derived.total_velocity, { includeUnit: false }),
      unbound_probability: quantityText(boundAssessment.unbound_probability, { includeUnit: false })
    };
  }

  function buildIndexRow(record) {
    const canonical = record.canonical_identifier || {};
    const sourceRows = (record.sources || []).map((source) => sourceSummary(record, source));
    return {
      object_id: compact(record.object_id),
      identifier: compact(canonical.value || record.object_id),
      identifier_kind: compact(canonical.kind),
      gaia_source_ids: uniq(sourceRows.map((source) => source.gaia_source_id)),
      paper_candidate_ids: uniq(sourceRows.map((source) => source.paper_candidate_id)),
      bibcodes: uniq(sourceRows.map((source) => source.bibcode)),
      sources: sourceRows,
      source_count: sourceRows.length,
      warning_count: ((record.merge || {}).warnings || []).length
    };
  }

  async function fetchJson(path) {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(path + " returned HTTP " + response.status);
    }
    return response.json();
  }

  async function loadData() {
    if (window.STELLA_CATALOG_SNAPSHOT) {
      const snapshot = window.STELLA_CATALOG_SNAPSHOT;
      state.index = snapshot.index || { summary: snapshot.summary || {} };
      state.objects = snapshot.objects || [];
      state.rows = snapshot.rows && snapshot.rows.length ? snapshot.rows : state.objects.map(buildIndexRow);
    } else {
      const root = (document.body.dataset.catalogRoot || "../../catalog").replace(/\/$/, "");
      state.index = await fetchJson(root + "/03_hvs_candidates_index.json");
      const indexObjects = state.index.objects || [];
      state.objects = await Promise.all(
        indexObjects.map((item) => fetchJson(root + "/candidates/" + encodeURIComponent(item.object_id) + ".json"))
      );
      state.rows = state.objects.map(buildIndexRow);
    }
    state.objectMap = new Map(state.objects.map((record) => [compact(record.object_id), record]));
  }

  function shell(content, active) {
    return `
      <div class="site-frame">
        <header class="hero">
          <div class="hero-content">
            <div class="eyebrow">Stella object-level data system</div>
            <h1>Stella HVS Catalog</h1>
            <p class="hero-copy">An object-level data and knowledge system for high-velocity-star research, preserving paper provenance, observed quantities, derived velocities, unbound probabilities, and method chains. JSON remains the source of truth; this site is the review and demo layer.</p>
          </div>
        </header>
        <nav class="top-nav" aria-label="Main navigation">
          <a class="nav-pill ${active === "home" ? "is-active" : ""}" href="#">Catalog</a>
          <a class="nav-pill" href="#catalog-index">Index</a>
          <a class="nav-pill" href="#method-notes">Methods</a>
          <a class="nav-pill" href="#provenance">Provenance</a>
        </nav>
        <main class="main-content">${content}</main>
      </div>
    `;
  }

  function metric(label, value) {
    return `
      <div class="metric">
        <span class="metric-value">${escapeHtml(value == null ? "" : value)}</span>
        <span class="metric-label">${escapeHtml(label)}</span>
      </div>
    `;
  }

  function renderSourceLines(row, valueGetter) {
    const lines = row.sources
      .map((source) => {
        const content = valueGetter(source);
        if (!compact(content)) {
          return "";
        }
        return `
          <div class="source-line">
            <span class="source-tag">${escapeHtml(source.source)}</span>
            <span>${content}</span>
          </div>
        `;
      })
      .join("");
    return lines || "";
  }

  function rowSearchText(row) {
    return [
      row.object_id,
      row.identifier,
      row.identifier_kind,
      ...(row.gaia_source_ids || []),
      ...(row.paper_candidate_ids || []),
      ...(row.bibcodes || []),
      ...row.sources.flatMap((source) => [
        source.record_id,
        source.paper_candidate_id,
        source.gaia_source_id,
        source.arxiv_id,
        source.bibcode,
        source.total_velocity,
        source.unbound_probability,
        ...Object.values(source.phase_space || {})
      ])
    ]
      .join(" ")
      .toLowerCase();
  }

  function filteredRows() {
    const query = state.filter.trim().toLowerCase();
    let rows = query ? state.rows.filter((row) => rowSearchText(row).includes(query)) : [...state.rows];
    const factor = state.sortDir === "asc" ? 1 : -1;
    rows.sort((left, right) => {
      let a = "";
      let b = "";
      if (state.sortKey === "source_count" || state.sortKey === "warning_count") {
        a = Number(left[state.sortKey] || 0);
        b = Number(right[state.sortKey] || 0);
        return (a - b) * factor;
      }
      if (state.sortKey === "bibcode") {
        a = (left.bibcodes || []).join(" ");
        b = (right.bibcodes || []).join(" ");
      } else {
        a = compact(left[state.sortKey]);
        b = compact(right[state.sortKey]);
      }
      return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }) * factor;
    });
    return rows;
  }

  function renderIdentifier(row) {
    return `
      <span class="identifier-main">${escapeHtml(row.identifier)}</span>
    `;
  }

  function renderCatalogTable() {
    const rows = filteredRows();
    const sourceRowCount = rows.reduce((total, row) => total + Math.max(1, row.sources.length), 0);
    const body = rows
      .map((row) => {
        const sources = row.sources.length ? row.sources : [{}];
        return sources
          .map((source, index) => {
            const span = sources.length;
            return `
              <tr class="${index === 0 ? "object-start" : "object-continuation"}">
                ${
                  index === 0
                    ? `<td class="identifier-cell" rowspan="${span}">${renderIdentifier(row)}</td>`
                    : ""
                }
                <td>${escapeHtml(source.bibcode || "")}</td>
                <td>${escapeHtml((source.phase_space || {}).ra || "")}</td>
                <td>${escapeHtml((source.phase_space || {}).dec || "")}</td>
                <td>${escapeHtml((source.phase_space || {}).parallax || "")}</td>
                <td>${escapeHtml((source.phase_space || {}).proper_motion_ra || "")}</td>
                <td>${escapeHtml((source.phase_space || {}).proper_motion_dec || "")}</td>
                <td>${escapeHtml((source.phase_space || {}).radial_velocity || "")}</td>
                <td>${escapeHtml(source.total_velocity || "")}</td>
                <td>${escapeHtml(source.unbound_probability || "")}</td>
                ${
                  index === 0
                    ? `<td rowspan="${span}">${escapeHtml(row.warning_count || "")}</td>
                       <td rowspan="${span}"><a class="more-link" href="#/object/${encodeURIComponent(row.object_id)}">Learn more</a></td>`
                    : ""
                }
              </tr>
            `;
          })
          .join("");
      })
      .join("");
    return `
      <div class="catalog-tools" id="catalog-index">
        <div>
          <h2 class="section-heading">High-Velocity-Star Object Index</h2>
          <div class="table-count">Showing ${rows.length} of ${state.rows.length} objects · ${sourceRowCount} source rows</div>
        </div>
        <div class="search-box">
          <label for="catalog-search">Search:</label>
          <input id="catalog-search" type="search" value="${escapeHtml(state.filter)}" autocomplete="off">
        </div>
      </div>
      <div class="table-wrap">
        <table class="catalog-table">
          <colgroup>
            <col class="col-identifier">
            <col class="col-bibcode">
            <col class="col-ra">
            <col class="col-dec">
            <col class="col-plx">
            <col class="col-pm">
            <col class="col-pm">
            <col class="col-rv">
            <col class="col-total-velocity">
            <col class="col-probability">
            <col class="col-small">
            <col class="col-more">
          </colgroup>
          <thead>
            <tr>
              <th><button class="sort-button" data-sort="identifier">Identifier</button></th>
              <th><button class="sort-button" data-sort="bibcode">Bibcode</button></th>
              <th>RA (deg/hms)</th>
              <th>Dec (deg)</th>
              <th>plx (mas)</th>
              <th>pmRA (mas yr^-1)</th>
              <th>pmDec (mas yr^-1)</th>
              <th>RV (km s^-1)</th>
              <th>Total velocity (km s^-1)</th>
              <th>P(unbound)</th>
              <th><button class="sort-button" data-sort="warning_count">Warnings</button></th>
              <th>More</th>
            </tr>
          </thead>
          <tbody>${body || `<tr><td colspan="12"><div class="empty-state">No matching objects.</div></td></tr>`}</tbody>
        </table>
      </div>
    `;
  }

  function renderHome() {
    const summary = (state.index && state.index.summary) || {};
    const content = `
      <section class="intro-grid">
        <div class="vision-panel">
          <h2>Vision and Current Status</h2>
          <p>Stella is building a traceable, reproducible, and continuously updated object-level data and knowledge system for high-velocity-star research. This page merges paper-level HVS/unbound candidate extractions into an object catalog and places sources, quantities, and method chains in one review interface.</p>
          <p>The web page is not the source of truth; <code>catalog/candidates/*.json</code> is. The live version reflects catalog updates after refresh, while the static version shares the current snapshot.</p>
        </div>
        <div class="metrics">
          ${metric("Objects", summary.object_count)}
          ${metric("Sources", summary.source_count)}
          ${metric("Candidate records", summary.candidate_count)}
          ${metric("Objects with Gaia IDs", summary.objects_with_gaia_count)}
          ${metric("Warnings", summary.warning_count)}
          ${metric("Skipped inputs", summary.skipped_count)}
        </div>
      </section>
      ${renderCatalogTable()}
      <section class="section-band" id="method-notes">
        <h2 class="section-heading">Method Chain</h2>
        <p>Each object detail page shows a per-source method DAG. Click a DAG node to inspect its summary; click any quantity to highlight the direct method reference, recursive upstream dependencies, and dependency edges.</p>
      </section>
      <section class="section-band" id="provenance">
        <h2 class="section-heading">Provenance</h2>
        <p>Object pages show source cards, candidate core fields, method chains, and the full object-level JSON. The object JSON keeps a compact core; full per-value source references remain in the corresponding paper-level <code>literature_hvs_candidates.json</code>.</p>
      </section>
    `;
    app.innerHTML = shell(content, "home");
  }

  function sourceById(record, sourceId) {
    return (record.sources || []).find((source) => source && source.source === sourceId) || {};
  }

  function methodGroupBySource(record, sourceId) {
    return (record.method_chain || []).find((group) => group && group.source === sourceId) || { source: sourceId, steps: [] };
  }

  function renderSourceCards(record) {
    return `
      <section class="section-band">
        <h2 class="section-heading">Sources</h2>
        <div class="source-cards">
          ${(record.sources || [])
            .map((source) => {
              const paper = source.paper || {};
              const links = paper.links || {};
              return `
                <article class="source-card">
                  <span class="source-tag">${escapeHtml(source.source)}</span>
                  <h3>${escapeHtml(paper.title || "Untitled source")}</h3>
                  <dl>
                    <dt>arXiv</dt><dd>${paper.arxiv_id ? `<a href="${escapeHtml(links.abs || "https://arxiv.org/abs/" + paper.arxiv_id)}">${escapeHtml(paper.arxiv_id)}</a>` : ""}</dd>
                    <dt>PDF</dt><dd>${links.pdf ? `<a href="${escapeHtml(links.pdf)}">PDF</a>` : ""}</dd>
                    <dt>bibcode</dt><dd>${escapeHtml(paper.bibcode || "")}</dd>
                    <dt>record_id</dt><dd>${escapeHtml(source.record_id || "")}</dd>
                    <dt>paper ID</dt><dd>${escapeHtml(source.paper_candidate_id || "")}</dd>
                    <dt>Gaia source ID</dt><dd>${escapeHtml(source.gaia_source_id || "")}</dd>
                    <dt>source JSON</dt><dd>${escapeHtml(source.source_json_path || "")}</dd>
                  </dl>
                </article>
              `;
            })
            .join("")}
        </div>
      </section>
    `;
  }

  function formatQuantityDetail(quantity) {
    const value = quantityText(quantity);
    return escapeHtml(value);
  }

  function quantityLabel(field, quantity, index) {
    const parts = [
      compact(quantity.name),
      compact(quantity.element),
      compact(quantity.hypothesis),
      compact(quantity.measurement_type),
      compact(quantity.band),
      compact(quantity.spectral_type),
      compact(quantity.line),
      compact(quantity.metric_type)
    ].filter(Boolean);
    if (parts.length) {
      return parts.join(" · ");
    }
    return FIELD_LABELS[field] || field || "item " + String(index + 1);
  }

  function renderQuantityRow(record, candidate, field, quantity, index) {
    const refs = (quantity.method_refs || []).map(compact).filter(Boolean);
    const active =
      state.activeLineage &&
      state.activeLineage.source === candidate.source &&
      refs.some((ref) => state.activeLineage.direct.has(ref));
    return `
      <div class="quantity-row">
        <button class="quantity-button ${active ? "is-active" : ""}" data-source="${escapeHtml(candidate.source)}" data-method-refs="${escapeHtml(refs.join(","))}">
          ${escapeHtml(quantityLabel(field, quantity, index))}
        </button>
        <div class="quantity-value">${formatQuantityDetail(quantity)}</div>
      </div>
    `;
  }

  function renderQuantityGroup(record, candidate, groupName, group) {
    const entries = Object.entries(group || {}).filter(([, quantity]) => quantity && typeof quantity === "object" && !Array.isArray(quantity));
    if (!entries.length) {
      return "";
    }
    return `
      <div class="quantity-group">
        <h4>${escapeHtml(GROUP_LABELS[groupName] || groupName)}</h4>
        ${entries
          .map(([field, quantity], index) => renderQuantityRow(record, candidate, field, quantity, index))
          .join("")}
      </div>
    `;
  }

  function renderQuantityList(record, candidate, groupName, records) {
    const entries = (records || []).filter((quantity) => quantity && typeof quantity === "object" && !Array.isArray(quantity));
    if (!entries.length) {
      return "";
    }
    return `
      <div class="quantity-group">
        <h4>${escapeHtml(GROUP_LABELS[groupName] || groupName)}</h4>
        ${entries.map((quantity, index) => renderQuantityRow(record, candidate, "", quantity, index)).join("")}
      </div>
    `;
  }

  function renderCandidateContext(context) {
    if (!context || typeof context !== "object") {
      return "";
    }
    const citation = context.citation || {};
    return `
      <dl class="json-dl">
        <dt>paper labels</dt><dd>${escapeHtml((context.paper_labels || []).join(", "))}</dd>
        <dt>bound claim</dt><dd>${escapeHtml(context.galactic_bound_claim || "")}</dd>
        <dt>basis</dt><dd>${escapeHtml(context.inclusion_basis || "")}</dd>
        <dt>confidence</dt><dd>${escapeHtml(context.extraction_confidence || "")}</dd>
        <dt>origin type</dt><dd>${escapeHtml(context.origin_type || "")}</dd>
        <dt>reassesses status</dt><dd>${context.paper_reassesses_unbound_status ? "true" : "false"}</dd>
        ${citation && Object.keys(citation).length ? `<dt>citation</dt><dd>${escapeHtml([citation.bibkey, citation.year, citation.bibcode || citation.arxiv_id].filter(Boolean).join(" · "))}</dd>` : ""}
      </dl>
    `;
  }

  function renderCandidateCore(record) {
    return `
      <section class="section-band">
        <h2 class="section-heading">Candidate Records</h2>
        <div class="core-grid">
          ${(record.candidates || [])
            .map((candidate) => {
              const identifiers = candidate.identifiers || {};
              const core = candidate.core || {};
              const stellar = candidate.stellar_parameters || {};
              const orbit = candidate.orbit || {};
              const origin = candidate.astrophysical_origin || {};
              return `
                <article class="candidate-core">
                  <h3><span class="source-tag">${escapeHtml(candidate.source)}</span> ${escapeHtml(identifiers.paper_candidate_id || identifiers.record_id || "")}</h3>
                  <dl class="json-dl">
                    <dt>record_id</dt><dd>${escapeHtml(identifiers.record_id || "")}</dd>
                    <dt>paper_candidate_id</dt><dd>${escapeHtml(identifiers.paper_candidate_id || "")}</dd>
                    <dt>gaia_source_id</dt><dd>${escapeHtml(identifiers.gaia_source_id || "")}</dd>
                  </dl>
                  ${renderCandidateContext(candidate.candidate_context)}
                  ${renderQuantityGroup(record, candidate, "observed_phase_space", core.observed_phase_space)}
                  ${renderQuantityGroup(record, candidate, "derived_kinematics", core.derived_kinematics)}
                  ${renderQuantityGroup(record, candidate, "bound_assessment", core.bound_assessment)}
                  ${renderQuantityList(record, candidate, "photometry", candidate.photometry)}
                  ${renderQuantityList(record, candidate, "spectroscopy", candidate.spectroscopy)}
                  ${renderQuantityGroup(record, candidate, "stellar_parameters", stellar)}
                  ${renderQuantityList(record, candidate, "stellar_parameters", stellar.other)}
                  ${renderQuantityList(record, candidate, "abundances", candidate.abundances)}
                  ${renderQuantityList(record, candidate, "quality_flags", candidate.quality_flags)}
                  ${renderQuantityGroup(record, candidate, "orbit", orbit)}
                  ${renderQuantityList(record, candidate, "orbit", orbit.other)}
                  ${renderQuantityGroup(record, candidate, "astrophysical_origin", origin)}
                  ${renderQuantityList(record, candidate, "hypothesis_metrics", origin.hypothesis_metrics)}
                  ${renderQuantityList(record, candidate, "astrophysical_origin", origin.other)}
                  ${renderQuantityList(record, candidate, "extra", candidate.extra)}
                </article>
              `;
            })
            .join("")}
        </div>
      </section>
    `;
  }

  function stepDepth(stepId, byId, memo, visiting) {
    if (memo.has(stepId)) {
      return memo.get(stepId);
    }
    if (visiting.has(stepId)) {
      return 0;
    }
    visiting.add(stepId);
    const step = byId.get(stepId) || {};
    const deps = (step.depends_on || []).filter((dep) => byId.has(dep));
    const depth = deps.length ? Math.max(...deps.map((dep) => stepDepth(dep, byId, memo, visiting))) + 1 : 0;
    visiting.delete(stepId);
    memo.set(stepId, depth);
    return depth;
  }

  function truncate(text, limit) {
    const value = compact(text);
    return value.length > limit ? value.slice(0, limit - 1) + "…" : value;
  }

  function lineageFor(steps, refs) {
    const byId = new Map(steps.map((step) => [compact(step.id), step]));
    const direct = new Set(refs.filter((ref) => byId.has(ref)));
    const ancestors = new Set();
    const edges = new Set();
    function visit(stepId) {
      const step = byId.get(stepId);
      if (!step) {
        return;
      }
      (step.depends_on || []).forEach((dep) => {
        const depId = compact(dep);
        if (!byId.has(depId)) {
          return;
        }
        edges.add(depId + "->" + stepId);
        if (!direct.has(depId)) {
          ancestors.add(depId);
        }
        visit(depId);
      });
    }
    direct.forEach(visit);
    return { direct, ancestors, edges };
  }

  function renderDagSvg(sourceId, steps) {
    if (!steps.length) {
      return `<div class="empty-state">This source has no method_chain.</div>`;
    }
    const byId = new Map(steps.map((step) => [compact(step.id), step]));
    const memo = new Map();
    const layers = new Map();
    steps.forEach((step) => {
      const id = compact(step.id);
      const depth = stepDepth(id, byId, memo, new Set());
      if (!layers.has(depth)) {
        layers.set(depth, []);
      }
      layers.get(depth).push(step);
    });
    const sortedLayers = [...layers.entries()].sort((a, b) => a[0] - b[0]);
    const nodeWidth = 158;
    const nodeHeight = 38;
    const xGap = 178;
    const yGap = 54;
    const positions = new Map();
    let maxLayerSize = 1;
    sortedLayers.forEach(([depth, layer]) => {
      maxLayerSize = Math.max(maxLayerSize, layer.length);
    });
    sortedLayers.forEach(([depth, layer]) => {
      const layerOffset = ((maxLayerSize - layer.length) * xGap) / 2;
      layer.forEach((step, index) => {
        positions.set(compact(step.id), { x: 32 + layerOffset + index * xGap, y: 28 + depth * yGap });
      });
    });
    const width = Math.max(520, 64 + maxLayerSize * xGap);
    const height = Math.max(140, 70 + sortedLayers.length * yGap);
    const active = state.activeLineage && state.activeLineage.source === sourceId ? state.activeLineage : null;
    const selected = state.selectedStep && state.selectedStep.source === sourceId ? state.selectedStep.stepId : "";
    const edges = [];
    steps.forEach((step) => {
      const to = compact(step.id);
      const toPos = positions.get(to);
      (step.depends_on || []).forEach((dep) => {
        const from = compact(dep);
        const fromPos = positions.get(from);
        if (!fromPos || !toPos) {
          return;
        }
        const key = from + "->" + to;
        edges.push(`
          <line class="dag-edge ${active && active.edges.has(key) ? "is-active" : ""}"
            x1="${fromPos.x + nodeWidth / 2}" y1="${fromPos.y + nodeHeight}"
            x2="${toPos.x + nodeWidth / 2}" y2="${toPos.y}" />
        `);
      });
    });
    const nodes = steps
      .map((step) => {
        const id = compact(step.id);
        const pos = positions.get(id);
        const classes = ["dag-node"];
        if (id === selected) {
          classes.push("is-selected");
        }
        if (active && active.direct.has(id)) {
          classes.push("is-direct");
        } else if (active && active.ancestors.has(id)) {
          classes.push("is-ancestor");
        }
        return `
          <g class="${classes.join(" ")}" data-source="${escapeHtml(sourceId)}" data-step="${escapeHtml(id)}">
            <rect x="${pos.x}" y="${pos.y}" width="${nodeWidth}" height="${nodeHeight}" rx="3"></rect>
            <text x="${pos.x + 9}" y="${pos.y + 14}">${escapeHtml(id)}</text>
            <text x="${pos.x + 9}" y="${pos.y + 29}">${escapeHtml(truncate(step.step_type || "method", 20))}</text>
          </g>
        `;
      })
      .join("");
    return `<div class="dag-scroll"><svg class="dag-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Method DAG">${edges.join("")}${nodes}</svg></div>`;
  }

  function selectedStepForSource(sourceId, steps) {
    if (!state.selectedStep || state.selectedStep.source !== sourceId) {
      return null;
    }
    return steps.find((step) => compact(step.id) === state.selectedStep.stepId) || null;
  }

  function renderMethodPanel(step) {
    if (!step) {
      return `
        <aside class="method-panel">
          <h4>Select a node</h4>
          <p>Click a DAG node to inspect its summary. Click a quantity below to return here and highlight the corresponding lineage.</p>
        </aside>
      `;
    }
    const list = (title, values) => {
      const items = (values || []).map((value) => `<li>${escapeHtml(value)}</li>`).join("");
      return items ? `<strong>${escapeHtml(title)}</strong><ul class="method-list">${items}</ul>` : "";
    };
    return `
      <aside class="method-panel">
        <h4>${escapeHtml(step.id)} · ${escapeHtml(step.step_type || "")}</h4>
        <p>${escapeHtml(step.summary || "")}</p>
        ${list("Inputs", step.inputs)}
        ${list("Outputs", step.outputs)}
        ${list("Depends on", step.depends_on)}
      </aside>
    `;
  }

  function renderMethodChains(record) {
    return `
      <section class="section-band" id="method-chain">
        <h2 class="section-heading">Method Chain DAG</h2>
        ${(record.method_chain || [])
          .map((group) => {
            const source = sourceById(record, group.source);
            const steps = group.steps || [];
            return `
              <article class="method-source" id="method-source-${escapeHtml(group.source)}">
                <h3><span class="source-tag">${escapeHtml(group.source)}</span> ${escapeHtml((source.paper || {}).bibcode || (source.paper || {}).arxiv_id || "")}</h3>
                <div class="method-layout">
                  ${renderDagSvg(group.source, steps)}
                  ${renderMethodPanel(selectedStepForSource(group.source, steps))}
                </div>
              </article>
            `;
          })
          .join("")}
      </section>
    `;
  }

  function renderRawJson(record) {
    return `
      <details class="raw-json">
        <summary>Full object-level JSON</summary>
        <pre>${escapeHtml(JSON.stringify(record, null, 2))}</pre>
      </details>
    `;
  }

  function renderDetail(objectId) {
    const record = state.objectMap.get(objectId);
    if (!record) {
      app.innerHTML = shell(`<div class="error">Object not found: ${escapeHtml(objectId)}</div>`, "detail");
      return;
    }
    const canonical = record.canonical_identifier || {};
    const content = `
      <section class="detail-header">
        <div>
          <a class="back-button" href="#">Back to index</a>
          <h2 class="detail-title">${escapeHtml(canonical.value || record.object_id)}</h2>
          <div class="detail-meta">${escapeHtml(record.object_id)} · schema ${escapeHtml(record.schema_version || "")} · generated ${escapeHtml(record.generated_at || "")}</div>
        </div>
      </section>
      ${renderSourceCards(record)}
      ${renderMethodChains(record)}
      ${renderCandidateCore(record)}
      ${renderRawJson(record)}
    `;
    app.innerHTML = shell(content, "detail");
  }

  function route() {
    const hash = window.location.hash || "";
    if (hash.startsWith("#/object/")) {
      const objectId = decodeURIComponent(hash.slice("#/object/".length));
      renderDetail(objectId);
    } else {
      state.selectedStep = null;
      state.activeLineage = null;
      renderHome();
    }
  }

  function rerenderDetailFromEventTarget(target) {
    const detailTitle = target.closest(".site-frame") && (window.location.hash || "").startsWith("#/object/");
    if (detailTitle) {
      route();
    }
  }

  app.addEventListener("click", (event) => {
    const sortButton = event.target.closest("[data-sort]");
    if (sortButton) {
      const key = sortButton.dataset.sort;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = "asc";
      }
      renderHome();
      return;
    }

    const node = event.target.closest(".dag-node");
    if (node) {
      state.selectedStep = { source: node.dataset.source, stepId: node.dataset.step };
      rerenderDetailFromEventTarget(node);
      return;
    }

    const quantity = event.target.closest(".quantity-button");
    if (quantity) {
      const sourceId = quantity.dataset.source;
      const refs = (quantity.dataset.methodRefs || "").split(",").map(compact).filter(Boolean);
      const objectId = decodeURIComponent((window.location.hash || "").slice("#/object/".length));
      const record = state.objectMap.get(objectId);
      const group = record ? methodGroupBySource(record, sourceId) : { steps: [] };
      const lineage = lineageFor(group.steps || [], refs);
      state.activeLineage = { source: sourceId, direct: lineage.direct, ancestors: lineage.ancestors, edges: lineage.edges };
      state.selectedStep = refs.length ? { source: sourceId, stepId: refs[0] } : null;
      rerenderDetailFromEventTarget(quantity);
      window.requestAnimationFrame(() => {
        const target = document.getElementById("method-source-" + sourceId) || document.getElementById("method-chain");
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    }
  });

  app.addEventListener("input", (event) => {
    if (event.target && event.target.id === "catalog-search") {
      state.filter = event.target.value;
      renderHome();
      const input = document.getElementById("catalog-search");
      if (input) {
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      }
    }
  });

  window.addEventListener("hashchange", route);

  async function main() {
    app.innerHTML = `<div class="site-frame"><div class="loading">Loading Stella HVS catalog...</div></div>`;
    try {
      await loadData();
      route();
    } catch (error) {
      app.innerHTML = `<div class="site-frame"><div class="error">Unable to load catalog: ${escapeHtml(error.message || error)}</div></div>`;
    }
  }

  main();
})();
