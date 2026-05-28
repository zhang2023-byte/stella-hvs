(function () {
  "use strict";

  const FIELD_LABELS = {
    ra: "RA",
    dec: "Dec",
    parallax: "plx",
    proper_motion_ra: "pmRA",
    proper_motion_dec: "pmDec",
    radial_velocity: "RV",
    distance: "distance",
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
    "radial_velocity",
    "distance"
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
  const STORAGE_KEY = "stellaCatalogHomeConfigV1";
  const HOME_COLUMNS = [
    { key: "discovery", label: "Discovery", type: "date", defaultVisible: true, widthClass: "col-discovery" },
    { key: "reported_by", label: "Reported by", type: "text", defaultVisible: true, widthClass: "col-reporter" },
    { key: "total_velocity", label: "Total velocity", type: "number", defaultVisible: true, widthClass: "col-velocity" },
    { key: "p_unbound", label: "P_ub", type: "number", defaultVisible: true, widthClass: "col-probability" },
    { key: "radial_velocity", label: "RV", type: "number", defaultVisible: true, widthClass: "col-rv" },
    { key: "radec", label: "RA, Dec", type: "number", defaultVisible: true, widthClass: "col-coordinate" },
    { key: "pm", label: "pmRA, pmDec", type: "number", defaultVisible: true, widthClass: "col-coordinate" },
    { key: "parallax", label: "plx", type: "number", defaultVisible: true, widthClass: "col-small" },
    { key: "distance", label: "Distance", type: "number", defaultVisible: true, widthClass: "col-distance" },
    { key: "g_mag", label: "G", type: "number", defaultVisible: true, widthClass: "col-small" },
    { key: "bp_rp", label: "BP-RP", type: "number", defaultVisible: true, widthClass: "col-small" },
    { key: "spectral_type", label: "Spectral type", type: "text", defaultVisible: true, widthClass: "col-spectrum" },
    { key: "metallicity", label: "Metallicity", type: "number", defaultVisible: true, widthClass: "col-stellar" },
    { key: "teff", label: "Teff", type: "number", defaultVisible: true, widthClass: "col-stellar" },
    { key: "log_g", label: "log g", type: "number", defaultVisible: true, widthClass: "col-stellar" }
  ];
  const DEFAULT_HOME_CONFIG = {
    visibleColumns: Object.fromEntries(HOME_COLUMNS.map((column) => [column.key, column.defaultVisible])),
    modes: {
      reportedBy: "earliest",
      velocity: "both",
      pUnbound: "both",
      distance: "all",
      spectralType: "both",
      metallicity: "both",
      teff: "both",
      logG: "both"
    }
  };
  const SOURCE_MODE_COLUMNS = {
    reported_by: {
      modeKey: "reportedBy",
      options: [["earliest", "earliest"], ["latest", "latest"], ["most_cited", "most cited"], ["all", "all"]]
    },
    total_velocity: {
      modeKey: "velocity",
      options: [["both", "Stella + paper"], ["stella", "Stella"], ["literature", "paper"]]
    },
    p_unbound: {
      modeKey: "pUnbound",
      options: [["both", "Stella + paper"], ["stella", "Stella"], ["literature", "paper"]]
    },
    distance: {
      modeKey: "distance",
      options: [["all", "all"], ["literature", "paper"], ["stella", "Stella"], ["gaia", "Gaia gspphot"]]
    },
    spectral_type: {
      modeKey: "spectralType",
      options: [["both", "paper + SIMBAD"], ["paper", "paper"], ["simbad", "SIMBAD"]]
    },
    metallicity: {
      modeKey: "metallicity",
      options: [["both", "paper + Gaia"], ["paper", "paper [Fe/H]"], ["gaia", "Gaia [M/H]"]]
    },
    teff: {
      modeKey: "teff",
      options: [["both", "paper + Gaia"], ["paper", "paper"], ["gaia", "Gaia"]]
    },
    log_g: {
      modeKey: "logG",
      options: [["both", "paper + Gaia"], ["paper", "paper"], ["gaia", "Gaia"]]
    }
  };
  const STATIC_SOURCE_LABELS = {
    discovery: "paper month",
    radial_velocity: "paper",
    radec: "Gaia DR3",
    pm: "Gaia DR3",
    parallax: "Gaia DR3",
    g_mag: "Gaia DR3",
    bp_rp: "Gaia DR3"
  };
  const SOURCE_LABEL_SUPPRESSED_COLUMNS = new Set(["discovery", "reported_by", "radec", "pm", "parallax", "g_mag", "bp_rp"]);
  const RANGE_FILTER_KEYS = new Set([
    "discovery",
    "total_velocity",
    "p_unbound",
    "radial_velocity",
    "parallax",
    "distance",
    "g_mag",
    "bp_rp",
    "metallicity",
    "teff",
    "log_g"
  ]);
  const SORTABLE_HOME_KEYS = new Set([
    "discovery",
    "total_velocity",
    "p_unbound",
    "radial_velocity"
  ]);
  const state = {
    index: null,
    objects: [],
    objectMap: new Map(),
    rows: [],
    paperMetadata: {},
    filter: "",
    rangeFilters: {},
    homeConfig: loadHomeConfig(),
    sortKey: "discovery",
    sortDir: "asc",
    selectedStep: null,
    activeLineage: null
  };
  let catalogTableRenderTimer = null;

  function cloneDefaultHomeConfig() {
    return {
      visibleColumns: { ...DEFAULT_HOME_CONFIG.visibleColumns },
      modes: { ...DEFAULT_HOME_CONFIG.modes }
    };
  }

  function loadHomeConfig() {
    const fallback = cloneDefaultHomeConfig();
    try {
      const raw = window.localStorage ? window.localStorage.getItem(STORAGE_KEY) : "";
      if (!raw) {
        return fallback;
      }
      const parsed = JSON.parse(raw);
      return {
        visibleColumns: { ...fallback.visibleColumns, ...asObject(parsed.visibleColumns) },
        modes: { ...fallback.modes, ...asObject(parsed.modes) }
      };
    } catch {
      return fallback;
    }
  }

  function saveHomeConfig() {
    try {
      if (window.localStorage) {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state.homeConfig));
      }
    } catch {
      // Local storage is optional; the page should still work without it.
    }
  }

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

  function trimNumberText(text) {
    return compact(text)
      .replace(/(\.\d*?[1-9])0+$/, "$1")
      .replace(/\.0+$/, "");
  }

  function fmtCompactNumber(value, digits) {
    const n = numberValue(value);
    if (n == null) {
      return compact(value);
    }
    if (digits != null) {
      return trimNumberText(n.toFixed(digits));
    }
    const abs = Math.abs(n);
    if (abs !== 0 && (abs < 0.001 || abs >= 100000)) {
      return trimNumberText(n.toExponential(2));
    }
    if (abs >= 1000) {
      return trimNumberText(n.toFixed(0));
    }
    if (abs >= 100) {
      return trimNumberText(n.toFixed(1));
    }
    if (abs >= 10) {
      return trimNumberText(n.toFixed(2));
    }
    if (abs >= 1) {
      return trimNumberText(n.toFixed(3));
    }
    return trimNumberText(n.toFixed(4));
  }

  function fmtProbability(value) {
    const n = numberValue(value);
    if (n == null) {
      return "";
    }
    if (n > 0 && n < 0.001) {
      return trimNumberText(n.toExponential(2));
    }
    return n.toFixed(3);
  }

  function displayDigitsForUnit(unit, label) {
    const unitText = compact(unit).toLowerCase();
    const labelText = compact(label).toLowerCase();
    if (labelText === "probability" || labelText.includes("p_ub")) {
      return 3;
    }
    if (unitText.includes("deg") || ["ra", "dec"].includes(labelText)) {
      return 5;
    }
    if (unitText.includes("km") && unitText.includes("s")) {
      return 0;
    }
    if (unitText === "kpc" || unitText.endsWith(" kpc")) {
      return 2;
    }
    if (unitText === "pc" || unitText.endsWith(" pc")) {
      return 0;
    }
    if (unitText.includes("mas") || labelText.includes("pm") || labelText.includes("plx") || labelText.includes("parallax")) {
      return 3;
    }
    if (unitText.includes("mag")) {
      return 3;
    }
    if (unitText === "k" || unitText.endsWith(" k")) {
      return 0;
    }
    if (unitText.includes("dex") || labelText.includes("[fe/h]") || labelText.includes("[m/h]") || labelText.includes("log")) {
      return 2;
    }
    return null;
  }

  function formatQuantityNumber(value, quantity, label) {
    const n = numberValue(value);
    if (n == null) {
      return compact(value);
    }
    return fmtCompactNumber(n, displayDigitsForUnit(asObject(quantity).unit, label));
  }

  function formatSignedDisplayError(value, fallbackSign, quantity, label) {
    const raw = compact(value);
    if (!raw) {
      return "";
    }
    let sign = fallbackSign;
    let body = raw;
    if (raw.startsWith("±")) {
      sign = "±";
      body = raw.slice(1);
    } else if (raw.startsWith("+") || raw.startsWith("-")) {
      sign = raw[0];
      body = raw.slice(1);
    }
    return sign + formatQuantityNumber(body.trim(), quantity, label);
  }

  function renderDisplayQuantityMath(quantity, label) {
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
    let body = escapeHtml(formatQuantityNumber(value, payload, label));
    if (error) {
      body += `<span class="math-op">&plusmn;</span>${escapeHtml(formatQuantityNumber(error.replace(/^[±+\-]\s*/, ""), payload, label))}`;
    } else if (lower || upper) {
      const lowerText = formatSignedDisplayError(lower, "-", payload, label);
      const upperText = formatSignedDisplayError(upper, "+", payload, label);
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

  function displayQuantityText(quantity, label) {
    const payload = asObject(quantity);
    const value = compact(payload.value);
    if (!value) {
      return "";
    }
    let text = formatQuantityNumber(value, payload, label);
    const error = compact(payload.error);
    const lower = compact(payload.lower_error);
    const upper = compact(payload.upper_error);
    if (error) {
      text += " +/- " + formatQuantityNumber(error.replace(/^[±+\-]\s*/, ""), payload, label);
    } else if (lower || upper) {
      text += " " + formatSignedDisplayError(lower, "-", payload, label) + " " + formatSignedDisplayError(upper, "+", payload, label);
    }
    const unit = compact(payload.unit);
    if (unit) {
      text += " " + unit;
    }
    return text;
  }

  function formatIntervalNumber(value, unit, label) {
    return label === "probability" ? fmtProbability(value) : fmtCompactNumber(value, displayDigitsForUnit(unit, label));
  }

  function monthIndex(value) {
    const text = compact(value);
    const match = text.match(/^(\d{4})-(\d{2})/);
    if (!match) {
      return null;
    }
    return Number(match[1]) * 12 + Number(match[2]) - 1;
  }

  function monthLabel(index) {
    const n = numberValue(index);
    if (n == null) {
      return "";
    }
    const year = Math.floor(n / 12);
    const month = Math.round(n - year * 12) + 1;
    return `${year}-${String(month).padStart(2, "0")}`;
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

  function paperMetadataFor(arxivId) {
    return asObject(state.paperMetadata[compact(arxivId)]);
  }

  function authorYearLabel(metadata, paper) {
    const meta = asObject(metadata);
    const existing = compact(meta.reported_by);
    if (existing) {
      return existing;
    }
    const year = compact(meta.year || compact(asObject(paper).month).slice(0, 4));
    const arxivId = compact(asObject(paper).arxiv_id);
    return ["arXiv " + arxivId, year].filter((item) => compact(item) && item !== "arXiv ").join(" ");
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
    const metadata = paperMetadataFor(paper.arxiv_id);
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
      paper: {
        arxiv_id: compact(paper.arxiv_id),
        bibcode: compact(paper.bibcode),
        title: compact(paper.title),
        month: compact(paper.month),
        links: asObject(paper.links)
      },
      paper_metadata: {
        ...metadata,
        reported_by: authorYearLabel(metadata, paper)
      },
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
    const posterior = asObject(dynamics.posterior);
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
      heliocentric_distance_kpc: intervalSummary(posterior.heliocentric_distance_kpc),
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
    const discoveryMonths = uniq(sourceRows.map((source) => asObject(source.paper).month)).sort();
    return {
      object_id: compact(record.object_id),
      identifier: compact(canonical.value || record.object_id),
      identifier_kind: compact(canonical.kind),
      gaia_source_ids: uniq(sourceRows.map((source) => source.gaia_source_id)),
      paper_candidate_ids: uniq(sourceRows.map((source) => source.paper_candidate_id)),
      bibcodes: uniq(sourceRows.map((source) => source.bibcode)),
      sources: sourceRows,
      source_count: sourceRows.length,
      discovery_month: discoveryMonths[0] || "",
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
      state.paperMetadata = asObject(snapshot.paper_metadata);
      state.rows = snapshot.rows && snapshot.rows.length ? snapshot.rows : state.objects.map(buildIndexRow);
    } else {
      const root = (document.body.dataset.catalogRoot || "../../catalog").replace(/\/$/, "");
      const paperMetadataPath = document.body.dataset.paperMetadata || "assets/paper-metadata.json";
      state.index = await fetchJson(root + "/03_hvs_candidates_index.json");
      try {
        state.paperMetadata = await fetchJson(paperMetadataPath);
      } catch {
        state.paperMetadata = {};
      }
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
          <nav class="top-nav" aria-label="Main navigation">
            <a class="nav-pill ${active === "home" ? "is-active" : ""}" href="#">Catalog</a>
            <a class="nav-pill" href="#catalog-index">Stars</a>
            <a class="nav-pill" href="#column-controls">Columns</a>
            <a class="nav-pill" href="#audit">Audit</a>
          </nav>
          <div class="hero-copy">
            <div class="eyebrow">Stella object-level HVS catalog</div>
            <h1>STELLA HVS CATALOG</h1>
            <p>Object-level high-velocity-star candidates merged from literature evidence, Gaia DR3/SIMBAD enrichment, and Stella dynamical reassessments. JSON remains the source of truth; this page is a generated view for scanning, sorting, and comparing candidates.</p>
            <div class="hero-actions">
              <a class="hero-link" href="#catalog-index">Open Star Table</a>
              <a class="hero-link" href="#column-controls">Tune Columns</a>
              <a class="hero-link" href="#audit">Review Audit</a>
            </div>
          </div>
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
      sources: rows.reduce((total, row) => total + Number(row.source_count || 0), 0),
      computed: computed.length,
      unbound95: computed.filter((row) => numberValue(asObject(asObject(row.dynamics).p_unbound).median) >= 0.95).length,
      lowerLimit: rows.filter((row) => asObject(row.dynamics).lower_limit).length,
      withGaia: rows.filter((row) => compact(asObject(asObject(row.external).gaia_dr3).source_id) || asArray(row.gaia_source_ids).length).length,
      warningObjects: rows.filter((row) => allWarnings(row) > 0).length
    };
  }

  function rowRecord(row) {
    return state.objectMap.get(compact(row.object_id)) || {};
  }

  function rowSource(row, sourceId) {
    return asArray(row.sources).find((source) => source && source.source === sourceId) || {};
  }

  function sourceDisplayLabel(row, sourceId) {
    const source = rowSource(row, sourceId);
    return compact(asObject(source.paper_metadata).reported_by) || compact(source.arxiv_id) || compact(sourceId);
  }

  function objectHash(objectId) {
    return `#/object/${encodeURIComponent(compact(objectId))}`;
  }

  function objectSourceHash(objectId, sourceId) {
    return `${objectHash(objectId)}/source/${encodeURIComponent(compact(sourceId))}`;
  }

  function sourceCardId(sourceId) {
    return "source-card-" + compact(sourceId).replace(/[^A-Za-z0-9_-]+/g, "-");
  }

  function paperEntries(row) {
    return asArray(row.sources).map((source) => {
      const paper = asObject(source.paper);
      const metadata = asObject(source.paper_metadata);
      return {
        source: compact(source.source),
        label: compact(metadata.reported_by) || compact(source.arxiv_id),
        month: compact(paper.month),
        pubdate: compact(metadata.pubdate),
        citation_count: numberValue(metadata.citation_count),
        arxiv_id: compact(source.arxiv_id),
        bibcode: compact(source.bibcode),
        title: compact(paper.title || metadata.title)
      };
    });
  }

  function paperDate(entry) {
    return compact(entry.pubdate || entry.month);
  }

  function sortedPaperEntries(row, modesOverride) {
    const entries = paperEntries(row).filter((entry) => compact(entry.label));
    if (!entries.length) {
      return [];
    }
    const mode = (modesOverride || state.homeConfig.modes).reportedBy;
    return [...entries].sort((left, right) => {
      if (mode === "most_cited") {
        const citationDelta = (numberValue(right.citation_count) ?? -1) - (numberValue(left.citation_count) ?? -1);
        if (citationDelta !== 0) {
          return citationDelta;
        }
      }
      const dateCompare = paperDate(left).localeCompare(paperDate(right));
      return mode === "latest" ? -dateCompare : dateCompare;
    });
  }

  function selectedReporter(row, modesOverride) {
    return sortedPaperEntries(row, modesOverride)[0] || null;
  }

  function reporterItem(row, reporter) {
    return {
      kind: "paper",
      source: "",
      label: "",
      text: reporter.label,
      rawText: reporter.label,
      number: reporter.citation_count,
      sort: reporter.label,
      href: objectSourceHash(row.object_id, reporter.source),
      sourceId: reporter.source,
      title: [reporter.label, reporter.title, reporter.arxiv_id, reporter.bibcode].filter(Boolean).join("\n"),
      searchText: [reporter.label, reporter.arxiv_id, reporter.bibcode, reporter.title].filter(Boolean).join(" ")
    };
  }

  function quantityItem(kind, source, quantity, label) {
    const payload = asObject(quantity);
    const rawText = quantityText(payload);
    if (!rawText) {
      return null;
    }
    return {
      kind,
      source,
      label: label || "",
      text: displayQuantityText(payload, label),
      rawText,
      html: renderDisplayQuantityMath(payload, label),
      title: rawText,
      number: numberValue(payload.value),
      numbers: [numberValue(payload.value)].filter((value) => value != null)
    };
  }

  function intervalItem(kind, source, interval, unit, label, lowerLimit) {
    const summary = asObject(interval);
    const median = numberValue(summary.median);
    if (median == null) {
      return null;
    }
    const p16 = numberValue(summary.p16);
    const p84 = numberValue(summary.p84);
    const body = formatIntervalNumber(median, unit, label);
    const error = p16 != null && p84 != null ? Math.abs(p84 - p16) / 2 : null;
    const errorText = label !== "probability" && error != null ? formatIntervalNumber(error, unit, label) : "";
    const intervalTextValue = errorText ? `${body} +/- ${errorText}` : body;
    const unitHtml = renderUnit(unit);
    const htmlBody = errorText
      ? `${escapeHtml(body)}<span class="math-op">&plusmn;</span>${escapeHtml(errorText)}`
      : escapeHtml(body);
    const exactInterval = [
      `median ${compact(summary.median)}`,
      p16 != null ? `p16 ${compact(summary.p16)}` : "",
      p84 != null ? `p84 ${compact(summary.p84)}` : "",
      unit
    ].filter(Boolean).join(" ");
    return {
      kind,
      source,
      label: label || "",
      text: [intervalTextValue, unit].filter(Boolean).join(" "),
      rawText: exactInterval,
      html: `<span class="math-formula quantity-math" aria-label="${escapeHtml(exactInterval)}">${htmlBody}${unitHtml ? `<span class="math-unit">${unitHtml}</span>` : ""}</span>`,
      title: exactInterval,
      number: median,
      numbers: [median, p16, p84].filter((value) => value != null),
      lowerLimit: Boolean(lowerLimit)
    };
  }

  function literatureQuantityItems(row, group, field, label) {
    const record = rowRecord(row);
    return asArray(record.candidates)
      .map((candidate) => {
        const quantity = asObject(asObject(asObject(candidate.core)[group])[field]);
        return quantityItem("paper", sourceDisplayLabel(row, candidate.source), quantity, label);
      })
      .filter(Boolean);
  }

  function literatureParameterItems(row, field, label) {
    const record = rowRecord(row);
    return asArray(record.candidates)
      .map((candidate) => quantityItem("paper", sourceDisplayLabel(row, candidate.source), asObject(asObject(candidate.stellar_parameters)[field]), label))
      .filter(Boolean);
  }

  function literatureSpectralTypeItems(row) {
    const record = rowRecord(row);
    const items = [];
    asArray(record.candidates).forEach((candidate) => {
      const source = sourceDisplayLabel(row, candidate.source);
      const stellar = asObject(candidate.stellar_parameters);
      const stellarType = asObject(stellar.spectral_type);
      const stellarText = compact(stellarType.value || stellarType.spectral_type);
      if (stellarText) {
        items.push({ kind: "paper", source, text: stellarText, label: "paper" });
      }
      asArray(candidate.spectroscopy).forEach((entry) => {
        const text = compact(entry.spectral_type || entry.value);
        if (text) {
          items.push({ kind: "paper", source, text, label: "paper" });
        }
      });
    });
    return items;
  }

  function literatureMetallicityItems(row) {
    const record = rowRecord(row);
    const items = literatureParameterItems(row, "metallicity", "[Fe/H]");
    asArray(record.candidates).forEach((candidate) => {
      const source = sourceDisplayLabel(row, candidate.source);
      asArray(candidate.abundances).forEach((entry) => {
        const element = compact(entry.element);
        const ref = compact(entry.reference_element);
        if (element === "Fe" && ref === "H") {
          const item = quantityItem("paper", source, entry, "[Fe/H]");
          if (item) {
            items.push(item);
          }
        }
      });
    });
    return items;
  }

  function externalProvider(record, provider) {
    return asObject(asObject(asObject(record.external_enrichment).providers)[provider]);
  }

  function providerQuantity(record, provider, group, field) {
    return asObject(asObject(externalProvider(record, provider)[group])[field]);
  }

  function gaiaItem(row, group, field, label) {
    return quantityItem("gaia", "Gaia DR3", providerQuantity(rowRecord(row), "gaia_dr3", group, field), label);
  }

  function simbadItem(row, group, field, label) {
    return quantityItem("simbad", "SIMBAD", providerQuantity(rowRecord(row), "simbad", group, field), label);
  }

  function tupleItem(kind, source, parts, label) {
    const valid = parts.filter((part) => part && compact(part.text));
    if (!valid.length) {
      return null;
    }
    return {
      kind,
      source,
      label,
      text: "(" + valid.map((part) => part.text).join(", ") + ")",
      rawText: "(" + valid.map((part) => part.rawText || part.text).join(", ") + ")",
      html: `<span class="tuple-paren">(</span>${valid.map((part) => part.html || textWithMath(part.text)).join('<span class="tuple-separator">, </span>')}<span class="tuple-paren">)</span>`,
      title: "(" + valid.map((part) => part.title || part.rawText || part.text).join(", ") + ")",
      number: valid[0].number,
      numbers: valid.flatMap((part) => asArray(part.numbers).length ? part.numbers : [part.number]).filter((value) => value != null)
    };
  }

  function currentColumnItems(row, key, modesOverride) {
    const dynamics = asObject(row.dynamics);
    const modes = modesOverride || state.homeConfig.modes;
    const record = rowRecord(row);
    if (key === "discovery") {
      const month = compact(row.discovery_month) || paperEntries(row).map((entry) => entry.month).filter(Boolean).sort()[0] || "";
      const index = monthIndex(month);
      return month ? [{ kind: "paper", source: "", text: month, number: index, numbers: index == null ? [] : [index], sort: month }] : [];
    }
    if (key === "reported_by") {
      if (modes.reportedBy === "all") {
        return sortedPaperEntries(row, { ...modes, reportedBy: "earliest" }).map((reporter) => reporterItem(row, reporter));
      }
      const reporter = selectedReporter(row, modes);
      return reporter ? [reporterItem(row, reporter)] : [];
    }
    if (key === "total_velocity") {
      const items = [];
      if (modes.velocity === "stella" || modes.velocity === "both") {
        const item = intervalItem("stella", "Stella", dynamics.total_velocity_grf_kms, "km s^-1", "vGRF", dynamics.lower_limit);
        if (item) {
          items.push(item);
        }
      }
      if (modes.velocity === "literature" || modes.velocity === "both") {
        items.push(...literatureQuantityItems(row, "derived_kinematics", "total_velocity", "paper"));
      }
      return items;
    }
    if (key === "p_unbound") {
      const items = [];
      if (modes.pUnbound === "stella" || modes.pUnbound === "both") {
        const item = intervalItem("stella", "Stella", dynamics.p_unbound, "", "probability", dynamics.lower_limit);
        if (item) {
          items.push(item);
        }
      }
      if (modes.pUnbound === "literature" || modes.pUnbound === "both") {
        items.push(...literatureQuantityItems(row, "bound_assessment", "unbound_probability", "paper"));
      }
      return items;
    }
    if (key === "radial_velocity") {
      return literatureQuantityItems(row, "observed_phase_space", "radial_velocity", "paper");
    }
    if (key === "radec") {
      return [tupleItem("gaia", "Gaia DR3", [
        gaiaItem(row, "astrometry", "ra", "RA"),
        gaiaItem(row, "astrometry", "dec", "Dec")
      ], "RA, Dec")].filter(Boolean);
    }
    if (key === "pm") {
      return [tupleItem("gaia", "Gaia DR3", [
        gaiaItem(row, "astrometry", "pmra", "pmRA"),
        gaiaItem(row, "astrometry", "pmdec", "pmDec")
      ], "pmRA, pmDec")].filter(Boolean);
    }
    if (key === "parallax") {
      return [gaiaItem(row, "astrometry", "parallax", "Gaia")].filter(Boolean);
    }
    if (key === "distance") {
      const items = [];
      if (modes.distance === "literature" || modes.distance === "all") {
        items.push(...literatureQuantityItems(row, "observed_phase_space", "distance", "paper"));
      }
      if (modes.distance === "stella" || modes.distance === "all") {
        const item = intervalItem("stella", "Stella", dynamics.heliocentric_distance_kpc, "kpc", "posterior", dynamics.lower_limit);
        if (item) {
          items.push(item);
        }
      }
      if (modes.distance === "gaia" || modes.distance === "all") {
        const item = gaiaItem(row, "stellar_parameters", "distance_gspphot", "distance_gspphot");
        if (item) {
          items.push(item);
        }
      }
      return items;
    }
    if (key === "g_mag") {
      return [gaiaItem(row, "photometry", "phot_g_mean_mag", "Gaia G")].filter(Boolean);
    }
    if (key === "bp_rp") {
      return [gaiaItem(row, "photometry", "bp_rp", "Gaia BP-RP")].filter(Boolean);
    }
    if (key === "spectral_type") {
      const items = [];
      if (modes.spectralType === "paper" || modes.spectralType === "both") {
        items.push(...literatureSpectralTypeItems(row));
      }
      if (modes.spectralType === "simbad" || modes.spectralType === "both") {
        const spectral = asObject(externalProvider(record, "simbad").spectral_type);
        const text = compact(spectral.value);
        if (text) {
          items.push({ kind: "simbad", source: "SIMBAD", text, label: "SIMBAD" });
        }
      }
      return items;
    }
    if (key === "metallicity") {
      const items = [];
      if (modes.metallicity === "paper" || modes.metallicity === "both") {
        items.push(...literatureMetallicityItems(row));
      }
      if (modes.metallicity === "gaia" || modes.metallicity === "both") {
        const item = gaiaItem(row, "stellar_parameters", "mh_gspphot", "[M/H]");
        if (item) {
          items.push(item);
        }
      }
      return items;
    }
    if (key === "teff") {
      const items = [];
      if (modes.teff === "paper" || modes.teff === "both") {
        items.push(...literatureParameterItems(row, "teff", "paper"));
      }
      if (modes.teff === "gaia" || modes.teff === "both") {
        const item = gaiaItem(row, "stellar_parameters", "teff_gspphot", "Gaia");
        if (item) {
          items.push(item);
        }
      }
      return items;
    }
    if (key === "log_g") {
      const items = [];
      if (modes.logG === "paper" || modes.logG === "both") {
        items.push(...literatureParameterItems(row, "log_g", "paper"));
      }
      if (modes.logG === "gaia" || modes.logG === "both") {
        const item = gaiaItem(row, "stellar_parameters", "logg_gspphot", "Gaia");
        if (item) {
          items.push(item);
        }
      }
      return items;
    }
    return [];
  }

  function columnByKey(key) {
    return HOME_COLUMNS.find((column) => column.key === key) || { key, label: key, type: "text" };
  }

  function visibleColumns() {
    return HOME_COLUMNS.filter((column) => state.homeConfig.visibleColumns[column.key] !== false);
  }

  function itemNumbers(item) {
    return asArray(item.numbers).filter((value) => numberValue(value) != null).map(Number);
  }

  function itemText(item) {
    return [item.text, item.rawText, item.searchText, item.source, item.label, item.lowerLimit ? "lower limit" : ""].filter(Boolean).join(" ");
  }

  function rowSearchText(row) {
    const context = asObject(row.candidate_context);
    return [
      row.object_id,
      row.identifier,
      row.identifier_kind,
      ...(row.gaia_source_ids || []),
      ...(row.paper_candidate_ids || []),
      ...(row.bibcodes || []),
      ...(context.paper_labels || []),
      ...HOME_COLUMNS.flatMap((column) => currentColumnItems(row, column.key).map(itemText))
    ].join(" ").toLowerCase();
  }

  function numericColumnStats(column) {
    if (!RANGE_FILTER_KEYS.has(column.key)) {
      return null;
    }
    const values = state.rows.flatMap((row) => currentColumnItems(row, column.key).flatMap(itemNumbers));
    if (!values.length) {
      return null;
    }
    return {
      min: Math.min(...values),
      max: Math.max(...values)
    };
  }

  function filterValue(column, stats, edge) {
    const filter = asObject(state.rangeFilters[column.key]);
    const raw = parseFilterInput(column, filter[edge]);
    const fallback = edge === "min" ? stats.min : stats.max;
    return raw == null ? fallback : raw;
  }

  function parseFilterInput(column, value) {
    const text = compact(value);
    if (!text) {
      return null;
    }
    if (column.type === "date") {
      return monthIndex(text);
    }
    return numberValue(text);
  }

  function filterInputValue(column, stats, edge) {
    const filter = asObject(state.rangeFilters[column.key]);
    const raw = compact(filter[edge]);
    if (raw) {
      return raw;
    }
    const fallback = edge === "min" ? stats.min : stats.max;
    return column.type === "date" ? monthLabel(fallback) : String(fallback);
  }

  function filterValidationErrors(column, stats) {
    const filter = asObject(state.rangeFilters[column.key]);
    if (!filter.enabled) {
      return [];
    }
    const errors = [];
    const minRaw = compact(filter.min);
    const maxRaw = compact(filter.max);
    const minValue = filterValue(column, stats, "min");
    const maxValue = filterValue(column, stats, "max");
    if (minRaw && parseFilterInput(column, minRaw) == null) {
      errors.push(column.type === "date" ? "Min must use YYYY-MM." : "Min must be a number.");
    }
    if (maxRaw && parseFilterInput(column, maxRaw) == null) {
      errors.push(column.type === "date" ? "Max must use YYYY-MM." : "Max must be a number.");
    }
    if (minValue < stats.min || minValue > stats.max || maxValue < stats.min || maxValue > stats.max) {
      errors.push(`Allowed range is ${filterDisplayValue(column, stats.min)} - ${filterDisplayValue(column, stats.max)}.`);
    }
    if (minValue > maxValue) {
      errors.push("Min cannot exceed max.");
    }
    return errors;
  }

  function rangeFilterMatches(row, column) {
    const filter = asObject(state.rangeFilters[column.key]);
    if (!filter.enabled) {
      return true;
    }
    const stats = numericColumnStats(column);
    if (!stats) {
      return true;
    }
    if (filterValidationErrors(column, stats).length) {
      return true;
    }
    const low = filterValue(column, stats, "min");
    const high = filterValue(column, stats, "max");
    const values = currentColumnItems(row, column.key).flatMap(itemNumbers);
    return values.some((value) => value >= Math.min(low, high) && value <= Math.max(low, high));
  }

  function passesFilters(row) {
    const query = state.filter.trim().toLowerCase();
    if (query && !rowSearchText(row).includes(query)) {
      return false;
    }
    return HOME_COLUMNS.every((column) => rangeFilterMatches(row, column));
  }

  function sortValue(row, key) {
    if (key === "identifier") {
      return compact(row.identifier);
    }
    if (key === "warnings") {
      return allWarnings(row);
    }
    const items = currentColumnItems(row, key);
    const column = columnByKey(key);
    if (column.type === "number") {
      for (const item of items) {
        const numbers = itemNumbers(item);
        if (numbers.length) {
          return numbers[0];
        }
      }
      return null;
    }
    if (column.type === "date") {
      return compact(asObject(items[0]).sort || asObject(items[0]).text);
    }
    return compact(asObject(items[0]).sort || asObject(items[0]).text);
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
          return compact(left.identifier).localeCompare(compact(right.identifier), undefined, { numeric: true });
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

  function dynamicsTone(status) {
    const text = compact(status).toLowerCase();
    if (text === "computed") {
      return "good";
    }
    if (text === "not_computed" || text === "missing" || text === "skipped") {
      return "quiet";
    }
    if (text.includes("fail") || text.includes("error") || text.includes("warning")) {
      return "warn";
    }
    return "neutral";
  }

  function renderSortButton(label, key) {
    const active = state.sortKey === key;
    const dir = active ? (state.sortDir === "asc" ? " ↑" : " ↓") : " ↕";
    return `<span class="sort-button${active ? " is-active" : ""}">${escapeHtml(label)}${escapeHtml(dir)}</span>`;
  }

  function renderHeaderLabel(label) {
    return `<span class="plain-header-label">${escapeHtml(label)}</span>`;
  }

  function renderHomeHeader(column) {
    if (!SORTABLE_HOME_KEYS.has(column.key)) {
      return `<th>${renderHeaderLabel(column.label)}</th>`;
    }
    return `<th class="sortable-header" data-sort="${escapeHtml(column.key)}">${renderSortButton(column.label, column.key)}</th>`;
  }

  function renderPills(values, tone) {
    return asArray(values).map((value) => badge(value, tone || "neutral")).join("");
  }

  function renderScienceMetrics() {
    const stats = computeStats(state.rows);
    return `
      <section class="metric-strip">
        ${metric("Objects", stats.objects, "merged stars")}
        ${metric("Source records", stats.sources, "paper-level entries")}
        ${metric("Dynamics computed", stats.computed, "Stella posterior")}
        ${metric("P_ub >= 0.95", stats.unbound95, "Stella probability")}
        ${metric("Gaia DR3 matched", stats.withGaia, "astroquery cache")}
        ${metric("Warnings", stats.warningObjects, "merge, enrichment, dynamics")}
      </section>
    `;
  }

  function option(value, label, current) {
    return `<option value="${escapeHtml(value)}"${value === current ? " selected" : ""}>${escapeHtml(label)}</option>`;
  }

  function modeOptionsForColumn(columnKey) {
    const config = SOURCE_MODE_COLUMNS[columnKey];
    if (!config) {
      return [];
    }
    return config.options.filter(([value]) => {
      const modes = { ...state.homeConfig.modes, [config.modeKey]: value };
      return state.rows.some((row) => currentColumnItems(row, columnKey, modes).length > 0);
    });
  }

  function normalizeHomeModeAvailability() {
    Object.entries(SOURCE_MODE_COLUMNS).forEach(([columnKey, config]) => {
      const available = modeOptionsForColumn(columnKey);
      if (!available.length) {
        return;
      }
      const current = state.homeConfig.modes[config.modeKey];
      if (!available.some(([value]) => value === current)) {
        state.homeConfig.modes[config.modeKey] = available[0][0];
      }
    });
  }

  function renderSourceSelector(column) {
    const config = SOURCE_MODE_COLUMNS[column.key];
    if (config) {
      const options = modeOptionsForColumn(column.key);
      if (!options.length) {
        return `<span class="source-static">—</span>`;
      }
      return `
        <select class="source-select" data-home-mode="${escapeHtml(config.modeKey)}" aria-label="${escapeHtml(column.label)} source">
          ${options.map(([value, text]) => option(value, text, state.homeConfig.modes[config.modeKey])).join("")}
        </select>
      `;
    }
    const label = STATIC_SOURCE_LABELS[column.key];
    return label ? `<span class="source-static">${escapeHtml(label)}</span>` : "";
  }

  function filterDisplayValue(column, value) {
    if (column.type === "date") {
      return monthLabel(value);
    }
    if (column.key === "p_unbound") {
      return fmtProbability(value);
    }
    return fmtNumber(value);
  }

  function filterStep(column, stats) {
    if (column.type === "date") {
      return "1";
    }
    if (column.key === "p_unbound") {
      return "0.001";
    }
    const span = Math.abs(stats.max - stats.min);
    if (!span) {
      return "1";
    }
    return String(Math.max(span / 200, 0.001).toPrecision(3));
  }

  function renderRangeFilter(column) {
    const stats = numericColumnStats(column);
    if (!stats) {
      return "";
    }
    const filter = asObject(state.rangeFilters[column.key]);
    const enabled = filter.enabled === true;
    const minValue = filterInputValue(column, stats, "min");
    const maxValue = filterInputValue(column, stats, "max");
    const step = filterStep(column, stats);
    const disabled = enabled ? "" : " disabled";
    const inputType = column.type === "date" ? "month" : "number";
    const minAttr = column.type === "date" ? monthLabel(stats.min) : String(stats.min);
    const maxAttr = column.type === "date" ? monthLabel(stats.max) : String(stats.max);
    const errors = filterValidationErrors(column, stats);
    return `
      <article class="range-filter${enabled ? " is-enabled" : ""}${errors.length ? " has-error" : ""}" data-filter-card="${escapeHtml(column.key)}">
        <label class="range-enable">
          <input type="checkbox" data-range-enable="${escapeHtml(column.key)}"${enabled ? " checked" : ""}>
          <span>${escapeHtml(column.label)}</span>
        </label>
        <div class="filter-bounds">Allowed ${escapeHtml(filterDisplayValue(column, stats.min))} - ${escapeHtml(filterDisplayValue(column, stats.max))}</div>
        <div class="range-pair">
          <label>
            <span>Min</span>
            <input type="${inputType}" data-filter-bound="${escapeHtml(column.key)}" data-filter-edge="min" min="${escapeHtml(minAttr)}" max="${escapeHtml(maxAttr)}" step="${escapeHtml(step)}" value="${escapeHtml(minValue)}"${disabled}>
          </label>
          <label>
            <span>Max</span>
            <input type="${inputType}" data-filter-bound="${escapeHtml(column.key)}" data-filter-edge="max" min="${escapeHtml(minAttr)}" max="${escapeHtml(maxAttr)}" step="${escapeHtml(step)}" value="${escapeHtml(maxValue)}"${disabled}>
          </label>
        </div>
        ${errors.length ? `<div class="filter-error" role="alert">${escapeHtml(errors[0])}</div>` : ""}
      </article>
    `;
  }

  function renderRangeFilters() {
    const cards = HOME_COLUMNS
      .filter((column) => RANGE_FILTER_KEYS.has(column.key))
      .map(renderRangeFilter)
      .filter(Boolean)
      .join("");
    if (!cards) {
      return "";
    }
    return `
      <div class="range-filter-header">
        <h3>Filters</h3>
      </div>
      <div class="range-filter-grid">${cards}</div>
    `;
  }

  function renderRangeFiltersRegion() {
    return `<div id="range-filter-region">${renderRangeFilters()}</div>`;
  }

  function updateRangeFilters() {
    const region = document.getElementById("range-filter-region");
    if (!region) {
      return;
    }
    region.innerHTML = renderRangeFilters();
  }

  function renderColumnControls() {
    return `
      <section class="control-panel" id="column-controls">
        <div class="control-heading">
          <h2 class="section-heading">Column Controls</h2>
          <button class="secondary-button" data-reset-columns type="button">Reset</button>
        </div>
        <div class="column-toggle-grid">
          ${HOME_COLUMNS.map((column) => `
            <label class="toggle-field">
              <input type="checkbox" data-visible-column="${escapeHtml(column.key)}"${state.homeConfig.visibleColumns[column.key] !== false ? " checked" : ""}>
              <span>${escapeHtml(column.label)}</span>
            </label>
          `).join("")}
        </div>
        ${renderRangeFiltersRegion()}
      </section>
    `;
  }

  function renderCatalogToolbar(rows, sourceRowCount) {
    return `
      <section class="catalog-tools" id="catalog-index">
        <div>
          <h2 class="section-heading">Star Index</h2>
          <div class="table-count">Showing ${rows.length} of ${state.rows.length} objects / ${sourceRowCount} source rows</div>
        </div>
        <label class="filter-field global-search">
          <span>Search all visible/source fields</span>
          <input id="catalog-search" type="search" value="${escapeHtml(state.filter)}" autocomplete="off">
        </label>
      </section>
    `;
  }

  function longDigitToken(value) {
    const match = compact(value).match(/\d{10,}/);
    return match ? match[0] : "";
  }

  function normalizedIdentifier(value) {
    return compact(value).toLowerCase().replace(/gaia\s*e?dr3/g, "").replace(/[^a-z0-9]+/g, "");
  }

  function equivalentIdentifier(left, right) {
    const leftDigits = longDigitToken(left);
    const rightDigits = longDigitToken(right);
    if (leftDigits && rightDigits && leftDigits === rightDigits) {
      return true;
    }
    const a = normalizedIdentifier(left);
    const b = normalizedIdentifier(right);
    return Boolean(a && b && a === b);
  }

  function renderIdentifierCell(row) {
    const identifier = compact(row.identifier || row.object_id);
    const objectId = compact(row.object_id);
    const secondary = [];
    if (objectId && !equivalentIdentifier(identifier, objectId)) {
      secondary.push(objectId);
    }
    return `
      <div class="identifier-cell-inner">
        <a class="identifier-main js-object-link" href="${objectHash(row.object_id)}" data-object-id="${escapeHtml(row.object_id)}">${escapeHtml(identifier)}</a>
        ${secondary.map((item) => `<span class="identifier-muted">${escapeHtml(item)}</span>`).join("")}
      </div>
    `;
  }

  function renderCellValue(row, item) {
    const value = item.html || textWithMath(item.text || "—");
    if (item.href) {
      return `<a class="cell-link js-object-link" href="${escapeHtml(item.href)}" data-object-id="${escapeHtml(row.object_id)}" data-source-id="${escapeHtml(item.sourceId || "")}">${value}</a>`;
    }
    return value;
  }

  function sourcePartsEquivalent(left, right) {
    const a = compact(left).toLowerCase();
    const b = compact(right).toLowerCase();
    return Boolean(a && b && (a === b || a.includes(b) || b.includes(a)));
  }

  function cellSourceLabel(item, columnKey) {
    if (SOURCE_LABEL_SUPPRESSED_COLUMNS.has(columnKey)) {
      return "";
    }
    if (item.kind === "paper") {
      return compact(item.source) || "paper";
    }
    if (item.kind === "stella") {
      return "Stella";
    }
    if (item.kind === "gaia") {
      return "Gaia DR3";
    }
    if (item.kind === "simbad") {
      return "SIMBAD";
    }
    const label = compact(item.label);
    const source = compact(item.source);
    if (!label || sourcePartsEquivalent(label, source)) {
      return source || label;
    }
    return [label, source].filter(Boolean).join(" · ");
  }

  function cellTitle(item, columnKey) {
    const pieces = [
      compact(item.title || item.rawText || item.text),
      cellSourceLabel(item, columnKey) ? "source: " + cellSourceLabel(item, columnKey) : ""
    ].filter(Boolean);
    return pieces.join("\n");
  }

  function renderCellItems(row, items, columnKey) {
    if (!items.length) {
      return `<span class="empty-inline">—</span>`;
    }
    return `
      <div class="cell-stack">
        ${items.map((item) => {
          const sourceLabel = cellSourceLabel(item, columnKey);
          const title = cellTitle(item, columnKey);
          return `
          <div class="cell-item"${title ? ` title="${escapeHtml(title)}"` : ""}>
            <strong class="cell-value${columnKey === "p_unbound" ? ` tone-${probabilityTone(item.number)}` : ""}">${renderCellValue(row, item)}</strong>
            ${sourceLabel ? `<span class="cell-source">${escapeHtml(sourceLabel)}</span>` : ""}
            ${item.lowerLimit ? badge("lower limit", "warn") : ""}
          </div>
        `;
        }).join("")}
      </div>
    `;
  }

  function renderHomeCell(row, column) {
    return renderCellItems(row, currentColumnItems(row, column.key), column.key);
  }

  function renderCatalogTable() {
    normalizeHomeModeAvailability();
    const columns = visibleColumns();
    const rows = filteredRows();
    const sourceRowCount = rows.reduce((total, row) => total + Math.max(1, asArray(row.sources).length), 0);
    const colCount = columns.length + 2;
    const body = rows.map((row) => `
      <tr>
        <td class="sticky-object">${renderIdentifierCell(row)}</td>
        ${columns.map((column) => `<td>${renderHomeCell(row, column)}</td>`).join("")}
        <td><a class="more-link js-object-link" href="${objectHash(row.object_id)}" data-object-id="${escapeHtml(row.object_id)}">Details</a></td>
      </tr>
    `).join("");
    return `
      ${renderCatalogToolbar(rows, sourceRowCount)}
      <div class="table-wrap">
        <table class="catalog-table">
          <colgroup>
            <col class="col-object">
            ${columns.map((column) => `<col class="${escapeHtml(column.widthClass || "")}">`).join("")}
            <col class="col-more">
          </colgroup>
          <thead>
            <tr>
              <th class="sticky-object">${renderHeaderLabel("Object")}</th>
              ${columns.map(renderHomeHeader).join("")}
              <th>Detail</th>
            </tr>
            <tr class="source-row">
              <th class="sticky-object"><span class="source-static">primary</span></th>
              ${columns.map((column) => `<th>${renderSourceSelector(column)}</th>`).join("")}
              <th></th>
            </tr>
          </thead>
          <tbody>${body || `<tr><td colspan="${colCount}"><div class="empty-state">No matching objects.</div></td></tr>`}</tbody>
        </table>
      </div>
    `;
  }

  function renderCatalogTableRegion() {
    return `<section id="catalog-table-region">${renderCatalogTable()}</section>`;
  }

  function updateCatalogTable() {
    if (catalogTableRenderTimer) {
      window.clearTimeout(catalogTableRenderTimer);
      catalogTableRenderTimer = null;
    }
    const region = document.getElementById("catalog-table-region");
    if (!region) {
      renderHome();
      return;
    }
    region.innerHTML = renderCatalogTable();
  }

  function scheduleCatalogTableUpdate(delay) {
    if (catalogTableRenderTimer) {
      window.clearTimeout(catalogTableRenderTimer);
    }
    catalogTableRenderTimer = window.setTimeout(() => {
      catalogTableRenderTimer = null;
      updateCatalogTable();
    }, delay == null ? 150 : delay);
  }

  function renderHome() {
    normalizeHomeModeAvailability();
    const content = `
      ${renderScienceMetrics()}
      ${renderColumnControls()}
      ${renderCatalogTableRegion()}
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
                <article class="source-card" id="${escapeHtml(sourceCardId(source.source))}">
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

  function focusSourceCard(sourceId) {
    if (!compact(sourceId)) {
      return;
    }
    window.requestAnimationFrame(() => {
      const target = document.getElementById(sourceCardId(sourceId));
      if (target) {
        target.classList.add("is-focused-source");
        target.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
  }

  function renderDetail(objectId, focusSourceId) {
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
    focusSourceCard(focusSourceId);
  }

  function parseObjectRoute(hash) {
    const prefix = "#/object/";
    if (!hash.startsWith(prefix)) {
      return null;
    }
    const parts = hash.slice(prefix.length).split("/");
    return {
      objectId: decodeURIComponent(parts[0] || ""),
      sourceId: parts[1] === "source" ? decodeURIComponent(parts.slice(2).join("/") || "") : ""
    };
  }

  function filterCardFor(columnKey) {
    const cssEscape = window.CSS && typeof window.CSS.escape === "function"
      ? window.CSS.escape
      : (value) => String(value).replace(/["\\]/g, "\\$&");
    return document.querySelector(`[data-filter-card="${cssEscape(columnKey)}"]`);
  }

  function updateFilterCardState(columnKey) {
    const card = filterCardFor(columnKey);
    const column = columnByKey(columnKey);
    const stats = numericColumnStats(column);
    if (!card || !stats) {
      return;
    }
    const filter = asObject(state.rangeFilters[columnKey]);
    const enabled = filter.enabled === true;
    const errors = filterValidationErrors(column, stats);
    card.classList.toggle("is-enabled", enabled);
    card.classList.toggle("has-error", errors.length > 0);
    card.querySelectorAll("[data-filter-bound]").forEach((input) => {
      input.disabled = !enabled;
    });
    let errorNode = card.querySelector(".filter-error");
    if (errors.length) {
      if (!errorNode) {
        errorNode = document.createElement("div");
        errorNode.className = "filter-error";
        errorNode.setAttribute("role", "alert");
        card.appendChild(errorNode);
      }
      errorNode.textContent = errors[0];
    } else if (errorNode) {
      errorNode.remove();
    }
  }

  function updateFilterBound(target) {
    const columnKey = target && target.dataset ? target.dataset.filterBound : "";
    if (!columnKey) {
      return false;
    }
    const edge = target.dataset.filterEdge === "max" ? "max" : "min";
    const current = { ...asObject(state.rangeFilters[columnKey]), enabled: true };
    current[edge] = target.value;
    state.rangeFilters[columnKey] = current;
    updateFilterCardState(columnKey);
    scheduleCatalogTableUpdate();
    return true;
  }

  function route() {
    const hash = window.location.hash || "";
    const objectRoute = parseObjectRoute(hash);
    if (objectRoute) {
      renderDetail(objectRoute.objectId, objectRoute.sourceId);
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
    const objectLink = event.target.closest(".js-object-link");
    if (objectLink) {
      const href = objectLink.getAttribute("href") || "";
      if (href.startsWith("#/object/")) {
        event.preventDefault();
        if (window.location.hash === href) {
          route();
        } else {
          window.location.hash = href;
        }
        return;
      }
    }

    const sortButton = event.target.closest("[data-sort]");
    if (sortButton) {
      const key = sortButton.dataset.sort;
      if (!SORTABLE_HOME_KEYS.has(key)) {
        return;
      }
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = key === "identifier" || columnByKey(key).type === "date" ? "asc" : "desc";
      }
      updateCatalogTable();
      return;
    }

    const resetColumns = event.target.closest("[data-reset-columns]");
    if (resetColumns) {
      state.homeConfig = cloneDefaultHomeConfig();
      state.rangeFilters = {};
      saveHomeConfig();
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
      const objectId = asObject(parseObjectRoute(window.location.hash || "")).objectId;
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
      scheduleCatalogTableUpdate();
      return;
    }
    if (updateFilterBound(event.target)) {
      return;
    }
    const rangeKey = event.target && event.target.dataset ? event.target.dataset.rangeFilter : "";
    if (rangeKey) {
      return;
    }
  });

  app.addEventListener("change", (event) => {
    const mode = event.target && event.target.dataset ? event.target.dataset.homeMode : "";
    if (mode && Object.prototype.hasOwnProperty.call(state.homeConfig.modes, mode)) {
      state.homeConfig.modes[mode] = event.target.value;
      saveHomeConfig();
      normalizeHomeModeAvailability();
      updateRangeFilters();
      updateCatalogTable();
      return;
    }
    const visibleColumn = event.target && event.target.dataset ? event.target.dataset.visibleColumn : "";
    if (visibleColumn && Object.prototype.hasOwnProperty.call(state.homeConfig.visibleColumns, visibleColumn)) {
      state.homeConfig.visibleColumns[visibleColumn] = Boolean(event.target.checked);
      saveHomeConfig();
      renderHome();
      return;
    }
    const filterBound = event.target && event.target.dataset ? event.target.dataset.filterBound : "";
    if (filterBound) {
      updateFilterBound(event.target);
      return;
    }
    const rangeEnable = event.target && event.target.dataset ? event.target.dataset.rangeEnable : "";
    if (rangeEnable) {
      const column = columnByKey(rangeEnable);
      const stats = numericColumnStats(column);
      const current = { ...asObject(state.rangeFilters[rangeEnable]) };
      current.enabled = Boolean(event.target.checked);
      if (stats) {
        if (!compact(current.min)) {
          current.min = column.type === "date" ? monthLabel(stats.min) : String(stats.min);
        }
        if (!compact(current.max)) {
          current.max = column.type === "date" ? monthLabel(stats.max) : String(stats.max);
        }
      }
      state.rangeFilters[rangeEnable] = current;
      updateFilterCardState(rangeEnable);
      updateCatalogTable();
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
