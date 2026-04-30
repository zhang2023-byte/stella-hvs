"""Default search settings for the high-velocity star literature pipeline."""

DEFAULT_QUERIES = [
    "hypervelocity stars",
    "high-velocity stars",
    "high radial velocity stars",
    "runaway stars",
    "unbound stars",
    "escaping stars",
]

DEFAULT_CATEGORIES = [
    "astro-ph.GA",
    "astro-ph.SR",
    "astro-ph.IM",
]

DEFAULT_SEARCH_MODE = "hybrid"
DEFAULT_SOURCE = "arxiv"
DEFAULT_MAX_RESULTS = 20
DEFAULT_SEARCH_SLEEP_SECONDS = 0.2
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_LLM_BATCH_SIZE = 25
DEFAULT_DEEPXIV_LLM_REVIEW_MAX_CANDIDATES = 20
