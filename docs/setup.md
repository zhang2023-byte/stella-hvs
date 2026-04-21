# Setup

Create the project conda environment from the checked-in spec:

```bash
conda env create -f environment.yml
conda activate stella-env
```

If the environment already exists and the spec changed, update it with:

```bash
conda env update -f environment.yml --prune
conda activate stella-env
```

Project secrets live in `.env`, which is ignored by Git:

```bash
cp scripts/env.example .env
```

Required:

```env
DEEPXIV_TOKEN=
```

Optional, only needed for LLM review:

```env
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

The script loads environment variables from `~/.env`, `stella-workspace/.env`, and the current working directory `.env`.

Keep secrets in `.env`, not in `environment.yml`. The environment file should
only contain reproducible runtime dependencies.
