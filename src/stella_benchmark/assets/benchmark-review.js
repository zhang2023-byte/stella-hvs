/* Expert review UI for the Stella HVS extraction benchmark.
 * Loads alignment JSON, lets the expert record verdicts, and autosaves them
 * to the local review server (POST /api/verdicts/<arxiv_id>). */
(function () {
  "use strict";

  const body = document.body;
  const config = {
    alignmentIndex: body.dataset.alignmentIndex,
    alignmentBase: body.dataset.alignmentBase,
    adjudicationBase: body.dataset.adjudicationBase,
    verdictApi: body.dataset.verdictApi,
  };

  const state = {
    index: null,
    expert: null,
    arxivId: null,
    alignment: null,
    items: new Map(),
    paperStatusVerdict: null,
    saveTimer: null,
    additionCounter: 0,
  };

  const paperList = document.getElementById("paper-list");
  const paperView = document.getElementById("paper-view");
  const sessionLine = document.getElementById("session-line");

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value);
    });
    (children || []).forEach((child) => child && node.appendChild(child));
    return node;
  }

  async function fetchJson(url, allow404) {
    const response = await fetch(url, { cache: "no-store" });
    if (allow404 && response.status === 404) return null;
    if (!response.ok) throw new Error(url + " -> HTTP " + response.status);
    return response.json();
  }

  function requiredItemIds(alignment) {
    const ids = [];
    (alignment.clusters || []).forEach((cluster) => {
      ids.push(cluster.cluster_id);
      (cluster.fields || []).forEach((field) => {
        if (!field.agreement) ids.push(cluster.cluster_id + ":" + field.field_path);
      });
    });
    (alignment.consensus_spot_checks || []).forEach((id) => {
      if (!ids.includes(id)) ids.push(id);
    });
    return ids;
  }

  function progressFor(alignment, adjudication) {
    const required = requiredItemIds(alignment);
    const decided = new Set(((adjudication || {}).items || []).map((item) => item.item_id));
    let done = required.filter((id) => decided.has(id)).length;
    let total = required.length + 1; // + paper status
    if ((adjudication || {}).paper_status_verdict) done += 1;
    return { done, total };
  }

  function banner(message, isError) {
    let node = paperView.querySelector(".status-banner");
    if (!node) {
      node = el("div", { class: "status-banner" });
      paperView.prepend(node);
    }
    node.textContent = message;
    node.classList.toggle("error", Boolean(isError));
  }

  function scheduleSave() {
    if (state.saveTimer) clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(save, 400);
  }

  async function save() {
    if (!state.arxivId || !state.alignment) return;
    const payload = {
      alignment_digest: state.alignment.alignment_digest,
      paper_status_verdict: state.paperStatusVerdict,
      items: Array.from(state.items.values()),
    };
    try {
      const response = await fetch(config.verdictApi + state.arxivId, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (response.status === 409) {
        banner("Alignment changed on disk - rebuild the review site and reload. Verdicts NOT saved.", true);
        return;
      }
      if (!response.ok) {
        const text = await response.text();
        banner("Save failed (HTTP " + response.status + "): " + text.slice(0, 200), true);
        return;
      }
      banner("Saved " + new Date().toLocaleTimeString());
      refreshListProgress();
    } catch (error) {
      banner("Save failed: " + error, true);
    }
  }

  function setItem(itemId, item) {
    item.item_id = itemId;
    state.items.set(itemId, item);
    scheduleSave();
  }

  function variantValueText(value) {
    if (value === null || value === undefined) return "(absent)";
    if (typeof value === "object" && !Array.isArray(value)) {
      const parts = [];
      if (value.value !== undefined) {
        let text = value.value || "(empty)";
        if (value.error) text += " +/- " + value.error;
        if (value.lower_error || value.upper_error) {
          text += " -" + (value.lower_error || "?") + " +" + (value.upper_error || "?");
        }
        if (value.unit) text += " [" + value.unit + "]";
        parts.push(text);
        if (value.raw_value && value.raw_value !== value.value) parts.push("raw: " + value.raw_value);
      } else {
        parts.push(JSON.stringify(value));
      }
      return parts.join("\n");
    }
    if (Array.isArray(value)) return value.join("\n") || "(empty)";
    return String(value);
  }

  function evidenceNodes(field) {
    const nodes = [];
    Object.entries(field.evidence || {}).forEach(([variantId, refs]) => {
      refs.forEach((ref) => {
        let text;
        let src;
        if (ref.kind === "ecsv_cell") {
          src = variantId + " | " + ref.path + ":" + ref.line + " [" + (ref.column_header || ref.column) + "]";
          const cells = Object.entries(ref.row_cells || {})
            .map(([name, cell]) => (name === ref.column ? ">> " : "") + name + "=" + cell)
            .join("  ");
          text = cells || ref.raw_value;
        } else {
          src = variantId + " | " + ref.path + ":" + ref.start_line + "-" + ref.end_line;
          text = (ref.lines || []).join("\n");
        }
        if (ref.error) text = "(evidence error: " + ref.error + ")";
        nodes.push(
          el("div", { class: "evidence-block" }, [
            el("span", { class: "src", text: src }),
            el("div", { text: "\n" + text }),
          ])
        );
      });
    });
    return nodes;
  }

  function verdictButton(label, selected, onClick, danger) {
    return el("button", {
      class: (selected ? "selected " : "") + (danger ? "danger-action" : ""),
      text: label,
      onclick: onClick,
    });
  }

  function rationaleInput(existing, onChange) {
    return el("input", {
      type: "text",
      placeholder: "rationale (required for fix/reject/add)",
      value: (existing && existing.rationale) || "",
      onchange: (event) => onChange(event.target.value),
    });
  }

  function jsonEditor(initialValue, onApply) {
    const editor = el("textarea", { class: "json-editor" });
    editor.value = JSON.stringify(initialValue, null, 2);
    const apply = el("button", {
      text: "Apply JSON",
      onclick: () => {
        try {
          onApply(JSON.parse(editor.value));
          editor.classList.remove("error");
          banner("Payload applied - saving");
        } catch (error) {
          banner("Invalid JSON: " + error, true);
        }
      },
    });
    return el("div", {}, [editor, el("div", { class: "verdict-row" }, [apply])]);
  }

  function renderFieldRow(cluster, field, spotSet) {
    const itemId = cluster.cluster_id + ":" + field.field_path;
    const existing = state.items.get(itemId);
    const isSpot = spotSet.has(itemId);
    const required = !field.agreement || isSpot;

    const row = el("div", { class: "field-row" + (field.agreement ? " agree" : "") });
    const header = el("div", {}, [
      el("span", { class: "field-path", text: field.field_path }),
    ]);
    if (isSpot) header.appendChild(el("span", { class: "badge warn", text: "spot check" }));
    if (!field.agreement) header.appendChild(el("span", { class: "badge danger", text: "disagreement" }));
    if (existing) header.appendChild(el("span", { class: "badge ok", text: existing.verdict }));
    else if (required) header.appendChild(el("span", { class: "required-tag", text: " verdict required" }));
    row.appendChild(header);

    const grid = el("div", { class: "value-grid" });
    Object.entries(field.values || {}).forEach(([variantId, value]) => {
      grid.appendChild(
        el("div", { class: "value-cell" }, [
          el("span", { class: "variant-name", text: variantId }),
          el("span", { text: variantValueText(value) }),
        ])
      );
    });
    row.appendChild(grid);
    evidenceNodes(field).forEach((node) => row.appendChild(node));

    const controls = el("div", { class: "verdict-row" });
    const base = (item) => ({
      kind: "field_value",
      cluster_id: cluster.cluster_id,
      field_path: field.field_path,
      rationale: (existing && existing.rationale) || "",
      ...item,
    });
    controls.appendChild(
      verdictButton("Accept", existing && existing.verdict === "accept", () =>
        setItem(itemId, base({ verdict: "accept" }))
      )
    );
    const variantIds = Object.keys(field.values || {});
    if (variantIds.length > 1) {
      const select = el("select", {});
      select.appendChild(el("option", { value: "", text: "accept variant…" }));
      variantIds.forEach((variantId) =>
        select.appendChild(el("option", { value: variantId, text: variantId }))
      );
      if (existing && existing.verdict === "accept_variant") select.value = existing.accepted_from_variant;
      select.addEventListener("change", () => {
        if (select.value)
          setItem(itemId, base({ verdict: "accept_variant", accepted_from_variant: select.value }));
      });
      controls.appendChild(select);
    }
    const fixButton = verdictButton("Fix…", existing && existing.verdict === "fix", () => {
      const seed =
        (existing && existing.fixed_payload) ||
        Object.values(field.values || {}).find((value) => value && typeof value === "object") ||
        {};
      const editorWrap = jsonEditor(seed, (payload) =>
        setItem(itemId, base({ verdict: "fix", fixed_payload: payload }))
      );
      row.appendChild(editorWrap);
    });
    controls.appendChild(fixButton);
    controls.appendChild(
      verdictButton(
        "Reject field",
        existing && existing.verdict === "reject_field",
        () => setItem(itemId, base({ verdict: "reject_field" })),
        true
      )
    );
    controls.appendChild(
      rationaleInput(existing, (value) => {
        const item = state.items.get(itemId);
        if (item) {
          item.rationale = value;
          scheduleSave();
        }
      })
    );
    row.appendChild(controls);
    return row;
  }

  function renderCluster(cluster, spotSet) {
    const card = el("div", { class: "cluster-card" });
    const existing = state.items.get(cluster.cluster_id);
    const title = el("h3", {
      text:
        (cluster.identifier_summary.display || cluster.identifier_summary.gaia_source_id || cluster.cluster_id),
    });
    title.appendChild(el("span", { class: "badge", text: cluster.matched_by }));
    (cluster.missing_in || []).forEach((variantId) =>
      title.appendChild(el("span", { class: "badge warn", text: "missing in " + variantId }))
    );
    if (cluster.conflict) title.appendChild(el("span", { class: "badge danger", text: "conflict" }));
    if (existing) title.appendChild(el("span", { class: "badge ok", text: existing.verdict }));
    card.appendChild(title);
    if (cluster.identifier_summary.all_values.length) {
      card.appendChild(
        el("p", {
          class: "field-path",
          text: "identifiers: " + cluster.identifier_summary.all_values.join(", "),
        })
      );
    }

    const presence = el("div", { class: "verdict-row" });
    const members = Object.keys(cluster.members || {});
    const baseSelect = el("select", {});
    members.forEach((variantId) =>
      baseSelect.appendChild(el("option", { value: variantId, text: "base: " + variantId }))
    );
    if (existing && existing.base_variant) baseSelect.value = existing.base_variant;
    presence.appendChild(
      verdictButton("Accept candidate", existing && existing.verdict === "accept", () =>
        setItem(cluster.cluster_id, {
          kind: "candidate_presence",
          cluster_id: cluster.cluster_id,
          verdict: "accept",
          base_variant: baseSelect.value || members[0] || "",
          rationale: (existing && existing.rationale) || "",
        })
      )
    );
    presence.appendChild(baseSelect);
    presence.appendChild(
      verdictButton(
        "Reject candidate",
        existing && existing.verdict === "reject",
        () =>
          setItem(cluster.cluster_id, {
            kind: "candidate_presence",
            cluster_id: cluster.cluster_id,
            verdict: "reject",
            rationale: (existing && existing.rationale) || "",
          }),
        true
      )
    );
    presence.appendChild(
      rationaleInput(existing, (value) => {
        const item = state.items.get(cluster.cluster_id);
        if (item) {
          item.rationale = value;
          scheduleSave();
        }
      })
    );
    card.appendChild(presence);

    const openFields = [];
    const collapsedFields = [];
    (cluster.fields || []).forEach((field) => {
      const itemId = cluster.cluster_id + ":" + field.field_path;
      if (!field.agreement || spotSet.has(itemId)) openFields.push(field);
      else collapsedFields.push(field);
    });
    openFields.forEach((field) => card.appendChild(renderFieldRow(cluster, field, spotSet)));
    if (collapsedFields.length) {
      const holder = el("div", { style: "display:none" });
      collapsedFields.forEach((field) => holder.appendChild(renderFieldRow(cluster, field, spotSet)));
      const toggle = el("button", {
        class: "toggle-fields",
        text: "Show " + collapsedFields.length + " agreeing fields",
        onclick: () => {
          const hidden = holder.style.display === "none";
          holder.style.display = hidden ? "" : "none";
          toggle.textContent = (hidden ? "Hide " : "Show ") + collapsedFields.length + " agreeing fields";
        },
      });
      card.appendChild(toggle);
      card.appendChild(holder);
    }
    return card;
  }

  function renderPaperStatus(alignment) {
    const card = el("div", { class: "paper-status-card" });
    card.appendChild(el("h3", { text: "Paper status" }));
    const grid = el("div", { class: "value-grid" });
    Object.entries(alignment.paper_status.values).forEach(([variantId, status]) => {
      grid.appendChild(
        el("div", { class: "value-cell" }, [
          el("span", { class: "variant-name", text: variantId }),
          el("span", { text: status }),
        ])
      );
    });
    card.appendChild(grid);

    const controls = el("div", { class: "verdict-row" });
    const select = el("select", {});
    ["candidates_found", "no_candidates", "partial", "needs_review", "source_missing"].forEach(
      (status) => select.appendChild(el("option", { value: status, text: status }))
    );
    const existing = state.paperStatusVerdict;
    const consensus = Object.values(alignment.paper_status.values)[0] || "candidates_found";
    select.value = (existing && existing.gold_status) || consensus;
    const setStatus = (verdict) => {
      state.paperStatusVerdict = {
        verdict: verdict,
        gold_status: select.value,
        rationale: (state.paperStatusVerdict && state.paperStatusVerdict.rationale) || "",
      };
      scheduleSave();
      renderPaper();
    };
    controls.appendChild(
      verdictButton("Accept status", existing && existing.verdict === "accept", () => setStatus("accept"))
    );
    controls.appendChild(select);
    controls.appendChild(
      verdictButton("Set corrected status", existing && existing.verdict === "fix", () => setStatus("fix"))
    );
    if (existing) controls.appendChild(el("span", { class: "badge ok", text: existing.gold_status }));
    card.appendChild(controls);
    return card;
  }

  function renderRecall(alignment) {
    const rows = (alignment.recall_assists || {}).uncovered_ecsv_rows || [];
    const card = el("div", { class: "recall-card" });
    card.appendChild(el("h3", { text: "Uncovered table rows (" + rows.length + ")" }));
    card.appendChild(
      el("p", {
        class: "field-path",
        text: "Data rows in candidate-referenced ECSV tables that no variant cites - check for missed candidates.",
      })
    );
    rows.forEach((row) => {
      card.appendChild(
        el("div", { class: "uncovered-row", text: row.path + ":" + row.line + "  " + row.row_preview })
      );
    });
    const addButton = el("button", {
      class: "toggle-fields",
      text: "Add missing candidate…",
      onclick: () => {
        state.additionCounter += 1;
        let itemId = "missing-" + String(state.additionCounter).padStart(3, "0");
        while (state.items.has(itemId)) {
          state.additionCounter += 1;
          itemId = "missing-" + String(state.additionCounter).padStart(3, "0");
        }
        const editorWrap = jsonEditor(
          { identifiers: { record_id: "", paper_candidate_id: "", gaia_source_id: "", all: [] } },
          (payload) =>
            setItem(itemId, {
              kind: "candidate_addition",
              verdict: "add_missing",
              added_payload: payload,
              rationale: "",
            })
        );
        card.appendChild(el("p", { class: "field-path", text: itemId + " (paste a full v7 candidate record)" }));
        card.appendChild(editorWrap);
      },
    });
    card.appendChild(addButton);
    Array.from(state.items.values())
      .filter((item) => item.kind === "candidate_addition")
      .forEach((item) =>
        card.appendChild(el("p", { class: "field-path", text: item.item_id + ": " + item.verdict }))
      );
    return card;
  }

  function renderPaper() {
    if (!state.alignment) return;
    const alignment = state.alignment;
    paperView.textContent = "";
    banner("Loaded " + alignment.arxiv_id);
    const spotSet = new Set(alignment.consensus_spot_checks || []);

    const title = el("h2", { text: alignment.arxiv_id + " - " + (alignment.paper.title || "") });
    paperView.appendChild(title);
    if (alignment.paper.links && alignment.paper.links.abs) {
      paperView.appendChild(
        el("p", {}, [el("a", { href: alignment.paper.links.abs, target: "_blank", text: "arXiv abstract" })])
      );
    }
    paperView.appendChild(renderPaperStatus(alignment));
    (alignment.clusters || []).forEach((cluster) => paperView.appendChild(renderCluster(cluster, spotSet)));
    paperView.appendChild(renderRecall(alignment));

    const exportRow = el("div", { class: "export-row" });
    exportRow.appendChild(
      el("button", {
        text: "Export verdicts JSON",
        onclick: () => {
          const payload = {
            alignment_digest: alignment.alignment_digest,
            paper_status_verdict: state.paperStatusVerdict,
            items: Array.from(state.items.values()),
          };
          const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
          const link = el("a", {
            href: URL.createObjectURL(blob),
            download: alignment.arxiv_id + ".verdicts.json",
          });
          link.click();
        },
      })
    );
    paperView.appendChild(exportRow);
  }

  async function openPaper(arxivId) {
    state.arxivId = arxivId;
    state.items = new Map();
    state.paperStatusVerdict = null;
    state.alignment = await fetchJson(config.alignmentBase + arxivId + ".alignment.json");
    const adjudication = await fetchJson(
      config.adjudicationBase + arxivId + ".adjudication.json",
      true
    );
    if (adjudication) {
      (adjudication.items || []).forEach((item) => state.items.set(item.item_id, item));
      state.paperStatusVerdict = adjudication.paper_status_verdict || null;
      if (adjudication.alignment_digest !== state.alignment.alignment_digest) {
        banner("Existing verdicts were made against a different alignment - review them carefully.", true);
      }
    }
    renderPaper();
    document
      .querySelectorAll(".paper-list button")
      .forEach((button) => button.classList.toggle("active", button.dataset.arxivId === arxivId));
  }

  async function refreshListProgress() {
    const buttons = document.querySelectorAll(".paper-list button");
    for (const button of buttons) {
      const arxivId = button.dataset.arxivId;
      try {
        const alignment =
          arxivId === state.arxivId
            ? state.alignment
            : await fetchJson(config.alignmentBase + arxivId + ".alignment.json");
        const adjudication =
          arxivId === state.arxivId
            ? {
                items: Array.from(state.items.values()),
                paper_status_verdict: state.paperStatusVerdict,
              }
            : await fetchJson(config.adjudicationBase + arxivId + ".adjudication.json", true);
        const progress = progressFor(alignment, adjudication);
        const node = button.querySelector(".progress");
        node.textContent = progress.done + " / " + progress.total + " verdicts";
        node.classList.toggle("done", progress.done >= progress.total);
      } catch (error) {
        /* leave the row as-is when a file is unreadable */
      }
    }
  }

  async function init() {
    try {
      const session = await fetchJson("/api/session", true);
      state.expert = session && session.expert;
    } catch (error) {
      state.expert = null;
    }
    sessionLine.textContent = state.expert
      ? "Expert: " + state.expert.id + (state.expert.name ? " (" + state.expert.name + ")" : "")
      : "Static mode - verdict saving requires serve_benchmark_review.py";
    state.index = await fetchJson(config.alignmentIndex);
    paperList.textContent = "";
    (state.index.papers || []).forEach((paper) => {
      const button = el("button", { "data-arxiv-id": paper.arxiv_id, onclick: () => openPaper(paper.arxiv_id) }, [
        el("span", { text: paper.arxiv_id }),
        el("span", {
          class: "progress",
          text: paper.disagreement_field_count + " disagreements, " + paper.cluster_count + " clusters",
        }),
      ]);
      paperList.appendChild(button);
    });
    refreshListProgress();
  }

  init().catch((error) => {
    sessionLine.textContent = "Failed to load: " + error;
  });
})();
