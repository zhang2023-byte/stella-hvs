# Environment Setup

## Create the Environment

```bash
conda env create -f environment.yml
conda activate stella-env
```

If the environment already exists but dependencies changed:

```bash
conda env update -f environment.yml --prune
conda activate stella-env
```

The environment installs Stella as an editable package (`pip install -e .`); runtime dependencies are declared in `pyproject.toml`. They cover local literature archiving, PDF text inspection, PDF page rendering, HTML parsing, network requests, Pydantic schema validation, external catalog table parsing, object-catalog enrichment, and HVS dynamical reassessment. PDF page rendering uses Poppler from `environment.yml`; PDF text extraction and page-level inspection use `pymupdf`, `pypdf`, and `pdfplumber`. FITS, VOTable, and CDS/MRT ASCII are read through `astropy`; SIMBAD/Gaia DR3 enrichment and optional Gaia DR3 dynamics refresh queries use `astroquery` and `pyvo`; Gaia DR3 parallax zero-point correction uses `gaiadr3-zeropoint`; Bayesian kinematics and escape comparisons use `emcee`, `scipy`, and `galpy`.

Node.js 22 is included for the React benchmark Dev Console. The Python server
uses the committed production bundle, so normal operation does not require a
live Vite server. Rebuild and test the frontend after changing its source:

```bash
cd benchmark/console
npm ci
npm test
npm run build
cd ../..
```

`npm run build` writes the Python-served bundle to
`src/stella/web/assets/benchmark-console/`. Do not edit that generated bundle
by hand.

## PDF Toolchain Check

The benchmark and review workflows treat the archived paper PDF as the
normative reading source. After creating or updating the environment, verify the
PDF toolchain once:

```bash
conda run -n stella-env python -c "import fitz, pypdf, pdfplumber; print('python PDF packages OK')"
conda run -n stella-env pdfinfo -v
conda run -n stella-env pdftoppm -v
```

For a real archived paper, render the first page into a scratch directory:

```bash
mkdir -p /tmp/stella-pdf-check
conda run -n stella-env pdftoppm -f 1 -l 1 -png literature/1912.02129/arxiv.pdf /tmp/stella-pdf-check/page
```

Delete `/tmp/stella-pdf-check` after the check if you do not need the rendered
PNG.

## Optional External Tools

The table extraction workflow prefers LaTeXML to convert paper LaTeX tables to HTML before producing ECSV. On macOS:

```bash
brew install latexml
```

Check that it is available:

```bash
which latexmlc
latexmlc --VERSION
```

If LaTeXML is unavailable, `scripts/extract_catalog_tables.py` tries Pandoc. If Pandoc is also unavailable, it falls back to the in-project lightweight LaTeX parser, but complex tables may lose fidelity.

## Configure `.env`

Project secrets live in `.env`; this file is not committed to Git:

```bash
cp .env.example .env
```

If you use `--source deepxiv`, or run DeepXiv-enhanced `catalog_assessment`, set:

```env
DEEPXIV_TOKEN=
ADS_API_TOKEN=
```

For benchmark gold annotation and scoring work, also point `STELLA_GOLD_DIR`
at the private gold repository's `gold/` directory (gold annotations live
outside this workspace; see `benchmark/README.md`):

```env
STELLA_GOLD_DIR=~/Documents/MyProject/stella-hvs-gold/gold
```

### DeepXiv token

DeepXiv search is provided by the `deepxiv-sdk` package
([github.com/DeepXiv/deepxiv_sdk](https://github.com/DeepXiv/deepxiv_sdk),
[API docs](https://data.rag.ac.cn/api/docs)). It is already installed by
`environment.yml`. The simplest way to get a token:

```bash
# Interactive: registers/saves a token to ~/.env (which Stella also reads)
conda run -n stella-env deepxiv config
```

On first use the SDK can also auto-register a free anonymous token
(1,000 requests/day) into `~/.env`. For a higher quota (10,000 requests/day),
register at [data.rag.ac.cn/register](https://data.rag.ac.cn/register) and either
run `deepxiv config --token YOUR_TOKEN` or set `DEEPXIV_TOKEN=...` in this
project's `.env`.

### NASA ADS token

ADS metadata/bibcode retrieval uses the NASA ADS Developer API
([docs: github.com/adsabs/adsabs-dev-api](https://github.com/adsabs/adsabs-dev-api)).
To get a token:

1. Sign in at [ui.adsabs.harvard.edu](https://ui.adsabs.harvard.edu).
2. Generate a key on the
   [API token settings page](https://ui.adsabs.harvard.edu/user/settings/token).
3. Put it in `.env` as `ADS_API_TOKEN=...` (the CLIs also accept `ADS_TOKEN`).

The following variables are optional and are only needed for LLM review of `no-clear-title-evidence` papers, `catalog_assessment`, and ADS metadata/bibcode archival or repair:

```env
LLM_API_KEY=
LLM_BASE_URL=https://tokendance.space/gateway/v1
LLM_MODEL=deepseek-v4-pro
LLM_THINKING=
LLM_REASONING_EFFORT=
```

The project default gateway is [Token Dance](https://tokendance.space)
(OpenAI-compatible; one key serves every model in the benchmark roster).
Create a key at <https://tokendance.space/keys>, then verify with:

```bash
conda run -n stella-env python scripts/check_llm_endpoint.py
```

Any other OpenAI-compatible endpoint also works by changing
`LLM_BASE_URL`/`LLM_MODEL`.

The main Python CLIs share one `.env` loader and read environment variables in this order:

- `~/.env`
- Project-root `.env`
- Current working directory `.env`

Do not put secrets in `environment.yml`. `environment.yml` should contain only reproducible dependencies.
