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
    filters: {
      dynamics: "all",
      unbound: "all",
      rv: "all",
      warnings: "all"
    },
    sortKey: "p_unbound",
    sortDir: "desc",
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

  const LATEX_SYMBOLS = {
    alpha: "&alpha;",
    beta: "&beta;",
    gamma: "&gamma;",
    Gamma: "&Gamma;",
    delta: "&delta;",
    Delta: "&Delta;",
    epsilon: "&epsilon;",
    varepsilon: "&epsilon;",
    zeta: "&zeta;",
    eta: "&eta;",
    theta: "&theta;",
    Theta: "&Theta;",
    lambda: "&lambda;",
    Lambda: "&Lambda;",
    mu: "&mu;",
    nu: "&nu;",
    xi: "&xi;",
    pi: "&pi;",
    Pi: "&Pi;",
    rho: "&rho;",
    sigma: "&sigma;",
    Sigma: "&Sigma;",
    tau: "&tau;",
    phi: "&phi;",
    varphi: "&phi;",
    Phi: "&Phi;",
    chi: "&chi;",
    psi: "&psi;",
    Psi: "&Psi;",
    omega: "&omega;",
    Omega: "&Omega;",
    pm: "&plusmn;",
    mp: "&#8723;",
    times: "&times;",
    cdot: "&middot;",
    ast: "*",
    star: "&#8902;",
    le: "&le;",
    leq: "&le;",
    ge: "&ge;",
    geq: "&ge;",
    ll: "&laquo;",
    gg: "&raquo;",
    approx: "&asymp;",
    sim: "~",
    simeq: "&#8771;",
    propto: "&prop;",
    infty: "&infin;",
    odot: "&#8857;",
    oplus: "&#8853;",
    sun: "&#9737;",
    deg: "&deg;",
    degree: "&deg;",
    prime: "&prime;",
    arcsec: "&Prime;",
    rightarrow: "&rarr;",
    to: "&rarr;",
    leftarrow: "&larr;"
  };

  function textWithMath(value) {
    const text = String(value == null ? "" : value);
    let out = "";
    let index = 0;
    const delimiters = [
      { open: "$$", close: "$$", display: true },
      { open: "\\[", close: "\\]", display: true },
      { open: "\\(", close: "\\)", display: false },
      { open: "$", close: "$", display: false }
    ];
    while (index < text.length) {
      let next = null;
      delimiters.forEach((delimiter) => {
        const found = text.indexOf(delimiter.open, index);
        if (found !== -1 && (!next || found < next.found || (found === next.found && delimiter.open.length > next.delimiter.open.length))) {
          next = { found, delimiter };
        }
      });
      if (!next) {
        out += escapeHtml(text.slice(index));
        break;
      }
      out += escapeHtml(text.slice(index, next.found));
      const formulaStart = next.found + next.delimiter.open.length;
      const formulaEnd = text.indexOf(next.delimiter.close, formulaStart);
      if (formulaEnd === -1) {
        out += escapeHtml(text.slice(next.found));
        break;
      }
      out += renderLatexFormula(text.slice(formulaStart, formulaEnd), next.delimiter.display);
      index = formulaEnd + next.delimiter.close.length;
    }
    return out;
  }

  function consumeGroup(text, index) {
    if (text[index] !== "{") {
      return null;
    }
    let depth = 0;
    for (let cursor = index; cursor < text.length; cursor += 1) {
      const char = text[cursor];
      if (char === "{") {
        depth += 1;
      } else if (char === "}") {
        depth -= 1;
        if (depth === 0) {
          return { body: text.slice(index + 1, cursor), end: cursor + 1 };
        }
      }
    }
    return null;
  }

  function readLatexCommand(text, index) {
    let cursor = index + 1;
    if (/[A-Za-z]/.test(text[cursor] || "")) {
      while (cursor < text.length && /[A-Za-z]/.test(text[cursor])) {
        cursor += 1;
      }
      return { name: text.slice(index + 1, cursor), end: cursor };
    }
    return { name: text[cursor] || "", end: Math.min(cursor + 1, text.length) };
  }

  function renderLatexAtom(text, index) {
    const char = text[index];
    if (char === "{") {
      const group = consumeGroup(text, index);
      if (group) {
        return { html: renderLatexTokens(group.body), end: group.end };
      }
    }
    if (char === "\\") {
      const command = readLatexCommand(text, index);
      return { html: renderLatexTokens(text.slice(index, command.end)), end: command.end };
    }
    return { html: escapeHtml(char || ""), end: Math.min(index + 1, text.length) };
  }

  function renderTextCommand(text, start, className) {
    const group = consumeGroup(text, start);
    if (!group) {
      return null;
    }
    return {
      html: `<span class="${className}">${escapeHtml(group.body)}</span>`,
      end: group.end
    };
  }

  function renderLatexTokens(text) {
    let out = "";
    let index = 0;
    while (index < text.length) {
      const char = text[index];
      if (char === "\\") {
        const command = readLatexCommand(text, index);
        const name = command.name;
        if (name === "frac" || name === "dfrac" || name === "tfrac") {
          const numerator = consumeGroup(text, command.end);
          const denominator = numerator ? consumeGroup(text, numerator.end) : null;
          if (numerator && denominator) {
            out += `<span class="math-frac"><span class="math-num">${renderLatexTokens(numerator.body)}</span><span class="math-den">${renderLatexTokens(denominator.body)}</span></span>`;
            index = denominator.end;
            continue;
          }
        }
        if (name === "sqrt") {
          let cursor = command.end;
          if (text[cursor] === "[") {
            const close = text.indexOf("]", cursor + 1);
            if (close !== -1) {
              cursor = close + 1;
            }
          }
          const group = consumeGroup(text, cursor);
          if (group) {
            out += `<span class="math-sqrt"><span class="math-radical">&radic;</span><span class="math-radicand">${renderLatexTokens(group.body)}</span></span>`;
            index = group.end;
            continue;
          }
        }
        if (["mathrm", "textrm", "operatorname", "text"].includes(name)) {
          const rendered = renderTextCommand(text, command.end, "math-roman");
          if (rendered) {
            out += rendered.html;
            index = rendered.end;
            continue;
          }
        }
        if (name === "mathbf") {
          const rendered = renderTextCommand(text, command.end, "math-bold");
          if (rendered) {
            out += rendered.html;
            index = rendered.end;
            continue;
          }
        }
        if (name === "mathit") {
          const rendered = renderTextCommand(text, command.end, "math-italic");
          if (rendered) {
            out += rendered.html;
            index = rendered.end;
            continue;
          }
        }
        if (name === "," || name === ";" || name === ":" || name === " ") {
          out += " ";
          index = command.end;
          continue;
        }
        if (name === "rm" || name === "bf" || name === "it") {
          index = command.end;
          while (text[index] === " ") {
            index += 1;
          }
          continue;
        }
        if (name === "!" || name === "left" || name === "right") {
          index = command.end;
          continue;
        }
        if (Object.prototype.hasOwnProperty.call(LATEX_SYMBOLS, name)) {
          out += LATEX_SYMBOLS[name];
          index = command.end;
          continue;
        }
        out += escapeHtml("\\" + name);
        index = command.end;
        continue;
      }
      if (char === "^" || char === "_") {
        const atom = renderLatexAtom(text, index + 1);
        out += char === "^" ? `<sup>${atom.html}</sup>` : `<sub>${atom.html}</sub>`;
        index = atom.end;
        continue;
      }
      if (char === "{" || char === "}") {
        index += 1;
        continue;
      }
      out += escapeHtml(char);
      index += 1;
    }
    return out;
  }

  function renderLatexFormula(source, display) {
    const latex = String(source == null ? "" : source).trim();
    if (!latex) {
      return "";
    }
    const className = display ? "math-formula math-display" : "math-formula";
    return `<span class="${className}" aria-label="${escapeHtml(latex)}">${renderLatexTokens(latex)}</span>`;
  }

  function isNumericText(value) {
    return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(compact(value));
  }

  function signedErrorText(value, fallbackSign) {
    const text = compact(value);
    if (!text) {
      return "";
    }
    if (text.startsWith("+") || text.startsWith("-") || text.startsWith("±")) {
      return text;
    }
    return fallbackSign + text;
  }

  function latexForUnit(unit) {
    let text = compact(unit);
    if (!text) {
      return "";
    }
    if (text.includes("$") || text.includes("\\(") || text.includes("\\[")) {
      return text;
    }
    text = text
      .replace(/µ/g, "\\mu")
      .replace(/μ/g, "\\mu")
      .replace(/\s+/g, " ")
      .replace(/\*\*/g, "^")
      .replace(/\s*\/\s*/g, " / ")
      .replace(/M_sun/g, "M_{\\odot}")
      .replace(/R_sun/g, "R_{\\odot}")
      .replace(/\bMsun\b/g, "M_{\\odot}")
      .replace(/\bRsun\b/g, "R_{\\odot}")
      .replace(/\belectron\b/g, "\\mathrm{electron}")
      .replace(/\blog\(([^)]*)\)/g, "\\log($1)");
    const pieces = text.split(" ").filter(Boolean);
    let denominator = false;
    const rendered = [];
    pieces.forEach((piece) => {
      if (piece === "/") {
        denominator = true;
        return;
      }
      let token = piece;
      if (denominator && !token.includes("^")) {
        token += "^-1";
      }
      token = token
        .replace(/^([A-Za-z]+)-(\d+)$/, "$1^-$2")
        .replace(/^([A-Za-z]+)\+(\d+)$/, "$1^+$2")
        .replace(/^([A-Za-z]+)\^(-?\d+)$/, "\\mathrm{$1}^{$2}")
        .replace(/^([A-Za-z]+)\^([+-]?\d+)$/, "\\mathrm{$1}^{$2}");
      if (/^[A-Za-z]+$/.test(token)) {
        token = "\\mathrm{" + token + "}";
      }
      rendered.push(token);
    });
    return rendered.join("\\,");
  }

  function renderUnit(unit) {
    const latex = latexForUnit(unit);
    if (!latex) {
      return "";
    }
    if (latex.includes("$") || latex.includes("\\(") || latex.includes("\\[")) {
      return textWithMath(latex);
    }
    return renderLatexFormula(latex, false);
  }

  function looksLikeUnit(value) {
    const text = compact(value);
    return /^(?:[A-Za-z_µμ]+|\w+\([^)]*\))(?:\s*(?:\/|\s)\s*(?:[A-Za-z_µμ]+|\w+\([^)]*\))(?:\^?\*?-?[0-9]+|\^[{]?-?[0-9]+[}]?)?)*$/.test(text)
      && /\b(?:km|mas|yr|s|mag|kpc|pc|dex|K|Myr|Gyr|deg|electron|Msun|Rsun|M_sun|R_sun)\b/.test(text);
  }

  function renderQuantityMath(quantity) {
    const payload = asObject(quantity);
    const value = compact(payload.value);
    if (!value) {
      return "";
    }
    const unit = compact(payload.unit);
    const error = compact(payload.error);
    const lower = compact(payload.lower_error);
    const upper = compact(payload.upper_error);
    const shouldRenderMath = Boolean(unit || error || lower || upper || isNumericText(value));
    if (!shouldRenderMath) {
      return textWithMath(value);
    }
    let body = escapeHtml(value);
    if (error) {
      body += `<span class="math-op">&plusmn;</span>${escapeHtml(error.replace(/^[±+\\-]\s*/, ""))}`;
    } else if (lower || upper) {
      const lowerText = signedErrorText(lower, "-");
      const upperText = signedErrorText(upper, "+");
      if (lowerText) {
        body += `<sub>${escapeHtml(lowerText)}</sub>`;
      }
      if (upperText) {
        body += `<sup>${escapeHtml(upperText)}</sup>`;
      }
    }
    const unitHtml = renderUnit(unit);
    if (unitHtml) {
      body += `<span class="math-unit">${unitHtml}</span>`;
    }
    return `<span class="math-formula quantity-math" aria-label="${escapeHtml(quantityText(payload))}">${body}</span>`;
  }

  function compact(value) {
    return String(value == null ? "" : value).trim();
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function asObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
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

  function numberValue(value) {
    if (value == null || value === "" || typeof value === "boolean") {
      return null;
    }
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function fmtNumber(value, digits) {
    const n = numberValue(value);
    if (n == null) {
      return "";
    }
    if (Math.abs(n) >= 1000) {
      return n.toFixed(digits == null ? 0 : digits);
    }
    if (Math.abs(n) >= 100) {
      return n.toFixed(digits == null ? 1 : digits);
    }
    if (Math.abs(n) >= 10) {
      return n.toFixed(digits == null ? 2 : digits);
    }
    return n.toFixed(digits == null ? 3 : digits);
  }

  function fmtProbability(value) {
    const n = numberValue(value);
    if (n == null) {
      return "";
    }
    if (n >= 0.995) {
      return n.toFixed(5);
    }
    return n.toFixed(3);
  }

  function quantityText(quantity, options) {
    if (!quantity || typeof quantity !== "object" || Array.isArray(quantity)) {
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
      text += " +/- " + error;
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

  function intervalSummary(value) {
    const payload = asObject(value);
    const median = numberValue(payload.median);
    const p16 = numberValue(payload.p16);
    const p84 = numberValue(payload.p84);
    if (median == null) {
      return { text: "", median: null, p16, p84 };
    }
    let text = fmtNumber(median);
    if (p16 != null && p84 != null) {
      text += " [" + fmtNumber(p16) + ", " + fmtNumber(p84) + "]";
    }
    return { text, median, p16, p84 };
  }

  function candidateForSource(record, sourceId) {
    return asArray(record.candidates).find((candidate) => candidate && candidate.source === sourceId) || null;
  }

  function bestSourceQuantity(record, group, field) {
    for (const candidate of asArray(record.candidates)) {
      const quantity = asObject(asObject(asObject(candidate.core)[group])[field]);
      if (Object.keys(quantity).length) {
        return quantity;
      }
    }
    return {};
  }

  function sourceSummary(record, source) {
    const sourceId = compact(source.source);
    const candidate = candidateForSource(record, sourceId) || {};
    const core = asObject(candidate.core);
    const observed = asObject(core.observed_phase_space);
    const derived = asObject(core.derived_kinematics);
    const boundAssessment = asObject(core.bound_assessment);
    const paper = asObject(source.paper);
    const context = asObject(candidate.candidate_context);
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
      unbound_probability: quantityText(boundAssessment.unbound_probability, { includeUnit: false }),
      bound_claim: compact(context.galactic_bound_claim),
      paper_labels: uniq(asArray(context.paper_labels)),
      origin_type: compact(context.origin_type),
      extraction_confidence: compact(context.extraction_confidence)
    };
  }

  function candidateContextSummary(record) {
    const contexts = asArray(record.candidates).map((candidate) => asObject(candidate.candidate_context));
    return {
      paper_labels: uniq(contexts.flatMap((context) => asArray(context.paper_labels))),
      bound_claims: uniq(contexts.map((context) => context.galactic_bound_claim)),
      origin_types: uniq(contexts.map((context) => context.origin_type)),
      extraction_confidence: uniq(contexts.map((context) => context.extraction_confidence)),
      reassessed_source_count: contexts.filter((context) => context.paper_reassesses_unbound_status === true).length
    };
  }

  function dynamicsSummary(record) {
    const dynamics = asObject(record.dynamics);
    const astrometry = asObject(dynamics.astrometry);
    const rvSource = asObject(dynamics.radial_velocity_source);
    const pUnbound = intervalSummary(dynamics.p_unbound_beta);
    const pBound = intervalSummary(dynamics.p_bound_beta);
    const totalVelocity = intervalSummary(dynamics.total_velocity_grf_kms);
    const escapeVelocity = intervalSummary(dynamics.escape_velocity_kms);
    const velocityMargin =
      totalVelocity.median != null && escapeVelocity.median != null
        ? totalVelocity.median - escapeVelocity.median
        : null;
    return {
      status: compact(dynamics.status || "not_computed"),
      status_reason: compact(dynamics.status_reason),
      gaia_source_id: compact(dynamics.gaia_source_id),
      p_unbound: pUnbound,
      p_bound: pBound,
      total_velocity_grf_kms: totalVelocity,
      escape_velocity_kms: escapeVelocity,
      velocity_margin_kms: velocityMargin,
      lower_limit: Boolean(dynamics.lower_limit),
      graveyard: Boolean(dynamics.graveyard),
      radial_velocity_source: {
        source: compact(rvSource.source),
        source_detail: compact(rvSource.source_detail),
        value: numberValue(rvSource.value),
        error: numberValue(rvSource.error),
        unit: compact(rvSource.unit),
        bibcode: compact(rvSource.bibcode),
        lower_limit: Boolean(rvSource.lower_limit)
      },
      corrected_parallax_mas: numberValue(astrometry.corrected_parallax_mas),
      parallax_error_mas: numberValue(astrometry.parallax_error_mas),
      corrected_parallax_over_error: numberValue(astrometry.corrected_parallax_over_error),
      warning_count: asArray(dynamics.warnings).length,
      sample_count: numberValue(asObject(dynamics.sampling).sample_count)
    };
  }

  function externalSummary(record) {
    const enrichment = asObject(record.external_enrichment);
    const providers = asObject(enrichment.providers);
    const simbad = asObject(providers.simbad);
    const gaia = asObject(providers.gaia_dr3);
    const verification = asObject(enrichment.verification);
    const separations = asObject(verification.coordinate_separations_arcsec);
    return {
      status: compact(enrichment.status),
      queried_at: compact(enrichment.queried_at),
      warning_count: asArray(enrichment.warnings).length,
      value_comparison_count: asArray(verification.value_comparisons).length,
      simbad: {
        status: compact(simbad.status),
        matched_by: compact(simbad.matched_by),
        main_id: compact(simbad.main_id),
        object_type: compact(simbad.object_type),
        separation_arcsec: numberValue(separations.simbad)
      },
      gaia_dr3: {
        status: compact(gaia.status),
        matched_by: compact(gaia.matched_by),
        source_id: compact(gaia.source_id),
        designation: compact(gaia.designation),
        separation_arcsec: numberValue(separations.gaia_dr3)
      }
    };
  }

  function quantityCoverageSummary(record) {
    const coverage = {
      photometry: 0,
      spectroscopy: 0,
      stellar_parameters: 0,
      abundances: 0,
      quality_flags: 0,
      orbit: 0,
      astrophysical_origin: 0,
      extra: 0
    };
    asArray(record.candidates).forEach((candidate) => {
      ["photometry", "spectroscopy", "abundances", "quality_flags", "extra"].forEach((key) => {
        coverage[key] += asArray(candidate[key]).length;
      });
      ["stellar_parameters", "orbit", "astrophysical_origin"].forEach((key) => {
        coverage[key] += Object.values(asObject(candidate[key])).filter((value) => {
          if (Array.isArray(value)) {
            return value.length > 0;
          }
          return value != null && value !== "" && Object.keys(asObject(value)).length > 0;
        }).length;
      });
    });
    return coverage;
  }

  function buildIndexRow(record) {
    const canonical = asObject(record.canonical_identifier);
    const sourceRows = asArray(record.sources).map((source) => sourceSummary(record, source));
    const merge = asObject(record.merge);
    const dynamics = dynamicsSummary(record);
    const external = externalSummary(record);
    const bestSourceValues = {};
    OBSERVED_FIELDS.forEach((field) => {
      bestSourceValues[field] = quantityText(bestSourceQuantity(record, "observed_phase_space", field), { includeUnit: false });
    });
    bestSourceValues.total_velocity = quantityText(bestSourceQuantity(record, "derived_kinematics", "total_velocity"), { includeUnit: false });
    bestSourceValues.unbound_probability = quantityText(bestSourceQuantity(record, "bound_assessment", "unbound_probability"), { includeUnit: false });
    return {
      object_id: compact(record.object_id),
      identifier: compact(canonical.value || record.object_id),
      identifier_kind: compact(canonical.kind),
      gaia_source_ids: uniq(sourceRows.map((source) => source.gaia_source_id)),
      paper_candidate_ids: uniq(sourceRows.map((source) => source.paper_candidate_id)),
      bibcodes: uniq(sourceRows.map((source) => source.bibcode)),
      sources: sourceRows,
      source_count: sourceRows.length,
      enrichment_status: external.status,
      enrichment_warning_count: external.warning_count,
      warning_count: asArray(merge.warnings).length,
      evidence_count: asArray(merge.evidence).length,
      best_source_values: bestSourceValues,
      candidate_context: candidateContextSummary(record),
      dynamics,
      external,
      merge: {
        match_strategy: compact(merge.match_strategy),
        warning_count: asArray(merge.warnings).length,
        evidence_count: asArray(merge.evidence).length
      },
      quantity_coverage: quantityCoverageSummary(record)
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
        <header class="masthead">
          <div>
            <div class="eyebrow">Stella object-level HVS catalog</div>
            <h1>Candidate Triage Console</h1>
          </div>
          <nav class="top-nav" aria-label="Main navigation">
            <a class="nav-pill ${active === "home" ? "is-active" : ""}" href="#">Catalog</a>
            <a class="nav-pill" href="#catalog-index">Index</a>
            <a class="nav-pill" href="#audit">Audit</a>
          </nav>
        </header>
        <main class="main-content">${content}</main>
      </div>
    `;
  }

  function badge(text, tone) {
    if (!compact(text)) {
      return "";
    }
    return `<span class="badge badge-${escapeHtml(tone || "neutral")}">${escapeHtml(text)}</span>`;
  }

  function metric(label, value, sublabel) {
    return `
      <div class="metric">
        <span class="metric-value">${escapeHtml(value == null || value === "" ? "-" : value)}</span>
        <span class="metric-label">${escapeHtml(label)}</span>
        ${sublabel ? `<span class="metric-sub">${looksLikeUnit(sublabel) ? renderUnit(sublabel) : textWithMath(sublabel)}</span>` : ""}
      </div>
    `;
  }

  function allWarnings(row) {
    return Number(asObject(row.merge).warning_count || row.warning_count || 0) +
      Number(asObject(row.external).warning_count || row.enrichment_warning_count || 0) +
      Number(asObject(row.dynamics).warning_count || 0);
  }

  function computeStats(rows) {
    const computed = rows.filter((row) => asObject(row.dynamics).status === "computed");
    return {
      objects: rows.length,
      computed: computed.length,
      skipped: rows.filter((row) => asObject(row.dynamics).status === "skipped").length,
      unbound95: computed.filter((row) => numberValue(asObject(asObject(row.dynamics).p_unbound).median) >= 0.95).length,
      unbound50: computed.filter((row) => numberValue(asObject(asObject(row.dynamics).p_unbound).median) >= 0.5).length,
      lowerLimit: rows.filter((row) => asObject(row.dynamics).lower_limit).length,
      graveyard: rows.filter((row) => asObject(row.dynamics).graveyard).length,
      warningObjects: rows.filter((row) => allWarnings(row) > 0).length
    };
  }

  function rowSearchText(row) {
    const dynamics = asObject(row.dynamics);
    const external = asObject(row.external);
    const context = asObject(row.candidate_context);
    return [
      row.object_id,
      row.identifier,
      row.identifier_kind,
      ...(row.gaia_source_ids || []),
      ...(row.paper_candidate_ids || []),
      ...(row.bibcodes || []),
      ...(context.paper_labels || []),
      ...(context.bound_claims || []),
      ...(context.origin_types || []),
      dynamics.status,
      dynamics.status_reason,
      asObject(dynamics.radial_velocity_source).source,
      external.status,
      asObject(external.simbad).main_id,
      asObject(external.gaia_dr3).designation,
      ...asArray(row.sources).flatMap((source) => [
        source.record_id,
        source.paper_candidate_id,
        source.gaia_source_id,
        source.arxiv_id,
        source.bibcode,
        source.total_velocity,
        source.unbound_probability,
        source.bound_claim,
        source.origin_type,
        source.extraction_confidence,
        ...asArray(source.paper_labels),
        ...Object.values(source.phase_space || {})
      ])
    ]
      .join(" ")
      .toLowerCase();
  }

  function passesFilters(row) {
    const query = state.filter.trim().toLowerCase();
    if (query && !rowSearchText(row).includes(query)) {
      return false;
    }
    const dynamics = asObject(row.dynamics);
    const pUnbound = numberValue(asObject(dynamics.p_unbound).median);
    if (state.filters.dynamics === "computed" && dynamics.status !== "computed") {
      return false;
    }
    if (state.filters.dynamics === "skipped" && dynamics.status !== "skipped") {
      return false;
    }
    if (state.filters.dynamics === "lower_limit" && !dynamics.lower_limit) {
      return false;
    }
    if (state.filters.dynamics === "graveyard" && !dynamics.graveyard) {
      return false;
    }
    if (state.filters.unbound === "gte95" && !(pUnbound != null && pUnbound >= 0.95)) {
      return false;
    }
    if (state.filters.unbound === "gte50" && !(pUnbound != null && pUnbound >= 0.5)) {
      return false;
    }
    if (state.filters.unbound === "mid" && !(pUnbound != null && pUnbound >= 0.05 && pUnbound < 0.5)) {
      return false;
    }
    if (state.filters.unbound === "low" && !(pUnbound != null && pUnbound < 0.05)) {
      return false;
    }
    if (state.filters.unbound === "missing" && pUnbound != null) {
      return false;
    }
    const rvSource = compact(asObject(dynamics.radial_velocity_source).source);
    if (state.filters.rv !== "all") {
      if (state.filters.rv === "missing" && rvSource) {
        return false;
      }
      if (state.filters.rv !== "missing" && rvSource !== state.filters.rv) {
        return false;
      }
    }
    const externalWarnings = Number(asObject(row.external).warning_count || 0);
    const mergeWarnings = Number(asObject(row.merge).warning_count || row.warning_count || 0);
    const dynamicsWarnings = Number(dynamics.warning_count || 0);
    if (state.filters.warnings === "clean" && externalWarnings + mergeWarnings + dynamicsWarnings !== 0) {
      return false;
    }
    if (state.filters.warnings === "any" && externalWarnings + mergeWarnings + dynamicsWarnings === 0) {
      return false;
    }
    if (state.filters.warnings === "merge" && mergeWarnings === 0) {
      return false;
    }
    if (state.filters.warnings === "enrichment" && externalWarnings === 0) {
      return false;
    }
    if (state.filters.warnings === "dynamics" && dynamicsWarnings === 0) {
      return false;
    }
    return true;
  }

  function sortValue(row, key) {
    const dynamics = asObject(row.dynamics);
    const external = asObject(row.external);
    if (key === "p_unbound") {
      return numberValue(asObject(dynamics.p_unbound).median);
    }
    if (key === "total_velocity") {
      return numberValue(asObject(dynamics.total_velocity_grf_kms).median);
    }
    if (key === "velocity_margin") {
      return numberValue(dynamics.velocity_margin_kms);
    }
    if (key === "source_count") {
      return Number(row.source_count || 0);
    }
    if (key === "warnings") {
      return allWarnings(row);
    }
    if (key === "evidence_count") {
      return Number(asObject(row.merge).evidence_count || row.evidence_count || 0);
    }
    if (key === "parallax_snr") {
      return numberValue(dynamics.corrected_parallax_over_error);
    }
    if (key === "enrichment_status") {
      return compact(external.status || row.enrichment_status);
    }
    return compact(row[key]);
  }

  function filteredRows() {
    const factor = state.sortDir === "asc" ? 1 : -1;
    return state.rows
      .filter(passesFilters)
      .sort((left, right) => {
        const a = sortValue(left, state.sortKey);
        const b = sortValue(right, state.sortKey);
        const aMissing = a == null || a === "";
        const bMissing = b == null || b === "";
        if (aMissing && bMissing) {
          return compact(left.identifier).localeCompare(compact(right.identifier), undefined, { numeric: true }) * factor;
        }
        if (aMissing) {
          return 1;
        }
        if (bMissing) {
          return -1;
        }
        if (typeof a === "number" && typeof b === "number") {
          return (a - b) * factor;
        }
        return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" }) * factor;
      });
  }

  function dynamicsTone(status) {
    if (status === "computed") {
      return "good";
    }
    if (status === "skipped") {
      return "warn";
    }
    return "neutral";
  }

  function probabilityTone(value) {
    const n = numberValue(value);
    if (n == null) {
      return "neutral";
    }
    if (n >= 0.95) {
      return "hot";
    }
    if (n >= 0.5) {
      return "good";
    }
    if (n < 0.05) {
      return "quiet";
    }
    return "warn";
  }

  function renderSortButton(label, key) {
    const active = state.sortKey === key;
    const dir = active ? (state.sortDir === "asc" ? " asc" : " desc") : "";
    return `<button class="sort-button${active ? " is-active" : ""}" data-sort="${escapeHtml(key)}">${escapeHtml(label)}${escapeHtml(dir)}</button>`;
  }

  function renderPills(values, tone) {
    return asArray(values).map((value) => badge(value, tone || "neutral")).join("");
  }

  function renderScienceMetrics() {
    const stats = computeStats(state.rows);
    return `
      <section class="metric-strip">
        ${metric("Objects", stats.objects, "merged candidates")}
        ${metric("Dynamics computed", stats.computed, stats.skipped + " skipped")}
        ${metric("P(unbound) >= 0.95", stats.unbound95, stats.unbound50 + " at >= 0.50")}
        ${metric("Lower-limit cases", stats.lowerLimit, "missing RV mode")}
        ${metric("Graveyard", stats.graveyard, "computed objects")}
        ${metric("Objects with warnings", stats.warningObjects, "merge, enrichment, or dynamics")}
      </section>
    `;
  }

  function renderFilters(rows, sourceRowCount) {
    return `
      <section class="catalog-tools" id="catalog-index">
        <div>
          <h2 class="section-heading">Research Candidate Index</h2>
          <div class="table-count">Showing ${rows.length} of ${state.rows.length} objects / ${sourceRowCount} source rows</div>
        </div>
        <div class="filter-grid">
          <label class="filter-field">
            <span>Search</span>
            <input id="catalog-search" type="search" value="${escapeHtml(state.filter)}" autocomplete="off">
          </label>
          <label class="filter-field">
            <span>Dynamics</span>
            <select data-filter="dynamics">
              ${option("all", "All", state.filters.dynamics)}
              ${option("computed", "computed", state.filters.dynamics)}
              ${option("skipped", "skipped", state.filters.dynamics)}
              ${option("lower_limit", "lower limit", state.filters.dynamics)}
              ${option("graveyard", "graveyard", state.filters.dynamics)}
            </select>
          </label>
          <label class="filter-field">
            <span>P(unbound)</span>
            <select data-filter="unbound">
              ${option("all", "All", state.filters.unbound)}
              ${option("gte95", ">= 0.95", state.filters.unbound)}
              ${option("gte50", ">= 0.50", state.filters.unbound)}
              ${option("mid", "0.05-0.50", state.filters.unbound)}
              ${option("low", "< 0.05", state.filters.unbound)}
              ${option("missing", "missing", state.filters.unbound)}
            </select>
          </label>
          <label class="filter-field">
            <span>RV source</span>
            <select data-filter="rv">
              ${option("all", "All", state.filters.rv)}
              ${option("literature", "literature", state.filters.rv)}
              ${option("simbad", "SIMBAD", state.filters.rv)}
              ${option("minimum_grf_velocity", "minimum GRF", state.filters.rv)}
              ${option("missing", "missing", state.filters.rv)}
            </select>
          </label>
          <label class="filter-field">
            <span>Warnings</span>
            <select data-filter="warnings">
              ${option("all", "All", state.filters.warnings)}
              ${option("clean", "clean", state.filters.warnings)}
              ${option("any", "any warning", state.filters.warnings)}
              ${option("merge", "merge", state.filters.warnings)}
              ${option("enrichment", "enrichment", state.filters.warnings)}
              ${option("dynamics", "dynamics", state.filters.warnings)}
            </select>
          </label>
        </div>
      </section>
    `;
  }

  function option(value, label, current) {
    return `<option value="${escapeHtml(value)}"${value === current ? " selected" : ""}>${escapeHtml(label)}</option>`;
  }

  function renderDynamicsCell(row) {
    const dynamics = asObject(row.dynamics);
    const pUnbound = asObject(dynamics.p_unbound);
    const v = asObject(dynamics.total_velocity_grf_kms);
    const escape = asObject(dynamics.escape_velocity_kms);
    const margin = numberValue(dynamics.velocity_margin_kms);
    const chips = [
      badge(dynamics.status || "not_computed", dynamicsTone(dynamics.status)),
      dynamics.lower_limit ? badge("lower limit", "warn") : "",
      dynamics.graveyard ? badge("graveyard", "quiet") : ""
    ].join("");
    return `
      <div class="science-stack">
        <div class="badge-row">${chips}</div>
        <div class="keyline"><span>Punb</span><strong class="tone-${probabilityTone(pUnbound.median)}">${escapeHtml(fmtProbability(pUnbound.median) || "-")}</strong></div>
        <div class="keyline"><span>vGRF</span><strong>${escapeHtml(fmtNumber(v.median) || "-")}</strong><em>${renderUnit("km s^-1")}</em></div>
        <div class="keyline"><span>vesc</span><strong>${escapeHtml(fmtNumber(escape.median) || "-")}</strong><em>${renderUnit("km s^-1")}</em></div>
        <div class="keyline"><span>margin</span><strong>${escapeHtml(margin == null ? "-" : fmtNumber(margin))}</strong><em>${renderUnit("km s^-1")}</em></div>
        ${dynamics.status_reason ? `<div class="muted-line">${escapeHtml(dynamics.status_reason)}</div>` : ""}
      </div>
    `;
  }

  function renderLiteratureCell(row) {
    const context = asObject(row.candidate_context);
    return `
      <div class="science-stack">
        <div class="badge-row">${renderPills(context.bound_claims, "paper")}</div>
        <div class="badge-row">${renderPills(context.paper_labels, "neutral")}</div>
        <div class="muted-line">${escapeHtml(asArray(context.origin_types).join(", ") || "-")}</div>
        <div class="muted-line">confidence: ${escapeHtml(asArray(context.extraction_confidence).join(", ") || "-")}</div>
      </div>
    `;
  }

  function renderQualityCell(row) {
    const dynamics = asObject(row.dynamics);
    const external = asObject(row.external);
    const rvSource = asObject(dynamics.radial_velocity_source);
    const gaia = asObject(external.gaia_dr3);
    const simbad = asObject(external.simbad);
    return `
      <div class="science-stack">
        <div class="keyline"><span>Gaia</span><strong>${escapeHtml(compact(gaia.source_id) || compact((row.gaia_source_ids || [])[0]) || "-")}</strong></div>
        <div class="keyline"><span>plx S/N</span><strong>${escapeHtml(fmtNumber(dynamics.corrected_parallax_over_error, 2) || "-")}</strong></div>
        <div class="keyline"><span>RV</span><strong>${escapeHtml(compact(rvSource.source) || "-")}</strong></div>
        <div class="muted-line">Gaia match: ${escapeHtml(compact(gaia.matched_by) || "-")}</div>
        <div class="muted-line">SIMBAD: ${escapeHtml(compact(simbad.main_id) || compact(simbad.status) || "-")}</div>
      </div>
    `;
  }

  function renderAuditCell(row) {
    const external = asObject(row.external);
    const merge = asObject(row.merge);
    return `
      <div class="science-stack audit-cell">
        <div class="badge-row">
          ${badge((row.source_count || 0) + " src", "neutral")}
          ${badge((merge.evidence_count || row.evidence_count || 0) + " evidence", "neutral")}
          ${badge((merge.warning_count || row.warning_count || 0) + " merge warn", Number(merge.warning_count || row.warning_count || 0) ? "warn" : "quiet")}
          ${badge((external.warning_count || row.enrichment_warning_count || 0) + " enrich warn", Number(external.warning_count || row.enrichment_warning_count || 0) ? "warn" : "quiet")}
        </div>
        <div class="muted-line">enrichment: ${escapeHtml(external.status || row.enrichment_status || "-")}</div>
        <div class="muted-line">match strategy: ${escapeHtml(merge.match_strategy || "-")}</div>
      </div>
    `;
  }

  function renderIdentifierCell(row) {
    return `
      <div class="identifier-cell-inner">
        <a class="identifier-main" href="#/object/${encodeURIComponent(row.object_id)}">${escapeHtml(row.identifier)}</a>
        <span class="identifier-kind">${escapeHtml(row.identifier_kind || row.object_id)}</span>
        <span class="identifier-muted">${escapeHtml(row.object_id)}</span>
      </div>
    `;
  }

  function renderCatalogTable() {
    const rows = filteredRows();
    const sourceRowCount = rows.reduce((total, row) => total + Math.max(1, asArray(row.sources).length), 0);
    const body = rows
      .map((row) => `
        <tr>
          <td>${renderIdentifierCell(row)}</td>
          <td>${renderDynamicsCell(row)}</td>
          <td>${renderLiteratureCell(row)}</td>
          <td>${renderQualityCell(row)}</td>
          <td>${renderAuditCell(row)}</td>
          <td><a class="more-link" href="#/object/${encodeURIComponent(row.object_id)}">Dossier</a></td>
        </tr>
      `)
      .join("");
    return `
      ${renderFilters(rows, sourceRowCount)}
      <div class="table-wrap">
        <table class="catalog-table">
          <colgroup>
            <col class="col-object">
            <col class="col-dynamics">
            <col class="col-literature">
            <col class="col-quality">
            <col class="col-audit">
            <col class="col-more">
          </colgroup>
          <thead>
            <tr>
              <th>${renderSortButton("Object", "identifier")}</th>
              <th>
                <div class="header-stack">
                  ${renderSortButton("Stella dynamics", "p_unbound")}
                  ${renderSortButton("vGRF", "total_velocity")}
                  ${renderSortButton("margin", "velocity_margin")}
                </div>
              </th>
              <th>Literature signal</th>
              <th>${renderSortButton("Gaia / RV quality", "parallax_snr")}</th>
              <th>
                <div class="header-stack">
                  ${renderSortButton("Audit", "warnings")}
                  ${renderSortButton("evidence", "evidence_count")}
                </div>
              </th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>${body || `<tr><td colspan="6"><div class="empty-state">No matching objects.</div></td></tr>`}</tbody>
        </table>
      </div>
    `;
  }

  function renderHome() {
    const content = `
      ${renderScienceMetrics()}
      ${renderCatalogTable()}
      <section class="audit-summary" id="audit">
        <h2 class="section-heading">Audit Surface</h2>
        <div class="audit-grid">
          ${metric("Merge warnings", (state.index && asArray(state.index.warnings).length) || computeStats(state.rows).warningObjects, "object-level review flags")}
          ${metric("Enrichment warnings", (state.index && asArray(state.index.enrichment_warnings).length) || "-", "Gaia/SIMBAD verification")}
          ${metric("Potential merges", (state.index && asArray(state.index.potential_merges).length) || 0, "review queue")}
          ${metric("Skipped inputs", (state.index && asArray(state.index.skipped).length) || 0, "catalog merge")}
        </div>
      </section>
    `;
    app.innerHTML = shell(content, "home");
  }

  function sourceById(record, sourceId) {
    return asArray(record.sources).find((source) => source && source.source === sourceId) || {};
  }

  function methodGroupBySource(record, sourceId) {
    return asArray(record.method_chain).find((group) => group && group.source === sourceId) || { source: sourceId, steps: [] };
  }

  function rowForObject(objectId) {
    return state.rows.find((row) => row.object_id === objectId) || buildIndexRow(state.objectMap.get(objectId) || {});
  }

  function renderDetailHeader(record, row) {
    const dynamics = asObject(row.dynamics);
    const pUnbound = asObject(dynamics.p_unbound);
    const v = asObject(dynamics.total_velocity_grf_kms);
    const escape = asObject(dynamics.escape_velocity_kms);
    const rvSource = asObject(dynamics.radial_velocity_source);
    const canonical = asObject(record.canonical_identifier);
    return `
      <section class="detail-header">
        <div>
          <a class="back-button" href="#">Back to index</a>
          <h2 class="detail-title">${escapeHtml(canonical.value || record.object_id)}</h2>
          <div class="detail-meta">${escapeHtml(record.object_id)} / schema ${escapeHtml(record.schema_version || "")} / generated ${escapeHtml(record.generated_at || "")}</div>
          <div class="badge-row detail-labels">${renderPills(asObject(row.candidate_context).paper_labels, "neutral")}</div>
        </div>
        <div class="dossier-scoreboard">
          ${metric("P(unbound)", fmtProbability(pUnbound.median) || "-", dynamics.status)}
          ${metric("vGRF", fmtNumber(v.median) || "-", "km s^-1")}
          ${metric("vesc", fmtNumber(escape.median) || "-", "km s^-1")}
          ${metric("RV source", compact(rvSource.source) || "-", dynamics.lower_limit ? "lower limit" : "")}
        </div>
      </section>
    `;
  }

  function dlRows(items) {
    return items
      .filter(([, value]) => value != null && value !== "" && !(Array.isArray(value) && !value.length))
      .map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${textWithMath(Array.isArray(value) ? value.join(", ") : value)}</dd>`)
      .join("");
  }

  function renderDynamicsDossier(record, row) {
    const dynamics = asObject(record.dynamics);
    const summary = asObject(row.dynamics);
    const astrometry = asObject(dynamics.astrometry);
    const rv = asObject(dynamics.radial_velocity_source);
    const warnings = asArray(dynamics.warnings);
    const provenance = asObject(dynamics.provenance);
    return `
      <section class="section-band">
        <h2 class="section-heading">Stella Dynamics</h2>
        <div class="dossier-grid">
          <article class="info-panel">
            <h3>Status</h3>
            <div class="badge-row">
              ${badge(summary.status || "not_computed", dynamicsTone(summary.status))}
              ${summary.lower_limit ? badge("lower limit", "warn") : ""}
              ${summary.graveyard ? badge("graveyard", "quiet") : ""}
            </div>
            <dl class="json-dl">
              ${dlRows([
                ["reason", summary.status_reason],
                ["Gaia source", summary.gaia_source_id],
                ["sample count", summary.sample_count],
                ["warnings", warnings.length]
              ])}
            </dl>
          </article>
          <article class="info-panel">
            <h3>Posterior</h3>
            <dl class="json-dl">
              ${dlRows([
                ["P(unbound)", fmtProbability(asObject(summary.p_unbound).median)],
                ["P(bound)", fmtProbability(asObject(summary.p_bound).median)],
                ["vGRF median", fmtNumber(asObject(summary.total_velocity_grf_kms).median)],
                ["vesc median", fmtNumber(asObject(summary.escape_velocity_kms).median)],
                ["vGRF - vesc", fmtNumber(summary.velocity_margin_kms)]
              ])}
            </dl>
          </article>
          <article class="info-panel">
            <h3>Astrometry</h3>
            <dl class="json-dl">
              ${dlRows([
                ["provider", astrometry.provider],
                ["source_id", astrometry.source_id],
                ["parallax", astrometry.parallax_mas],
                ["zero point", astrometry.zero_point_mas],
                ["corrected parallax", astrometry.corrected_parallax_mas],
                ["parallax error", astrometry.parallax_error_mas],
                ["corrected plx/error", astrometry.corrected_parallax_over_error]
              ])}
            </dl>
          </article>
          <article class="info-panel">
            <h3>Radial Velocity</h3>
            <dl class="json-dl">
              ${dlRows([
                ["source", rv.source],
                ["value", rv.value],
                ["error", rv.error],
                ["unit", rv.unit],
                ["bibcode", rv.bibcode],
                ["detail", rv.source_detail]
              ])}
            </dl>
          </article>
        </div>
        ${renderWarningList("Dynamics warnings", warnings)}
        ${renderProvenance(provenance)}
      </section>
    `;
  }

  function renderProvenance(provenance) {
    if (!Object.keys(provenance).length) {
      return "";
    }
    return `
      <details class="compact-details">
        <summary>Dynamics provenance</summary>
        <pre>${escapeHtml(JSON.stringify(provenance, null, 2))}</pre>
      </details>
    `;
  }

  function renderExternalDossier(record) {
    const enrichment = asObject(record.external_enrichment);
    const providers = asObject(enrichment.providers);
    const simbad = asObject(providers.simbad);
    const gaia = asObject(providers.gaia_dr3);
    const verification = asObject(enrichment.verification);
    return `
      <section class="section-band">
        <h2 class="section-heading">Gaia and SIMBAD Verification</h2>
        <div class="dossier-grid">
          <article class="info-panel">
            <h3>SIMBAD</h3>
            <dl class="json-dl">
              ${dlRows([
                ["status", simbad.status],
                ["matched_by", simbad.matched_by],
                ["main_id", simbad.main_id],
                ["object_type", simbad.object_type],
                ["RV", quantityText(simbad.radial_velocity)]
              ])}
            </dl>
          </article>
          <article class="info-panel">
            <h3>Gaia DR3</h3>
            <dl class="json-dl">
              ${dlRows([
                ["status", gaia.status],
                ["matched_by", gaia.matched_by],
                ["source_id", gaia.source_id],
                ["designation", gaia.designation],
                ["RV", quantityText(gaia.radial_velocity)]
              ])}
            </dl>
          </article>
          <article class="info-panel span-2">
            <h3>Value Comparisons</h3>
            ${renderComparisonTable(asArray(verification.value_comparisons))}
          </article>
        </div>
        ${renderWarningList("Enrichment warnings", asArray(enrichment.warnings))}
      </section>
    `;
  }

  function renderComparisonTable(comparisons) {
    if (!comparisons.length) {
      return `<div class="empty-inline">No comparisons recorded.</div>`;
    }
    return `
      <div class="mini-table-wrap">
        <table class="mini-table">
          <thead>
            <tr><th>source</th><th>field</th><th>literature</th><th>official</th><th>difference</th><th>unit</th></tr>
          </thead>
          <tbody>
            ${comparisons.map((item) => `
              <tr>
                <td>${textWithMath(item.source || "")}</td>
                <td>${textWithMath(item.field || "")}</td>
                <td>${textWithMath(item.literature_value || "")}</td>
                <td>${textWithMath(item.official_value || "")}</td>
                <td>${textWithMath(item.difference || "")}</td>
                <td>${textWithMath(item.unit || "")}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderWarningList(title, warnings) {
    if (!warnings.length) {
      return "";
    }
    return `
      <div class="warning-panel">
        <h3>${escapeHtml(title)}</h3>
        ${warnings.map((warning) => `
          <div class="warning-row">
            <strong>${escapeHtml(warning.type || "warning")}</strong>
            <span>${textWithMath(warning.message || JSON.stringify(warning))}</span>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderMergeAudit(record) {
    const merge = asObject(record.merge);
    return `
      <section class="section-band">
        <h2 class="section-heading">Merge Evidence</h2>
        <div class="dossier-grid">
          <article class="info-panel">
            <h3>Grouping</h3>
            <dl class="json-dl">
              ${dlRows([
                ["strategy", merge.match_strategy],
                ["evidence", asArray(merge.evidence).length],
                ["warnings", asArray(merge.warnings).length]
              ])}
            </dl>
          </article>
          <article class="info-panel span-2">
            <h3>Evidence edges</h3>
            ${renderEvidenceList(asArray(merge.evidence))}
          </article>
        </div>
        ${renderWarningList("Merge warnings", asArray(merge.warnings))}
      </section>
    `;
  }

  function renderEvidenceList(evidence) {
    if (!evidence.length) {
      return `<div class="empty-inline">Singleton object or no merge evidence recorded.</div>`;
    }
    return evidence.map((item) => `
      <div class="evidence-row">
        ${badge(item.evidence_type || "evidence", "neutral")}
        ${badge(item.decision || "", item.decision === "accepted" ? "good" : "warn")}
        <span>${textWithMath(item.source || "")}</span>
        <span>${textWithMath(item.matched_value || item.message || "")}</span>
      </div>
    `).join("");
  }

  function renderSourceCards(record) {
    return `
      <section class="section-band">
        <h2 class="section-heading">Literature Sources</h2>
        <div class="source-cards">
          ${asArray(record.sources)
            .map((source) => {
              const paper = asObject(source.paper);
              const links = asObject(paper.links);
              return `
                <article class="source-card">
                  <span class="source-tag">${escapeHtml(source.source)}</span>
                  <h3>${textWithMath(paper.title || "Untitled source")}</h3>
                  <dl>
                    ${dlRows([
                      ["arXiv", paper.arxiv_id],
                      ["bibcode", paper.bibcode],
                      ["record_id", source.record_id],
                      ["paper ID", source.paper_candidate_id],
                      ["Gaia source ID", source.gaia_source_id],
                      ["source JSON", source.source_json_path]
                    ])}
                  </dl>
                  <div class="link-row">
                    ${paper.arxiv_id ? `<a href="${escapeHtml(links.abs || "https://arxiv.org/abs/" + paper.arxiv_id)}">arXiv</a>` : ""}
                    ${links.pdf ? `<a href="${escapeHtml(links.pdf)}">PDF</a>` : ""}
                  </div>
                </article>
              `;
            })
            .join("")}
        </div>
      </section>
    `;
  }

  function formatQuantityDetail(quantity) {
    return renderQuantityMath(quantity);
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
      return parts.join(" / ");
    }
    return FIELD_LABELS[field] || field || "item " + String(index + 1);
  }

  function renderQuantityRow(record, candidate, field, quantity, index) {
    const refs = asArray(quantity.method_refs).map(compact).filter(Boolean);
    const active =
      state.activeLineage &&
      state.activeLineage.source === candidate.source &&
      refs.some((ref) => state.activeLineage.direct.has(ref));
    return `
      <div class="quantity-row">
        <button class="quantity-button ${active ? "is-active" : ""}" data-source="${escapeHtml(candidate.source)}" data-method-refs="${escapeHtml(refs.join(","))}">
          ${textWithMath(quantityLabel(field, quantity, index))}
        </button>
        <div class="quantity-value">${formatQuantityDetail(quantity)}</div>
      </div>
    `;
  }

  function renderQuantityGroup(record, candidate, groupName, group) {
    const entries = Object.entries(asObject(group)).filter(([, quantity]) => quantity && typeof quantity === "object" && !Array.isArray(quantity));
    if (!entries.length) {
      return "";
    }
    return `
      <div class="quantity-group">
        <h4>${escapeHtml(GROUP_LABELS[groupName] || groupName)}</h4>
        ${entries.map(([field, quantity], index) => renderQuantityRow(record, candidate, field, quantity, index)).join("")}
      </div>
    `;
  }

  function renderQuantityList(record, candidate, groupName, records) {
    const entries = asArray(records).filter((quantity) => quantity && typeof quantity === "object" && !Array.isArray(quantity));
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
    const citation = asObject(context.citation);
    return `
      <dl class="json-dl">
        ${dlRows([
          ["paper labels", asArray(context.paper_labels)],
          ["bound claim", context.galactic_bound_claim],
          ["basis", context.inclusion_basis],
          ["confidence", context.extraction_confidence],
          ["origin type", context.origin_type],
          ["reassesses status", context.paper_reassesses_unbound_status ? "true" : "false"],
          ["citation", Object.keys(citation).length ? [citation.bibkey, citation.year, citation.bibcode || citation.arxiv_id].filter(Boolean).join(" / ") : ""]
        ])}
      </dl>
    `;
  }

  function renderCandidateCore(record) {
    return `
      <section class="section-band">
        <h2 class="section-heading">Source Candidate Records</h2>
        <div class="core-grid">
          ${asArray(record.candidates)
            .map((candidate) => {
              const identifiers = asObject(candidate.identifiers);
              const core = asObject(candidate.core);
              const stellar = asObject(candidate.stellar_parameters);
              const orbit = asObject(candidate.orbit);
              const origin = asObject(candidate.astrophysical_origin);
              return `
                <article class="candidate-core">
                  <h3><span class="source-tag">${escapeHtml(candidate.source)}</span> ${escapeHtml(identifiers.paper_candidate_id || identifiers.record_id || "")}</h3>
                  <dl class="json-dl">
                    ${dlRows([
                      ["record_id", identifiers.record_id],
                      ["paper_candidate_id", identifiers.paper_candidate_id],
                      ["gaia_source_id", identifiers.gaia_source_id]
                    ])}
                  </dl>
                  ${renderCandidateContext(candidate.candidate_context)}
                  <div class="quantity-layout">
                    ${renderQuantityGroup(record, candidate, "observed_phase_space", asObject(core.observed_phase_space))}
                    ${renderQuantityGroup(record, candidate, "derived_kinematics", asObject(core.derived_kinematics))}
                    ${renderQuantityGroup(record, candidate, "bound_assessment", asObject(core.bound_assessment))}
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
                  </div>
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
    const deps = asArray(step.depends_on).filter((dep) => byId.has(dep));
    const depth = deps.length ? Math.max(...deps.map((dep) => stepDepth(dep, byId, memo, visiting))) + 1 : 0;
    visiting.delete(stepId);
    memo.set(stepId, depth);
    return depth;
  }

  function truncate(text, limit) {
    const value = compact(text);
    return value.length > limit ? value.slice(0, limit - 1) + "..." : value;
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
      asArray(step.depends_on).forEach((dep) => {
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
    const yGap = 56;
    const positions = new Map();
    let maxLayerSize = 1;
    sortedLayers.forEach(([, layer]) => {
      maxLayerSize = Math.max(maxLayerSize, layer.length);
    });
    sortedLayers.forEach(([depth, layer]) => {
      const layerOffset = ((maxLayerSize - layer.length) * xGap) / 2;
      layer.forEach((step, index) => {
        positions.set(compact(step.id), { x: 28 + layerOffset + index * xGap, y: 24 + depth * yGap });
      });
    });
    const width = Math.max(520, 60 + maxLayerSize * xGap);
    const height = Math.max(132, 64 + sortedLayers.length * yGap);
    const active = state.activeLineage && state.activeLineage.source === sourceId ? state.activeLineage : null;
    const selected = state.selectedStep && state.selectedStep.source === sourceId ? state.selectedStep.stepId : "";
    const edges = [];
    steps.forEach((step) => {
      const to = compact(step.id);
      const toPos = positions.get(to);
      asArray(step.depends_on).forEach((dep) => {
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
            <rect x="${pos.x}" y="${pos.y}" width="${nodeWidth}" height="${nodeHeight}" rx="2"></rect>
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
      return `<aside class="method-panel"><h4>Method node</h4><p></p></aside>`;
    }
    const list = (title, values) => {
      const items = asArray(values).map((value) => `<li>${textWithMath(value)}</li>`).join("");
      return items ? `<strong>${escapeHtml(title)}</strong><ul class="method-list">${items}</ul>` : "";
    };
    return `
      <aside class="method-panel">
        <h4>${escapeHtml(step.id)} / ${escapeHtml(step.step_type || "")}</h4>
        <p>${textWithMath(step.summary || "")}</p>
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
        ${asArray(record.method_chain)
          .map((group) => {
            const source = sourceById(record, group.source);
            const steps = asArray(group.steps);
            return `
              <article class="method-source" id="method-source-${escapeHtml(group.source)}">
                <h3><span class="source-tag">${escapeHtml(group.source)}</span> ${escapeHtml(asObject(source.paper).bibcode || asObject(source.paper).arxiv_id || "")}</h3>
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
    const row = rowForObject(objectId);
    const content = `
      ${renderDetailHeader(record, row)}
      ${renderDynamicsDossier(record, row)}
      ${renderExternalDossier(record)}
      ${renderMergeAudit(record)}
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
    const inDetail = target.closest(".site-frame") && (window.location.hash || "").startsWith("#/object/");
    if (inDetail) {
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
        state.sortDir = key === "identifier" ? "asc" : "desc";
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
      const lineage = lineageFor(asArray(group.steps), refs);
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

  app.addEventListener("change", (event) => {
    const filter = event.target && event.target.dataset ? event.target.dataset.filter : "";
    if (filter && Object.prototype.hasOwnProperty.call(state.filters, filter)) {
      state.filters[filter] = event.target.value;
      renderHome();
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
