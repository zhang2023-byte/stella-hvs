# Setup

Run commands inside the project conda environment:

```bash
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
