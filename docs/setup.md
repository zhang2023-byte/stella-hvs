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

The environment includes dependencies for local literature archiving, HTML parsing, network requests, Pydantic schema validation, external catalog table parsing, object-catalog enrichment, and HVS dynamical reassessment. FITS, VOTable, and CDS/MRT ASCII are read through `astropy`; SIMBAD/Gaia DR3 enrichment and dynamics queries use `astroquery` and `pyvo`; Gaia DR3 parallax zero-point correction uses `gaiadr3-zeropoint`; Bayesian kinematics and escape comparisons use `emcee`, `scipy`, and `galpy`.

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
cp env.example .env
```

If you use `--source deepxiv`, or run DeepXiv-enhanced `catalog_assessment`, set:

```env
DEEPXIV_TOKEN=
ADS_API_TOKEN=
```

The following variables are optional and are only needed for LLM review of `no-clear-title-evidence` papers, `catalog_assessment`, and ADS metadata/bibcode archival or repair:

```env
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_THINKING=
LLM_REASONING_EFFORT=
```

The main Python CLIs share one `.env` loader and read environment variables in this order:

- `~/.env`
- Project-root `.env`
- Current working directory `.env`

Do not put secrets in `environment.yml`. `environment.yml` should contain only reproducible dependencies.
