"""Strict v2 contracts for contribution benchmark scoring outputs."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Rate = Annotated[float, Field(ge=0.0, le=1.0)]
Count = Annotated[int, Field(ge=0)]


def _rate_matches(actual: float | None, numerator: int, denominator: int) -> bool:
    expected = numerator / denominator if denominator else None
    if actual is None or expected is None:
        return actual is expected
    return abs(actual - expected) <= 1e-12


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ScorecardSchema(StrictModel):
    name: Literal["benchmark.hvs_contribution_scorecard"]
    version: Literal[2]


class ScoringDetailsSchema(StrictModel):
    name: Literal["benchmark.hvs_contribution_scoring_details"]
    version: Literal[2]


class ArtifactSchemaRef(StrictModel):
    name: str = Field(min_length=1)
    version: int = Field(ge=1)


class PaperDeliveryCounts(StrictModel):
    complete: Count
    partial: Count
    failed: Count
    network_failed: Count
    interrupted: Count
    pending: Count
    running: Count
    skipped: Count


class DocumentDelivery(StrictModel):
    documents_expected: Count
    documents_delivered: Count
    documents_missing: Count
    schema_valid: Count
    schema_invalid: Count
    delivery_rate: Rate | None
    schema_valid_rate: Rate | None

    @model_validator(mode="after")
    def counts_are_exhaustive(self) -> "DocumentDelivery":
        if self.documents_expected != self.documents_delivered + self.documents_missing:
            raise ValueError("expected documents must equal delivered plus missing")
        if self.documents_delivered != self.schema_valid + self.schema_invalid:
            raise ValueError("delivered documents must equal schema-valid plus schema-invalid")
        if not _rate_matches(
            self.delivery_rate, self.documents_delivered, self.documents_expected
        ):
            raise ValueError("delivery_rate does not match document counts")
        if not _rate_matches(
            self.schema_valid_rate, self.schema_valid, self.documents_delivered
        ):
            raise ValueError("schema_valid_rate does not match delivered documents")
        return self


class ObjectQuantityDelivery(StrictModel):
    complete: Count
    failed: Count
    complete_rate: Rate | None

    @model_validator(mode="after")
    def rate_matches_counts(self) -> "ObjectQuantityDelivery":
        if not _rate_matches(
            self.complete_rate, self.complete, self.complete + self.failed
        ):
            raise ValueError("complete_rate does not match quantity delivery counts")
        return self


class L0Score(StrictModel):
    paper_delivery: PaperDeliveryCounts
    documents: DocumentDelivery
    object_quantity_delivery: ObjectQuantityDelivery


class L1Score(StrictModel):
    matched: Count
    ai_only: Count
    gold_only: Count
    precision: Rate | None
    recall: Rate | None
    f1: Rate | None

    @model_validator(mode="after")
    def rates_match_counts(self) -> "L1Score":
        if not _rate_matches(self.precision, self.matched, self.matched + self.ai_only):
            raise ValueError("L1 precision does not match counts")
        if not _rate_matches(self.recall, self.matched, self.matched + self.gold_only):
            raise ValueError("L1 recall does not match counts")
        expected_f1 = (
            2 * self.precision * self.recall / (self.precision + self.recall)
            if self.precision is not None
            and self.recall is not None
            and self.precision + self.recall > 0
            else None
        )
        if self.f1 is None or expected_f1 is None:
            if self.f1 is not expected_f1:
                raise ValueError("L1 F1 does not match precision and recall")
        elif abs(self.f1 - expected_f1) > 1e-12:
            raise ValueError("L1 F1 does not match precision and recall")
        return self


class L2Score(StrictModel):
    gold_values: Count
    ai_values: Count
    paired: Count
    gold_only: Count
    ai_only: Count
    strict_agreement: Count
    lenient_agreement: Count
    mismatch: Count
    value_recall: Rate | None
    value_precision: Rate | None
    strict_agreement_rate: Rate | None
    strict_end_to_end_rate: Rate | None

    @model_validator(mode="after")
    def pair_counts_are_exhaustive(self) -> "L2Score":
        if self.paired != self.strict_agreement + self.lenient_agreement + self.mismatch:
            raise ValueError("paired values must equal strict, lenient, and mismatch counts")
        if self.gold_values != self.paired + self.gold_only:
            raise ValueError("Gold values must equal paired plus gold-only counts")
        if self.ai_values != self.paired + self.ai_only:
            raise ValueError("AI values must equal paired plus ai-only counts")
        for label, actual, numerator, denominator in (
            ("value_recall", self.value_recall, self.paired, self.gold_values),
            ("value_precision", self.value_precision, self.paired, self.ai_values),
            (
                "strict_agreement_rate",
                self.strict_agreement_rate,
                self.strict_agreement,
                self.paired,
            ),
            (
                "strict_end_to_end_rate",
                self.strict_end_to_end_rate,
                self.strict_agreement,
                self.gold_values,
            ),
        ):
            if not _rate_matches(actual, numerator, denominator):
                raise ValueError(f"L2 {label} does not match counts")
        return self


class ContributionTypeDiagnostic(StrictModel):
    matched: Count
    correct: Count
    accuracy: Rate | None
    confusion: dict[str, Count]

    @model_validator(mode="after")
    def counts_and_rate_match(self) -> "ContributionTypeDiagnostic":
        if self.correct > self.matched:
            raise ValueError("contribution-type counts are inconsistent")
        if not _rate_matches(self.accuracy, self.correct, self.matched):
            raise ValueError("contribution-type accuracy does not match counts")
        return self


class PaperBoundnessDiagnostic(StrictModel):
    gold_statuses: Count
    assigned: Count
    correct: Count
    coverage: Rate | None
    accuracy: Rate | None
    confusion: dict[str, Count]

    @model_validator(mode="after")
    def counts_and_rates_match(self) -> "PaperBoundnessDiagnostic":
        if self.assigned > self.gold_statuses or self.correct > self.assigned:
            raise ValueError("paper-boundness counts are inconsistent")
        if not _rate_matches(self.coverage, self.assigned, self.gold_statuses):
            raise ValueError("paper-boundness coverage does not match counts")
        if not _rate_matches(self.accuracy, self.correct, self.assigned):
            raise ValueError("paper-boundness accuracy does not match counts")
        return self


class AgreementDiagnostic(StrictModel):
    compared: Count
    agreement: Count
    agreement_rate: Rate | None

    @model_validator(mode="after")
    def counts_and_rate_match(self) -> "AgreementDiagnostic":
        if self.agreement > self.compared:
            raise ValueError("diagnostic agreement exceeds compared pairs")
        if not _rate_matches(self.agreement_rate, self.agreement, self.compared):
            raise ValueError("diagnostic agreement rate does not match counts")
        return self


class SummaryEvidenceDiagnostic(StrictModel):
    matched: Count
    required_summary_present: Count
    required_evidence_present: Count
    summary_presence_rate: Rate | None
    evidence_presence_rate: Rate | None

    @model_validator(mode="after")
    def counts_and_rates_match(self) -> "SummaryEvidenceDiagnostic":
        if (
            self.required_summary_present > self.matched
            or self.required_evidence_present > self.matched
        ):
            raise ValueError("summary/evidence presence exceeds matched objects")
        if not _rate_matches(
            self.summary_presence_rate,
            self.required_summary_present,
            self.matched,
        ):
            raise ValueError("summary presence rate does not match counts")
        if not _rate_matches(
            self.evidence_presence_rate,
            self.required_evidence_present,
            self.matched,
        ):
            raise ValueError("evidence presence rate does not match counts")
        return self


class ScorecardDiagnostics(StrictModel):
    contribution_type: ContributionTypeDiagnostic
    paper_boundness: PaperBoundnessDiagnostic
    paper_preferred: AgreementDiagnostic
    source_kind: AgreementDiagnostic
    summary_evidence: SummaryEvidenceDiagnostic


class ScoreInputHashes(StrictModel):
    gold_selection: Sha256
    method_config: Sha256
    gold_annotations: list[Sha256] = Field(min_length=1)
    ai_documents: list[Sha256]


class ScoringTarget(StrictModel):
    gold_schema: ArtifactSchemaRef
    ai_schema: ArtifactSchemaRef

    @model_validator(mode="after")
    def is_contribution_target(self) -> "ScoringTarget":
        gold = self.gold_schema.model_dump()
        ai = self.ai_schema.model_dump()
        if gold.get("name") != "benchmark.hvs_contribution_annotation":
            raise ValueError("unexpected contribution Gold target")
        if ai.get("name") != "literature_hvs_contributions":
            raise ValueError("unexpected contribution extraction target")
        if gold.get("version") not in (1, 2) or ai.get("version") not in (1, 2):
            raise ValueError("unsupported contribution target version")
        if gold.get("version") != ai.get("version"):
            raise ValueError("contribution target schema versions must match")
        return self


class ScoreSpecBinding(StrictModel):
    version: Literal["3.0.0"]
    sha256: Sha256


class ScorerBinding(StrictModel):
    implementation: Literal["stella.benchmark.hvs_contribution_scoring"]
    sha256: Sha256


class ScoringContract(StrictModel):
    target: ScoringTarget
    score_spec: ScoreSpecBinding
    scorer: ScorerBinding


class HvsContributionScorecardV2(StrictModel):
    schema_: ScorecardSchema = Field(alias="schema")
    run_id: str = Field(min_length=1)
    l0: L0Score
    l1: L1Score
    l2: L2Score
    diagnostics: ScorecardDiagnostics
    papers_scored: Count
    input_hashes: ScoreInputHashes
    scoring_contract: ScoringContract
    contract_note: Literal["three quality layers and diagnostics; no fused score"]

    @model_validator(mode="after")
    def inputs_match_delivery(self) -> "HvsContributionScorecardV2":
        documents = self.l0.documents
        if self.papers_scored != documents.documents_expected:
            raise ValueError("papers_scored must equal documents_expected")
        if len(self.input_hashes.gold_annotations) != self.papers_scored:
            raise ValueError("every scored Gold annotation must have an input hash")
        if len(self.input_hashes.ai_documents) != documents.documents_delivered:
            raise ValueError("every delivered AI document must have an input hash")
        if sum(self.l0.paper_delivery.model_dump().values()) != self.papers_scored:
            raise ValueError("paper delivery states must cover every scored paper")
        return self


class HvsContributionScoringDetailsV2(StrictModel):
    schema_: ScoringDetailsSchema = Field(alias="schema")
    input_hashes: ScoreInputHashes
    scoring_contract: ScoringContract
    papers: list[dict[str, Any]]


def validate_scorecard_v2(payload: Any) -> dict[str, Any]:
    """Validate and normalize the only writable contribution scorecard shape."""

    return HvsContributionScorecardV2.model_validate(payload).model_dump(
        mode="json", by_alias=True
    )
