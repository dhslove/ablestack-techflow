"""HTTP request and response contracts for TechFlow AI Gateway v1."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


SafeId = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
RepositoryName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]


class SourceKind(StrEnum):
    DOCUMENTATION = "DOCUMENTATION"
    SOURCE_CODE = "SOURCE_CODE"
    TEST_CODE = "TEST_CODE"
    BUILD_SCHEMA = "BUILD_SCHEMA"


class SourceState(StrEnum):
    REGISTERED = "REGISTERED"
    QUARANTINED = "QUARANTINED"
    APPROVED = "APPROVED"
    INDEXING = "INDEXING"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    REJECTED = "REJECTED"


class JobState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class AnswerState(StrEnum):
    ANSWERED = "ANSWERED"
    ABSTAINED = "ABSTAINED"
    FAILED = "FAILED"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ApiMeta(StrictModel):
    correlation_id: str = Field(alias="correlationId")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="generatedAt")
    api_version: str = Field(default="v1", alias="apiVersion")


class Envelope(StrictModel):
    data: Any
    meta: ApiMeta


class SourceCreateRequest(StrictModel):
    source_profile_id: SafeId = Field(alias="sourceProfileId")
    repository: RepositoryName
    branch: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    commit: CommitSha
    source_kind: SourceKind = Field(alias="sourceKind")
    classification: Literal["D0"] = "D0"
    license_spdx: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = Field(default=None, alias="licenseSpdx")


class SourceApprovalRequest(StrictModel):
    approved_by: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{3,128}$")] = Field(alias="approvedBy")
    expected_commit: CommitSha | None = Field(default=None, alias="expectedCommit")
    decision_note: Annotated[str, StringConstraints(max_length=500)] | None = Field(default=None, alias="decisionNote")
    accept_quarantine_exclusions: bool = Field(default=False, alias="acceptQuarantineExclusions")

    @model_validator(mode="after")
    def exclusion_acceptance_requires_note(self) -> "SourceApprovalRequest":
        if self.accept_quarantine_exclusions and (not self.decision_note or len(self.decision_note.strip()) < 10):
            raise ValueError("acceptQuarantineExclusions requires a decisionNote of at least 10 characters")
        return self


class SourceDiscoveryRequest(StrictModel):
    detected_by: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{3,128}$")] = Field(alias="detectedBy")


class SourceScanRequest(StrictModel):
    scanned_by: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{3,128}$")] = Field(alias="scannedBy")


class JobCompletionRequest(StrictModel):
    succeeded: bool
    indexed_file_count: int = Field(ge=0, alias="indexedFileCount")
    error_code: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")] | None = Field(default=None, alias="errorCode")

    @model_validator(mode="after")
    def completion_contract(self) -> "JobCompletionRequest":
        if self.succeeded and self.error_code is not None:
            raise ValueError("successful completion cannot include errorCode")
        if not self.succeeded and self.error_code is None:
            raise ValueError("failed completion requires errorCode")
        return self


class JobRunRequest(StrictModel):
    requested_by: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{3,128}$")] = Field(alias="requestedBy")
    provider_profile_id: Literal["OPENAI_EMBEDDING_V1"] = Field(
        default="OPENAI_EMBEDDING_V1", alias="providerProfileId"
    )


class CompatibilityMember(StrictModel):
    source_version_id: UUID = Field(alias="sourceVersionId")
    required: bool = True


class CompatibilitySetCreateRequest(StrictModel):
    name: Annotated[str, StringConstraints(min_length=3, max_length=128)]
    product: Literal["ABLESTACK"] = "ABLESTACK"
    product_version: Annotated[str, StringConstraints(min_length=1, max_length=64)] = Field(alias="productVersion")
    members: list[CompatibilityMember] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def unique_members(self) -> "CompatibilitySetCreateRequest":
        ids = [member.source_version_id for member in self.members]
        if len(ids) != len(set(ids)):
            raise ValueError("members must be unique")
        return self


class IngestionCreateRequest(StrictModel):
    requested_by: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{3,128}$")] = Field(alias="requestedBy")


class QueryRequest(StrictModel):
    query_id: UUID = Field(alias="queryId")
    question: Annotated[str, StringConstraints(min_length=3, max_length=4000)]
    source_profile_ids: list[SafeId] | None = Field(default=None, min_length=1, max_length=9, alias="sourceProfileIds")
    compatibility_set_id: UUID | None = Field(default=None, alias="compatibilitySetId")
    locale: Literal["ko-KR", "en-US"] = "ko-KR"
    classification: Literal["D0"] = "D0"

    @model_validator(mode="after")
    def exactly_one_scope(self) -> "QueryRequest":
        if bool(self.source_profile_ids) == bool(self.compatibility_set_id):
            raise ValueError("exactly one query scope is required")
        return self


class GroundedQueryRequest(QueryRequest):
    actor_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{3,128}$")] = Field(alias="actorId")


class ComprehensiveQueryRequest(StrictModel):
    query_id: UUID = Field(alias="queryId")
    question: Annotated[str, StringConstraints(min_length=3, max_length=4000)]
    actor_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{3,128}$")] = Field(alias="actorId")
    product_version: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = Field(
        default=None, alias="productVersion"
    )
    compatibility_set_id: UUID | None = Field(default=None, alias="compatibilitySetId")
    source_profile_ids: list[SafeId] | None = Field(default=None, min_length=1, max_length=9, alias="sourceProfileIds")
    artifact_ids: list[UUID] = Field(default_factory=list, max_length=5, alias="artifactIds")
    environment: Annotated[str, StringConstraints(max_length=1000)] | None = None
    locale: Literal["ko-KR", "en-US"] = "ko-KR"
    classification: Literal["D0"] = "D0"

    @model_validator(mode="after")
    def explicit_scopes_are_exclusive(self) -> "ComprehensiveQueryRequest":
        if self.compatibility_set_id and self.source_profile_ids:
            raise ValueError("compatibilitySetId and sourceProfileIds are mutually exclusive")
        if len(self.artifact_ids) != len(set(self.artifact_ids)):
            raise ValueError("artifactIds must be unique")
        return self


class CommunityCaseCreateRequest(StrictModel):
    discussion_id: Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,18}$")] = Field(alias="discussionId")
    discussion_url: Annotated[str, StringConstraints(pattern=r"^https://community\.ablecloud\.io/d/[A-Za-z0-9._~/-]+$")] = Field(alias="discussionUrl")
    title: Annotated[str, StringConstraints(min_length=3, max_length=200)]
    question: Annotated[str, StringConstraints(min_length=3, max_length=4000)]
    author_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{1,128}$")] = Field(alias="authorId")
    tag_slugs: list[Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,64}$")]] = Field(default_factory=list, max_length=20, alias="tagSlugs")
    artifact_ids: list[UUID] = Field(default_factory=list, max_length=5, alias="artifactIds")
    product_version: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = Field(default=None, alias="productVersion")
    post_id: Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,18}$")] | None = Field(default=None, alias="postId")
    post_number: int | None = Field(default=None, ge=1, alias="postNumber")
    post_author_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{1,128}$")] | None = Field(default=None, alias="postAuthorId")
    turn_role: Literal["REQUESTER", "STAFF", "ASSISTANT"] = Field(default="REQUESTER", alias="turnRole")
    response_requested: bool = Field(default=True, alias="responseRequested")
    resolution_only: bool = Field(default=False, alias="resolutionOnly")
    best_answer_post_id: Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,18}$")] | None = Field(default=None, alias="bestAnswerPostId")
    best_answer_user_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{1,128}$")] | None = Field(default=None, alias="bestAnswerUserId")
    best_answer_set_at: datetime | None = Field(default=None, alias="bestAnswerSetAt")

    @model_validator(mode="after")
    def unique_artifacts_and_tags(self) -> "CommunityCaseCreateRequest":
        if len(self.artifact_ids) != len(set(self.artifact_ids)) or len(self.tag_slugs) != len(set(self.tag_slugs)):
            raise ValueError("artifactIds and tagSlugs must be unique")
        return self

    @field_validator("post_id", "post_author_id", "best_answer_post_id", "best_answer_user_id", mode="before")
    @classmethod
    def normalize_optional_event_fields(cls, value: Any) -> Any:
        return None if value == "" else value

    @field_validator("post_number", "best_answer_set_at", mode="before")
    @classmethod
    def normalize_optional_typed_event_fields(cls, value: Any) -> Any:
        return None if value == "" else value


class CommunityDecisionRequest(StrictModel):
    decision: Literal["APPROVE", "REJECT"]
    reviewer: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{3,128}$")]
    expected_draft_version: int = Field(ge=1, alias="expectedDraftVersion")
    edited_answer: Annotated[str, StringConstraints(min_length=3, max_length=12000)] | None = Field(default=None, alias="editedAnswer")
    note: Annotated[str, StringConstraints(max_length=1000)] | None = None

    @field_validator("edited_answer", mode="before")
    @classmethod
    def normalize_visual_flow_empty_edit(cls, value: Any) -> Any:
        """Activepieces renders an unset optional template value as an empty string."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


class CommunityPublishRequest(StrictModel):
    requested_by: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{3,128}$")] = Field(alias="requestedBy")


class EvaluationRunCreateRequest(StrictModel):
    name: Annotated[str, StringConstraints(min_length=3, max_length=128)]
    source_profile_ids: list[SafeId] | None = Field(default=None, min_length=1, max_length=9, alias="sourceProfileIds")
    compatibility_set_id: UUID | None = Field(default=None, alias="compatibilitySetId")
    provider_profile_id: Literal["OPENAI_RAG_DEFAULT_V1", "OPENAI_RAG_ESCALATION_V1"] = Field(alias="providerProfileId")
    requested_by: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{3,128}$")] = Field(alias="requestedBy")

    @model_validator(mode="after")
    def exactly_one_scope(self) -> "EvaluationRunCreateRequest":
        if bool(self.source_profile_ids) == bool(self.compatibility_set_id):
            raise ValueError("exactly one evaluation scope is required")
        return self


class EvaluationExecuteRequest(StrictModel):
    case_set_id: Literal["ABLESTACK_GOLDEN_V1"] = Field(default="ABLESTACK_GOLDEN_V1", alias="caseSetId")
    requested_by: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@-]{3,128}$")] = Field(alias="requestedBy")
