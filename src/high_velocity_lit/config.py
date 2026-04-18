"""Default search settings for the high-velocity star literature pipeline."""

DEFAULT_QUERIES = [
    "hypervelocity stars",
    "high-velocity stars",
    "runaway stars",
    "unbound stars",
    "escaping stars",
]

DEFAULT_CATEGORIES = [
    "astro-ph.GA",
]

DEFAULT_SEARCH_MODE = "hybrid"
DEFAULT_SOURCE = "deepxiv"
DEFAULT_MAX_RESULTS = 20
DEFAULT_SEARCH_SLEEP_SECONDS = 0.2
DEFAULT_BRIEF_SLEEP_SECONDS = 0.2
DEFAULT_CLASSIFIER = "rules"
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_LLM_BATCH_SIZE = 25
