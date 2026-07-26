"""Central schema and release registry for persisted Stella artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

STELLA_RELEASE = "0.6.0"
ACTIVE_BENCHMARK_CAMPAIGN = "hvs-extraction-v4"

Lifecycle = Literal["current", "read_only", "transient"]
CampaignLifecycle = Literal["active", "read_only"]


@dataclass(frozen=True)
class BenchmarkCampaignEntry:
    campaign_id: str
    lifecycle: CampaignLifecycle


BENCHMARK_CAMPAIGNS = {
    entry.campaign_id: entry
    for entry in (
        BenchmarkCampaignEntry("hvs-extraction-v1", "read_only"),
        BenchmarkCampaignEntry("hvs-extraction-v2", "read_only"),
        BenchmarkCampaignEntry("hvs-extraction-v3", "read_only"),
        BenchmarkCampaignEntry("hvs-extraction-scratch-legacy", "read_only"),
        BenchmarkCampaignEntry("hvs-extraction-v4", "active"),
    )
}
if [
    entry.campaign_id
    for entry in BENCHMARK_CAMPAIGNS.values()
    if entry.lifecycle == "active"
] != [ACTIVE_BENCHMARK_CAMPAIGN]:
    raise RuntimeError("benchmark campaign registry must have exactly one matching active campaign")


@dataclass(frozen=True)
class SchemaEntry:
    name: str
    current_version: int
    readable_versions: tuple[int, ...]
    lifecycle: Lifecycle = "current"
    legacy_aliases: tuple[str, ...] = ()
    model_key: str | None = None

    def __post_init__(self) -> None:
        if not self.name or self.current_version < 1:
            raise ValueError("schema entries require a name and a positive current version")
        if self.current_version not in self.readable_versions:
            raise ValueError(f"{self.name}: current version must be readable")
        if any(version < 1 for version in self.readable_versions):
            raise ValueError(f"{self.name}: readable versions must be positive")


def _entry(
    name: str,
    current: int,
    *,
    readable: tuple[int, ...] | None = None,
    lifecycle: Lifecycle = "current",
    aliases: tuple[str, ...] = (),
    model_key: str | None = None,
) -> SchemaEntry:
    return SchemaEntry(
        name=name,
        current_version=current,
        readable_versions=readable or (current,),
        lifecycle=lifecycle,
        legacy_aliases=aliases,
        model_key=model_key,
    )


SCHEMAS: tuple[SchemaEntry, ...] = (
    _entry("article_data_assets.review", 1, aliases=("stella.article_data_assets.review.v0.1",), model_key="catalog_review"),
    _entry("article_data_assets.extraction", 1, aliases=("stella.article_data_assets.extraction.v0.1",), model_key="catalog_extraction"),
    _entry("article_data_assets.inventory", 1, aliases=("stella.article_data_assets.inventory.v0.1",)),
    _entry("article_data_assets.index", 1, aliases=("stella.article_data_assets.index.v0.1",)),
    _entry("arxiv.metadata_report", 1, aliases=("stella.arxiv.metadata.report.v0.1",)),
    _entry("literature.month", 1, aliases=("stella.literature.month.v0.1",)),
    _entry("literature.index", 1, aliases=("stella.literature.index.v0.1",)),
    _entry("literature.title_triage", 1, aliases=("stella.literature.title_triage.v0.1",)),
    _entry("literature.assets_audit", 1, aliases=("stella.literature.assets_audit.v0.1",)),
    _entry("literature_hvs_candidates", 2, readable=(1, 2), aliases=("stella.literature_hvs_candidates.v0.1", "stella.literature_hvs_candidates.v0.2"), model_key="hvs_candidates"),
    _entry("literature_hvs_candidates.index", 1, aliases=("stella.literature_hvs_candidates.index.v0.1",)),
    _entry("hvs_candidate_catalog.object", 1, aliases=("stella.hvs_candidate_catalog.object.v0.1",)),
    _entry("hvs_candidate_catalog.index", 1, aliases=("stella.hvs_candidate_catalog.index.v0.1",)),
    _entry("hvs_catalog_site.snapshot", 1, aliases=("stella.hvs_catalog_site.snapshot.v0.1",)),
    _entry("benchmark.sampling_manifest", 2, aliases=("stella.benchmark_sampling_manifest.v0.2",)),
    _entry("benchmark.campaign", 1, aliases=("stella.benchmark_campaign.v0.1",)),
    _entry("benchmark.legacy_campaign", 1, lifecycle="read_only"),
    _entry("benchmark.gold_annotation", 1, aliases=("stella.benchmark_gold_annotation.v0.1",), model_key="gold_annotation"),
    _entry("benchmark.gold_form_draft", 1, lifecycle="transient", aliases=("stella.benchmark_gold_form_draft.v0.1",)),
    _entry("benchmark.gold_manifest", 1, aliases=("stella.benchmark_gold_manifest.v0.1",)),
    _entry("benchmark.context_manifest", 1, aliases=("stella.benchmark_context_pack.v0.1",)),
    _entry("benchmark.agent_bundle", 1, lifecycle="transient", aliases=("stella.benchmark_agent_bundle.v0.1",)),
    _entry("benchmark.roster_bundle", 3, readable=(1, 2, 3), lifecycle="transient"),
    _entry("benchmark.archive_inventory", 1, lifecycle="read_only"),
    _entry("benchmark.leakage_audit", 1, aliases=("stella.benchmark_leakage_audit.v0.1",)),
    _entry("benchmark.run_config", 3, readable=(2, 3), aliases=("stella.benchmark_run_config.v0.2", "stella.benchmark_run_config.v0.3")),
    _entry("benchmark.run_manifest", 4, readable=(1, 2, 3, 4), aliases=("stella.benchmark_run_manifest.v0.1", "stella.benchmark_run_manifest.v0.2", "stella.benchmark_run_manifest.v0.3", "stella.benchmark_run_manifest.v0.4")),
    _entry("benchmark.run_event", 2, readable=(1, 2), lifecycle="transient"),
    _entry("benchmark.run_trace_blob", 1, lifecycle="transient"),
    _entry("benchmark.dev_console_state", 1, lifecycle="transient"),
    _entry("benchmark.dev_experiment_group", 2, readable=(1, 2), lifecycle="transient"),
    _entry("benchmark.dev_group_event", 1, lifecycle="transient"),
    _entry("benchmark.dev_evaluation", 1, lifecycle="transient"),
    _entry("benchmark.hvs_extraction_scratch.run_config", 2, readable=(1, 2), lifecycle="transient"),
    _entry("benchmark.hvs_extraction_scratch.prepared_input", 1, lifecycle="transient"),
    _entry("benchmark.hvs_extraction_scratch.roster_proposal", 2, readable=(1, 2), lifecycle="transient"),
    _entry("benchmark.hvs_extraction_scratch.roster_final", 2, readable=(1, 2), lifecycle="transient"),
    _entry("benchmark.hvs_extraction_scratch.candidate_fields", 2, readable=(1, 2), lifecycle="transient"),
    _entry("benchmark.hvs_extraction_scratch.paper_result", 2, readable=(1, 2), lifecycle="transient"),
    _entry("benchmark.hvs_extraction_scratch.run_summary", 2, readable=(1, 2), lifecycle="transient"),
    _entry("benchmark.hvs_extraction_scratch.evaluation", 1, lifecycle="transient"),
    _entry("benchmark.test_release", 1, aliases=("stella.benchmark_test_release.v0.1",)),
    _entry("benchmark.scorecard", 4, readable=(2, 3, 4), aliases=("stella.benchmark_scorecard.v0.2", "stella.benchmark_scorecard.v0.3", "stella.benchmark_scorecard.v0.4")),
    _entry("benchmark.scoring_details", 3, readable=(2, 3), aliases=("stella.benchmark_scoring_details.v0.2", "stella.benchmark_scoring_details.v0.3")),
    _entry("benchmark.extraction_surface_ablation", 1),
)

REGISTRY = {entry.name: entry for entry in SCHEMAS}
if len(REGISTRY) != len(SCHEMAS):
    raise RuntimeError("duplicate schema names in registry")

LEGACY_ALIASES: dict[str, tuple[str, int]] = {}
for _schema in SCHEMAS:
    for _position, _alias in enumerate(_schema.legacy_aliases):
        if _alias in LEGACY_ALIASES:
            raise RuntimeError(f"duplicate legacy schema alias: {_alias}")
        versions = _schema.readable_versions
        version = versions[_position] if len(versions) == len(_schema.legacy_aliases) else _schema.current_version
        LEGACY_ALIASES[_alias] = (_schema.name, version)


def schema_ref(name: str, version: int | None = None) -> dict[str, Any]:
    entry = REGISTRY.get(name)
    if entry is None:
        raise ValueError(f"unknown schema artifact: {name}")
    selected = entry.current_version if version is None else version
    if selected not in entry.readable_versions:
        raise ValueError(f"unsupported {name} schema version: {selected}")
    return {"name": name, "version": selected}


def require_campaign_writable(campaign_id: str) -> str:
    """Return the canonical id only for the single active campaign."""

    entry = BENCHMARK_CAMPAIGNS.get(str(campaign_id))
    if entry is None or entry.lifecycle != "active":
        raise ValueError(f"benchmark campaign {campaign_id!r} is not writable")
    return entry.campaign_id


def require_schema(
    payload: Any,
    expected_name: str,
    *,
    require_current: bool = False,
) -> tuple[str, int]:
    if expected_name not in REGISTRY:
        raise ValueError(f"unknown schema artifact: {expected_name}")
    if not isinstance(payload, dict):
        raise ValueError("artifact must be a JSON object")
    ref = payload.get("schema")
    if not isinstance(ref, dict):
        raise ValueError("artifact must contain structured schema metadata")
    name = ref.get("name")
    version = ref.get("version")
    if name != expected_name:
        raise ValueError(f"expected schema {expected_name!r}, got {name!r}")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("schema.version must be an integer")
    entry = REGISTRY[expected_name]
    allowed = (entry.current_version,) if require_current else entry.readable_versions
    if version not in allowed:
        qualifier = "current" if require_current else "readable"
        raise ValueError(f"schema {expected_name} version {version} is not {qualifier}")
    return name, version


def model_for(name: str, version: int) -> type[Any]:
    require_schema({"schema": {"name": name, "version": version}}, name)
    if name == "article_data_assets.review":
        from stella.lit.schema_models import CatalogReviewRecord
        return CatalogReviewRecord
    if name == "article_data_assets.extraction":
        from stella.lit.schema_models import CatalogExtractionRecord
        return CatalogExtractionRecord
    if name == "literature_hvs_candidates":
        from stella.lit.schema_models import LiteratureHvsCandidatesRecord, LegacyLiteratureHvsCandidatesRecord
        return LegacyLiteratureHvsCandidatesRecord if version == 1 else LiteratureHvsCandidatesRecord
    if name == "benchmark.gold_annotation":
        from stella.benchmark.gold import GoldAnnotation
        return GoldAnnotation
    raise ValueError(f"schema {name!r} has no registered model")


def list_schema_status() -> list[dict[str, Any]]:
    return [
        {
            "name": entry.name,
            "current_version": entry.current_version,
            "readable_versions": list(entry.readable_versions),
            "lifecycle": entry.lifecycle,
        }
        for entry in SCHEMAS
    ]
