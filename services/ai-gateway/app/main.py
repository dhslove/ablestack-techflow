"""TechFlow AI Gateway Issue #41 FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import json
import logging
import re
import time
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .config import ConfigurationError, Settings
from .models import (
    ApiMeta,
    CompatibilitySetCreateRequest,
    ComprehensiveQueryRequest,
    CommunityCaseCreateRequest,
    CommunityDecisionRequest,
    CommunityPublishRequest,
    Envelope,
    EvaluationExecuteRequest,
    EvaluationRunCreateRequest,
    GroundedQueryRequest,
    IngestionCreateRequest,
    JobCompletionRequest,
    JobRunRequest,
    QueryRequest,
    SourceApprovalRequest,
    SourceCreateRequest,
    SourceDiscoveryRequest,
    SourceScanRequest,
)
from .evaluation import judge_case, load_golden_set
from .postgres_store import PostgresStore
from .embedding import EmbeddingsAdapter, build_embedding_adapter
from .provider import ComprehensiveResponsesRequest, ResponsesRequest, profile_payloads
from .responses import (
    ResponsesAdapter,
    ResponsesProviderError,
    build_responses_adapter,
    citation_payload,
    context_from_results,
    decide_generation,
    load_safety_identifier_salt,
    stable_safety_identifier,
    validate_grounded_result,
)
from .source_fetcher import FetchError, GitSnapshotFetcher, SnapshotFetcher
from .source_pipeline import SourcePipeline
from .source_registry import get_profile
from .store import InvalidBoundaryError, InvalidStateError, MemoryStore, Store, StoreError
from .artifacts import ArtifactStore
from .comprehensive import plan_query
from .community import FlarumClient, format_draft, profiles_for_tags
from .versioned_assist import (
    CURATED_PLATFORM_PROFILE,
    SOURCE_ROLES,
    VERSIONED_SOURCE_PROFILES,
    coverage_payload,
    expand_retrieval_question,
    evidence_ledger,
    format_public_answer,
    select_context_results,
    versioned_plan,
)
from .platform_references import curated_platform_results
from .chat_assist import (
    CASE_REFERENCE,
    CommunityFlowClient,
    SynologyBotClient,
    case_card,
    case_evidence_text,
    case_reference,
    case_text,
    help_text,
    parse_chat_event,
    parse_command,
)


CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{15,127}$")
logger = logging.getLogger("techflow.ai_gateway")


def _json_log(event: str, **fields: object) -> None:
    safe = {"event": event, **fields}
    print(json.dumps(safe, ensure_ascii=True, separators=(",", ":")), flush=True)


MANUAL_REVIEW_ERROR_CODES = {"CONFLICT", "INVALID_STATE", "SOURCE_HEAD_MOVED"}


def _error(correlation_id: str, status_code: int, code: str) -> JSONResponse:
    if code in MANUAL_REVIEW_ERROR_CODES:
        failure_class = "MANUAL_REVIEW"
    elif status_code >= 500:
        failure_class = "RETRYABLE"
    else:
        failure_class = "TERMINAL"
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "failureClass": failure_class},
            "meta": {"correlationId": correlation_id, "apiVersion": "v1"},
        },
    )


def _envelope(data: Any, correlation_id: str) -> Envelope:
    return Envelope(data=data, meta=ApiMeta(correlationId=correlation_id))


def _model_data(model: Any) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=False)


def _idempotency_key(idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> str:
    if not idempotency_key or not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        raise InvalidBoundaryError("valid Idempotency-Key is required")
    return idempotency_key


def _correlation_id(request: Request) -> str:
    return request.state.correlation_id


def _build_store(settings: Settings) -> Store:
    if settings.store_backend == "postgres":
        return PostgresStore(settings)
    return MemoryStore()


def create_app(
    settings: Settings | None = None,
    store: Store | None = None,
    source_fetcher: SnapshotFetcher | None = None,
    embeddings_adapter: EmbeddingsAdapter | None = None,
    responses_adapter: ResponsesAdapter | None = None,
    chat_bot_client: SynologyBotClient | None = None,
    community_flow_client: CommunityFlowClient | None = None,
    flarum_client_instance: FlarumClient | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings.from_env()
    runtime_settings.validate()
    logger.setLevel(getattr(logging, runtime_settings.log_level, logging.INFO))
    runtime_store = store or _build_store(runtime_settings)
    runtime_embeddings = embeddings_adapter or build_embedding_adapter(runtime_settings)
    runtime_responses = responses_adapter or build_responses_adapter(runtime_settings)
    safety_identifier_salt = load_safety_identifier_salt(runtime_settings)
    source_pipeline = SourcePipeline(source_fetcher or GitSnapshotFetcher())
    artifact_store = ArtifactStore(
        runtime_settings.artifact_root,
        retention_hours=runtime_settings.artifact_retention_hours,
        max_bytes=runtime_settings.artifact_max_bytes,
        max_extracted_bytes=runtime_settings.artifact_max_extracted_bytes,
        max_archive_entries=runtime_settings.artifact_max_archive_entries,
        max_compression_ratio=runtime_settings.artifact_max_compression_ratio,
        max_log_evidence_chars=runtime_settings.artifact_max_log_evidence_chars,
    )
    flarum_client = flarum_client_instance or FlarumClient(
        runtime_settings.flarum_base_url,
        runtime_settings.flarum_public_url,
        runtime_settings.flarum_api_key_file,
        runtime_settings.community_publish_enabled,
        runtime_settings.flarum_assistant_user_id_file,
        runtime_settings.community_review_post_enabled,
    )
    runtime_chat_bot = chat_bot_client or SynologyBotClient(
        runtime_settings.chat_base_url, runtime_settings.chat_bot_token_file, runtime_settings.chat_bot_enabled,
    )
    runtime_community_flows = community_flow_client or CommunityFlowClient(
        runtime_settings.community_approve_webhook_file,
        runtime_settings.community_reject_webhook_file,
        runtime_settings.chat_bot_enabled,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        runtime_store.close()

    application = FastAPI(
        title="TechFlow AI Gateway",
        version=__version__,
        description="TechFlow AI Gateway with grounded Responses generation and deterministic retrieval.",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.store = runtime_store
    application.state.settings = runtime_settings
    application.state.artifacts = artifact_store

    @application.middleware("http")
    async def boundary_middleware(request: Request, call_next):
        started = time.perf_counter()
        correlation_id = request.headers.get("X-Correlation-Id", "")
        if request.url.path == "/v1/chat/synology/events" and not correlation_id:
            correlation_id = f"chat-{uuid4().hex}"
        if request.url.path.startswith("/v1") and not CORRELATION_PATTERN.fullmatch(correlation_id):
            return _error("missing", 400, "INVALID_CORRELATION_ID")
        request.state.correlation_id = correlation_id or "healthcheck"
        try:
            response = await call_next(request)
        except Exception as exc:
            _json_log(
                "request_failed",
                correlationId=request.state.correlation_id,
                method=request.method,
                path=request.url.path,
                status=500,
                errorType=type(exc).__name__,
            )
            return _error(request.state.correlation_id, 500, "INTERNAL_ERROR")
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Correlation-Id"] = request.state.correlation_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        _json_log(
            "request_completed",
            correlationId=request.state.correlation_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            durationMs=duration_ms,
        )
        return response

    @application.exception_handler(StoreError)
    async def store_error_handler(request: Request, exc: StoreError):
        status_code = getattr(exc, "http_status", 500)
        code = getattr(exc, "code", "STORE_ERROR")
        return _error(getattr(request.state, "correlation_id", "missing"), status_code, code)

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        safe_fields = [".".join(str(item) for item in error["loc"] if item not in {"body"}) for error in exc.errors()]
        response = _error(getattr(request.state, "correlation_id", "missing"), 422, "VALIDATION_ERROR")
        payload = json.loads(response.body)
        payload["error"]["fields"] = safe_fields[:20]
        safe_headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-length", "content-type"}
        }
        return JSONResponse(status_code=422, content=payload, headers=safe_headers)

    @application.get("/healthz", response_model=Envelope, operation_id="getHealth")
    def health() -> Envelope | JSONResponse:
        health_data = runtime_store.health()
        health_data["version"] = __version__
        health_data["providerProfiles"] = profile_payloads()
        if health_data.get("database") != "ready" or health_data.get("vector") not in {"ready", "not-applicable"}:
            return JSONResponse(status_code=503, content=_envelope(health_data, "healthcheck").model_dump(by_alias=True, mode="json"))
        return _envelope(health_data, "healthcheck")

    @application.post("/v1/sources", response_model=Envelope, status_code=status.HTTP_201_CREATED, operation_id="createSource")
    def create_source(
        request: SourceCreateRequest,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        return _envelope(runtime_store.create_source(_model_data(request), idempotency_key), correlation_id)

    @application.get("/v1/source-profiles", response_model=Envelope, operation_id="listSourceProfiles")
    def list_source_profiles(correlation_id: Annotated[str, Depends(_correlation_id)]) -> Envelope:
        return _envelope(runtime_store.list_source_profiles(), correlation_id)

    @application.get("/v1/source-mirrors", response_model=Envelope, operation_id="listSourceMirrors")
    def list_source_mirrors(correlation_id: Annotated[str, Depends(_correlation_id)]) -> Envelope:
        return _envelope(runtime_store.list_source_mirrors(), correlation_id)

    @application.post(
        "/v1/source-profiles/{sourceProfileId}/discoveries",
        response_model=Envelope,
        status_code=status.HTTP_201_CREATED,
        operation_id="discoverSourceCandidate",
    )
    def discover_source_candidate(
        sourceProfileId: str,
        request: SourceDiscoveryRequest,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        profile = get_profile(sourceProfileId)
        started = time.perf_counter()
        try:
            commit = source_pipeline.discover(profile)
        except FetchError as exc:
            runtime_store.record_mirror_sync(
                profile.repository, None, False, exc.code, round((time.perf_counter() - started) * 1000)
            )
            raise
        runtime_store.record_mirror_sync(
            profile.repository, commit, True, None, round((time.perf_counter() - started) * 1000)
        )
        data = runtime_store.register_candidate(profile.profile_id, commit, request.detected_by, idempotency_key)
        return _envelope(data, correlation_id)

    @application.get("/v1/source-versions/{sourceVersionId}", response_model=Envelope, operation_id="getSourceVersion")
    def get_source_version(
        sourceVersionId: UUID, correlation_id: Annotated[str, Depends(_correlation_id)]
    ) -> Envelope:
        return _envelope(runtime_store.get_source_version(sourceVersionId), correlation_id)

    @application.post(
        "/v1/source-versions/{sourceVersionId}/scan",
        response_model=Envelope,
        operation_id="scanSourceVersion",
    )
    def scan_source_version(
        sourceVersionId: UUID,
        request: SourceScanRequest,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        version = runtime_store.get_source_version(sourceVersionId)
        profile = get_profile(version["sourceProfileId"])
        report = source_pipeline.scan(profile, version["commit"])
        return _envelope(
            runtime_store.record_scan(sourceVersionId, report, request.scanned_by, idempotency_key), correlation_id
        )

    @application.get(
        "/v1/source-versions/{sourceVersionId}/files", response_model=Envelope, operation_id="listSourceVersionFiles"
    )
    def list_source_version_files(
        sourceVersionId: UUID, correlation_id: Annotated[str, Depends(_correlation_id)]
    ) -> Envelope:
        return _envelope(runtime_store.list_source_files(sourceVersionId), correlation_id)

    @application.post(
        "/v1/source-versions/{sourceVersionId}/approve", response_model=Envelope, operation_id="approveSourceVersion"
    )
    def approve_source_version(
        sourceVersionId: UUID,
        request: SourceApprovalRequest,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        return _envelope(
            runtime_store.approve_version(sourceVersionId, _model_data(request), idempotency_key), correlation_id
        )

    @application.get("/v1/sources/{sourceId}", response_model=Envelope, operation_id="getSource")
    def get_source(sourceId: UUID, correlation_id: Annotated[str, Depends(_correlation_id)]) -> Envelope:
        return _envelope(runtime_store.get_source(sourceId), correlation_id)

    @application.post("/v1/compatibility-sets", response_model=Envelope, status_code=status.HTTP_201_CREATED, operation_id="createCompatibilitySet")
    def create_compatibility_set(
        request: CompatibilitySetCreateRequest,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        return _envelope(runtime_store.create_compatibility_set(_model_data(request), idempotency_key), correlation_id)

    @application.post("/v1/sources/{sourceId}/approve", response_model=Envelope, operation_id="approveSource")
    def approve_source(
        sourceId: UUID,
        request: SourceApprovalRequest,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        return _envelope(runtime_store.approve_source(sourceId, _model_data(request), idempotency_key), correlation_id)

    @application.post("/v1/sources/{sourceId}/ingestions", response_model=Envelope, status_code=status.HTTP_202_ACCEPTED, operation_id="createIngestion")
    def create_ingestion(
        sourceId: UUID,
        request: IngestionCreateRequest,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        return _envelope(
            runtime_store.create_ingestion(sourceId, _model_data(request), idempotency_key, correlation_id),
            correlation_id,
        )

    @application.delete("/v1/sources/{sourceId}", response_model=Envelope, status_code=status.HTTP_202_ACCEPTED, operation_id="withdrawSource")
    def withdraw_source(
        sourceId: UUID,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        return _envelope(runtime_store.withdraw_source(sourceId, idempotency_key, correlation_id), correlation_id)

    @application.get("/v1/jobs/{jobId}", response_model=Envelope, operation_id="getJob")
    def get_job(jobId: UUID, correlation_id: Annotated[str, Depends(_correlation_id)]) -> Envelope:
        return _envelope(runtime_store.get_job(jobId), correlation_id)

    @application.post("/v1/jobs/{jobId}/run", response_model=Envelope, operation_id="runIndexingJob")
    def run_job(
        jobId: UUID,
        request: JobRunRequest,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        return _envelope(
            runtime_store.run_job(jobId, _model_data(request), idempotency_key, correlation_id,
                                  runtime_embeddings, runtime_settings.embedding_batch_size),
            correlation_id,
        )

    @application.post("/v1/jobs/{jobId}/complete", response_model=Envelope, operation_id="completeIngestionJob")
    def complete_ingestion_job(
        jobId: UUID,
        request: JobCompletionRequest,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        return _envelope(runtime_store.complete_job(jobId, _model_data(request), idempotency_key), correlation_id)

    def _retrieve(request: QueryRequest, correlation_id: str) -> dict[str, Any]:
        result = runtime_embeddings.embed([request.question])
        return runtime_store.retrieve(_model_data(request), result, correlation_id)

    @application.post("/v1/rag/retrieve", response_model=Envelope, operation_id="retrieveRagContext")
    def retrieve_rag(request: QueryRequest, correlation_id: Annotated[str, Depends(_correlation_id)]) -> Envelope:
        return _envelope(_retrieve(request, correlation_id), correlation_id)

    def _query_grounded(request: GroundedQueryRequest, correlation_id: str) -> dict[str, Any]:
        scope = {
            "sourceProfileIds": request.source_profile_ids,
            "compatibilitySetId": request.compatibility_set_id,
        }
        retrieval = _retrieve(request, correlation_id)
        decision = decide_generation(
            retrieval["results"],
            compatibility_set_id=str(request.compatibility_set_id) if request.compatibility_set_id else None,
            source_profile_ids=request.source_profile_ids,
        )
        common = {
            "queryId": request.query_id,
            "scope": scope,
            "retrieval": {
                "resultCount": retrieval["resultCount"],
                "provider": retrieval["provider"],
                "providerCalled": retrieval["providerCalled"],
            },
            "retrievalProviderCalled": retrieval["providerCalled"],
        }
        if decision.state == "ABSTAINED":
            return {**common, "state": "ABSTAINED", "abstainReason": decision.abstain_reason,
                    "answer": None, "citations": [], "providerProfileId": None,
                    "generationProviderCalled": False}
        context = context_from_results(retrieval["results"], request.classification)
        provider_request = ResponsesRequest(
            query_id=str(request.query_id),
            question=request.question,
            profile_id=decision.profile_id or "",
            context=context,
            locale=request.locale,
            safety_identifier=stable_safety_identifier(request.actor_id, safety_identifier_salt),
        )
        try:
            generated = runtime_responses.generate(provider_request)
            runtime_store.record_response_call(request.query_id, generated, correlation_id)
            state, answer, abstain_reason, cited = validate_grounded_result(generated, context)
            return {**common, "state": state, "abstainReason": abstain_reason, "answer": answer,
                    "citations": [citation_payload(item) for item in cited],
                    "providerProfileId": generated.profile_id,
                    "generationProviderCalled": generated.provider == "openai"}
        except ResponsesProviderError as exc:
            runtime_store.record_response_failure(request.query_id, exc, correlation_id)
            return {**common, "state": "FAILED", "abstainReason": None, "answer": None,
                    "citations": [], "providerProfileId": exc.profile_id,
                    "generationProviderCalled": exc.provider_called,
                    "errorCode": exc.code, "failureClass": exc.failure_class}

    @application.post("/v1/rag/query", response_model=Envelope, operation_id="queryRag")
    def query_rag(request: GroundedQueryRequest, correlation_id: Annotated[str, Depends(_correlation_id)]) -> Envelope:
        return _envelope(_query_grounded(request, correlation_id), correlation_id)

    @application.post("/v1/artifacts", response_model=Envelope, status_code=status.HTTP_201_CREATED, operation_id="createArtifact")
    async def create_artifact(
        request: Request,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        filename: Annotated[str, Header(alias="X-Artifact-Filename")],
        classification: Annotated[str, Header(alias="X-Artifact-Classification")] = "D0",
    ) -> Envelope:
        if classification != "D0":
            raise InvalidBoundaryError("only D0 artifacts are permitted")
        media_type = request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        record = artifact_store.put(filename, media_type, await request.body())
        return _envelope(record.payload(), correlation_id)

    @application.get("/v1/artifacts/{artifactId}", response_model=Envelope, operation_id="getArtifact")
    def get_artifact(artifactId: UUID, correlation_id: Annotated[str, Depends(_correlation_id)]) -> Envelope:
        return _envelope(artifact_store.get(artifactId).payload(), correlation_id)

    @application.delete("/v1/artifacts/{artifactId}", response_model=Envelope, operation_id="deleteArtifact")
    def delete_artifact(
        artifactId: UUID,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        return _envelope({"artifactId": artifactId, "deleted": artifact_store.delete(artifactId)}, correlation_id)

    def _query_comprehensive(request: ComprehensiveQueryRequest, correlation_id: str) -> dict[str, Any]:
        compatibility = runtime_store.resolve_compatibility_set(request.compatibility_set_id, request.product_version)
        explicit_profiles = request.source_profile_ids or (compatibility or {}).get("sourceProfileIds")
        versioned_review = not explicit_profiles and not compatibility
        plan = plan_query(request.question, explicit_profiles)
        plan_payload = versioned_plan(request.question) if versioned_review else plan.payload()
        if versioned_review:
            profiles = list(VERSIONED_SOURCE_PROFILES)
        else:
            profiles = list(plan.profile_ids)
        if plan.state != "READY":
            if versioned_review:
                pass
            else:
                return {"queryId": request.query_id, "state": "NEEDS_INFORMATION", "plan": plan_payload,
                    "report": None, "citations": [], "generationProviderCalled": False}
        if compatibility and not set(profiles).issubset(set(compatibility["sourceProfileIds"])):
            return {"queryId": request.query_id, "state": "NEEDS_INFORMATION", "plan": plan_payload,
                    "questionsNeeded": ["선택한 영역을 모두 포함하는 승인된 Compatibility Set이 필요합니다."],
                    "report": None, "citations": [], "generationProviderCalled": False}
        if len(profiles) > 1 and not compatibility and not versioned_review:
            return {"queryId": request.query_id, "state": "NEEDS_INFORMATION", "plan": plan_payload,
                    "questionsNeeded": ["제품 버전 또는 승인된 compatibilitySetId를 지정하십시오."],
                    "report": None, "citations": [], "generationProviderCalled": False}
        scope = {
            "policy": "DIPLO_CURRENT_EUROPA_PREVIEW_V1" if versioned_review else "EXPLICIT_V1",
            "compatibilitySetId": compatibility["compatibilitySetId"] if compatibility else None,
            "sourceProfileIds": None if compatibility else profiles,
        }
        coverage: list[dict[str, object]] = []
        if versioned_review:
            retrieval_question = expand_retrieval_question(request.question)
            embedding_result = runtime_embeddings.embed([retrieval_question])
            results_by_profile: dict[str, list[dict[str, Any]]] = {}
            provider_called = embedding_result.provider == "openai"
            for profile_id in VERSIONED_SOURCE_PROFILES:
                if profile_id == CURATED_PLATFORM_PROFILE:
                    results_by_profile[profile_id] = curated_platform_results(request.question)
                    continue
                retrieval_request = QueryRequest(
                    queryId=request.query_id, question=retrieval_question, sourceProfileIds=[profile_id],
                    locale=request.locale, classification=request.classification,
                )
                item = runtime_store.retrieve(_model_data(retrieval_request), embedding_result, correlation_id)
                results_by_profile[profile_id] = item["results"]
            coverage = coverage_payload(request.question, results_by_profile)
            retrieval = {
                "results": select_context_results(request.question, results_by_profile),
                "providerCalled": provider_called,
            }
        else:
            retrieval_request = QueryRequest(
                queryId=request.query_id, question=request.question,
                compatibilitySetId=scope["compatibilitySetId"], sourceProfileIds=scope["sourceProfileIds"],
                locale=request.locale, classification=request.classification,
            )
            retrieval = _retrieve(retrieval_request, correlation_id)
        context = context_from_results(retrieval["results"], request.classification)
        if not context:
            return {"queryId": request.query_id, "state": "ABSTAINED", "plan": plan_payload,
                    "scope": scope, "coverage": coverage,
                    "report": None, "citations": [], "abstainReason": "no-grounding", "generationProviderCalled": False}
        artifacts = tuple(artifact_store.evidence(artifact_id) for artifact_id in request.artifact_ids)
        provider_request = ComprehensiveResponsesRequest(
            query_id=str(request.query_id), question=request.question, context=context, artifacts=artifacts,
            locale=request.locale, safety_identifier=stable_safety_identifier(request.actor_id, safety_identifier_salt),
            source_roles=tuple(SOURCE_ROLES.items()) if versioned_review else (),
        )
        try:
            generated = runtime_responses.generate_comprehensive(provider_request)
            runtime_store.record_response_call(request.query_id, generated, correlation_id)
            cited = {item.chunk_id: item for item in context}
            citations = [citation_payload(cited[item]) for item in generated.citations_used if item in cited]
            return {"queryId": request.query_id, "state": generated.report["state"], "plan": plan_payload,
                    "scope": scope, "coverage": coverage, "report": generated.report, "citations": citations,
                    "generationProviderCalled": generated.provider == "openai", "providerProfileId": generated.profile_id}
        except ResponsesProviderError as exc:
            runtime_store.record_response_failure(request.query_id, exc, correlation_id)
            return {"queryId": request.query_id, "state": "FAILED", "plan": plan_payload, "report": None,
                    "scope": scope, "coverage": coverage,
                    "citations": [], "generationProviderCalled": exc.provider_called, "errorCode": exc.code,
                    "failureClass": exc.failure_class}

    @application.post("/v1/assist/query", response_model=Envelope, operation_id="queryAssist")
    def query_assist(request: ComprehensiveQueryRequest, correlation_id: Annotated[str, Depends(_correlation_id)]) -> Envelope:
        return _envelope(_query_comprehensive(request, correlation_id), correlation_id)

    @application.post(
        "/v1/community/cases", response_model=Envelope, status_code=status.HTTP_201_CREATED,
        operation_id="createCommunityCase",
    )
    def create_community_case(
        request: CommunityCaseCreateRequest,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        assist_request = ComprehensiveQueryRequest(
            queryId=uuid4(), question=f"{request.title}\n\n{request.question}", actorId=f"community:{request.author_id}",
            productVersion=request.product_version or "diplo", artifactIds=request.artifact_ids,
            locale="ko-KR", classification="D0",
        )
        result = _query_comprehensive(assist_request, correlation_id)
        draft = {"draftAnswer": format_draft(result), "answerState": result.get("state"),
                 "citations": result.get("citations") or [], "evidenceLedger": evidence_ledger(result)}
        result = runtime_store.create_community_case(_model_data(request), draft, idempotency_key, correlation_id)
        created = result.pop("created", False)
        review_ready = not runtime_settings.community_review_post_enabled
        if created and runtime_settings.community_review_post_enabled and result.get("draftAnswer"):
            try:
                marker = f"<!-- techflow-review:{result['caseId']}:v{result['draftVersion']} -->"
                review = flarum_client.publish_review_reply(
                    result["discussionId"], result["draftAnswer"], marker,
                )
                result = runtime_store.attach_community_review(
                    result["caseId"], review, f"review-post-{result['caseId']}-v{result['draftVersion']}",
                )
                review_ready = True
                _json_log(
                    "community_review_post_created", correlationId=correlation_id,
                    caseId=str(result["caseId"]), postId=result["reviewPostId"], isApproved=False,
                )
            except Exception as exc:
                _json_log(
                    "community_review_post_failed", correlationId=correlation_id,
                    caseId=str(result["caseId"]), errorType=type(exc).__name__,
                )
        if runtime_settings.chat_bot_enabled and created and review_ready:
            reviewer_ids = [item["userId"] for item in runtime_store.list_chat_reviewers()]
            if not reviewer_ids:
                _json_log(
                    "community_chat_notification_skipped", correlationId=correlation_id,
                    caseId=str(result["caseId"]), reason="no_connected_reviewer",
                )
            else:
                for attempt in range(1, 4):
                    try:
                        runtime_chat_bot.send(reviewer_ids, case_card(result, new_notification=True))
                        _json_log(
                            "community_chat_notification_sent", correlationId=correlation_id,
                            caseId=str(result["caseId"]), reviewerCount=len(reviewer_ids), attempt=attempt,
                        )
                        break
                    except Exception as exc:
                        if attempt == 3:
                            _json_log(
                                "community_chat_notification_failed", correlationId=correlation_id,
                                caseId=str(result["caseId"]), errorType=type(exc).__name__, attempts=attempt,
                            )
                        else:
                            time.sleep(0.2 * attempt)
        return _envelope(result, correlation_id)

    @application.get("/v1/community/cases/{caseId}", response_model=Envelope, operation_id="getCommunityCase")
    def get_community_case(caseId: UUID, correlation_id: Annotated[str, Depends(_correlation_id)]) -> Envelope:
        return _envelope(runtime_store.get_community_case(caseId), correlation_id)

    @application.get(
        "/v1/community/discussions/{discussionId}/case",
        response_model=Envelope,
        operation_id="getCommunityCaseByDiscussion",
    )
    def get_community_case_by_discussion(
        discussionId: str, correlation_id: Annotated[str, Depends(_correlation_id)]
    ) -> Envelope:
        return _envelope(runtime_store.get_community_case_by_discussion(discussionId), correlation_id)

    @application.post(
        "/v1/community/reviews/reconcile", response_model=Envelope,
        operation_id="reconcileCommunityReviews",
    )
    def reconcile_community_reviews(
        correlation_id: Annotated[str, Depends(_correlation_id)],
        _: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        checked = approved = 0
        for item in runtime_store.list_community_cases(("DRAFT_PENDING",), 100):
            post_id = str(item.get("reviewPostId") or "")
            if not post_id:
                continue
            checked += 1
            if flarum_client.review_post_is_approved(post_id):
                runtime_store.mark_community_review_approved(
                    item["caseId"], f"flarum-review-approved-{post_id}",
                )
                approved += 1
        return _envelope({"checked": checked, "approved": approved}, correlation_id)

    @application.post("/v1/community/cases/{caseId}/decision", response_model=Envelope, operation_id="decideCommunityCase")
    def decide_community_case(
        caseId: UUID, request: CommunityDecisionRequest,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        return _envelope(runtime_store.decide_community_case(caseId, _model_data(request), idempotency_key), correlation_id)

    @application.post("/v1/community/cases/{caseId}/publish", response_model=Envelope, operation_id="publishCommunityCase")
    def publish_community_case(
        caseId: UUID, request: CommunityPublishRequest,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        current = runtime_store.get_community_case(caseId)
        if current["state"] == "PUBLISHED":
            current["requestedBy"] = request.requested_by
            return _envelope(current, correlation_id)
        if current["state"] != "APPROVED":
            raise InvalidStateError("only approved drafts can be published")
        marker = f"<!-- techflow-case:{caseId}:approval:{current['approvalVersion']} -->"
        publication = flarum_client.publish_reply(current["discussionId"], current["draftAnswer"], marker)
        result = runtime_store.mark_community_published(caseId, publication, idempotency_key)
        result["requestedBy"] = request.requested_by
        return _envelope(result, correlation_id)

    def _resolve_chat_case(reference: str) -> dict[str, Any]:
        if not CASE_REFERENCE.fullmatch(reference):
            raise InvalidBoundaryError("invalid Community case reference")
        return runtime_store.resolve_community_case(reference)

    def _pending_chat_response() -> dict[str, Any]:
        cases = runtime_store.list_community_cases(("DRAFT_PENDING", "APPROVED"), 10)
        if not cases:
            return {"text": "현재 승인 대기 중인 Community 답변이 없습니다."}
        lines = ["Community 승인 대기 목록"]
        for item in cases:
            lines.append(
                f"• {case_reference(item)} · Discussion #{item['discussionId']} · V{item['draftVersion']} · "
                f"{item.get('answerState') or '-'} · {item['title']}"
            )
        lines.append("상세 <Case 앞 8자> 명령으로 답변을 확인하세요. 내부 근거는 근거 <Case 앞 8자> 명령에서만 표시됩니다.")
        return {"text": "\n".join(lines)[:7000]}

    async def _wait_for_case(case_id: UUID, desired: set[str], timeout_seconds: float = 15.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        current = runtime_store.get_community_case(case_id)
        while current["state"] not in desired and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
            current = runtime_store.get_community_case(case_id)
        return current

    @application.post(
        "/v1/chat/synology/events", response_class=JSONResponse,
        operation_id="handleSynologyChatEvent",
    )
    async def handle_synology_chat_event(request: Request) -> JSONResponse:
        try:
            event = parse_chat_event(request.headers.get("content-type", ""), await request.body())
            runtime_chat_bot.validate(event.token)
            allowed = {item.casefold() for item in runtime_settings.chat_reviewer_usernames}
            command, args = parse_command(event)
            reviewer_commands = {"connect", "pending", "detail", "evidence", "history", "approve", "reject", "edit"}
            if command in reviewer_commands and event.username.casefold() not in allowed:
                return JSONResponse(status_code=403, content={"text": "승인 권한이 없는 Chat 사용자입니다."})
            if command in reviewer_commands:
                runtime_store.upsert_chat_reviewer(event.user_id, event.username)
            if command in {"help", "connect"}:
                response = _pending_chat_response() if command == "connect" else {"text": help_text()}
                if command == "connect":
                    response["text"] = f"{event.username} 계정을 TechFlow 승인 담당자로 연결했습니다.\n\n{response['text']}"
                return JSONResponse(content=response)
            if command == "pending":
                return JSONResponse(content=_pending_chat_response())
            if command == "detail":
                if len(args) != 1:
                    return JSONResponse(content={"text": "사용법: 상세 <Discussion ID 또는 Case 앞 8자>"})
                return JSONResponse(content=case_card(_resolve_chat_case(args[0])))
            if command == "evidence":
                if len(args) != 1:
                    return JSONResponse(content={"text": "사용법: 근거 <Discussion ID 또는 Case 앞 8자>"})
                return JSONResponse(content={"text": case_evidence_text(_resolve_chat_case(args[0]))})
            if command == "history":
                if not args:
                    cases = runtime_store.list_community_cases(None, 10)
                    text = "최근 Community 처리 이력\n" + "\n".join(
                        f"• {case_reference(item)} · {item['state']} · {item.get('reviewer') or '-'} · {item['title']}"
                        for item in cases
                    )
                    return JSONResponse(content={"text": text[:7000]})
                case = _resolve_chat_case(args[0])
                events = runtime_store.list_community_case_events(case["caseId"], 10)
                text = f"Case {case_reference(case)} 처리 이력\n" + "\n".join(
                    f"• {item['createdAt'].isoformat()} · {item['eventType']} · {item['actor']}"
                    for item in events
                )
                return JSONResponse(content={"text": text[:7000]})
            if command in {"approve", "reject", "edit"}:
                minimum = 3 if command == "edit" else 2
                if len(args) < minimum:
                    return JSONResponse(content={"text": help_text()})
                case = _resolve_chat_case(args[0])
                try:
                    version = int(args[1])
                except ValueError:
                    return JSONResponse(content={"text": "Draft Version은 숫자여야 합니다."})
                decision = "APPROVE" if command in {"approve", "edit"} else "REJECT"
                edited_answer = args[2] if command == "edit" else None
                note = (args[2] if command == "reject" and len(args) > 2 else "Chat button decision")[:1000]
                if decision == "APPROVE" and case["state"] == "PUBLISHED":
                    return JSONResponse(content={"text": case_text(case, include_answer=False)})
                if decision == "REJECT" and case["state"] == "REJECTED":
                    return JSONResponse(content={"text": case_text(case, include_answer=False)})
                flow_payload = {
                    "eventId": event.event_key, "correlationId": request.state.correlation_id,
                    "caseId": str(case["caseId"]), "reviewer": f"chat:{event.username}",
                    "expectedDraftVersion": version, "editedAnswer": edited_answer, "note": note,
                }
                await asyncio.to_thread(runtime_community_flows.decide, decision, flow_payload)
                desired = {"PUBLISHED"} if decision == "APPROVE" else {"REJECTED"}
                current = await _wait_for_case(case["caseId"], desired)
                if current["state"] not in desired:
                    return JSONResponse(content={
                        "text": f"요청은 접수됐지만 최종 상태가 {current['state']}입니다. 이력 명령으로 확인하세요."
                    })
                return JSONResponse(content={"text": case_text(current, include_answer=False)})
            if command == "unknown" and event.text:
                assist_request = ComprehensiveQueryRequest(
                    queryId=uuid4(), question=event.text, actorId=f"chat:{event.user_id}",
                    productVersion="diplo", locale="ko-KR", classification="D0",
                )
                result = await asyncio.to_thread(_query_comprehensive, assist_request, request.state.correlation_id)
                answer = format_public_answer(result)
                if answer:
                    return JSONResponse(content={"text": answer[:7000]})
                if result.get("state") == "NEEDS_INFORMATION":
                    needed = result.get("questionsNeeded") or (result.get("plan") or {}).get("questionsNeeded") or []
                    return JSONResponse(content={"text": ("추가 정보가 필요합니다.\n" + "\n".join(f"• {item}" for item in needed))[:7000]})
                return JSONResponse(content={"text": "검토 근거가 충분하지 않아 답변을 보류했습니다. 로그나 화면 정보를 함께 제공해 주세요."})
            return JSONResponse(content={"text": "알 수 없는 명령입니다.\n\n" + help_text()})
        except InvalidBoundaryError:
            return JSONResponse(status_code=403, content={"text": "요청 인증 또는 입력 검증에 실패했습니다."})
        except StoreError as exc:
            return JSONResponse(status_code=exc.http_status, content={"text": "Case 상태가 변경됐거나 찾을 수 없습니다."})
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse(status_code=400, content={"text": "Chat 요청 형식을 해석할 수 없습니다."})

    @application.post("/v1/evaluations/runs", response_model=Envelope, status_code=status.HTTP_202_ACCEPTED, operation_id="createEvaluationRun")
    def create_evaluation_run(
        request: EvaluationRunCreateRequest,
        correlation_id: Annotated[str, Depends(_correlation_id)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> Envelope:
        return _envelope(
            runtime_store.create_evaluation_run(_model_data(request), idempotency_key, correlation_id),
            correlation_id,
        )

    @application.get("/v1/evaluations/runs/{runId}", response_model=Envelope, operation_id="getEvaluationRun")
    def get_evaluation_run(runId: UUID, correlation_id: Annotated[str, Depends(_correlation_id)]) -> Envelope:
        return _envelope(runtime_store.get_evaluation_run(runId), correlation_id)

    def _execute_golden_cases(run_id: UUID, cases: list[dict[str, Any]], actor_id: str) -> None:
        try:
            for index, case in enumerate(cases, 1):
                case_correlation_id = f"eval-{str(run_id)[:12]}-{index:03d}"
                started = time.perf_counter()
                result = _query_grounded(
                    GroundedQueryRequest(
                        queryId=uuid4(),
                        question=case["question"],
                        actorId=actor_id,
                        sourceProfileIds=case["sourceProfileIds"],
                        classification="D0",
                        locale=case["locale"],
                    ),
                    case_correlation_id,
                )
                latency_ms = round((time.perf_counter() - started) * 1000)
                runtime_store.record_evaluation_result(
                    run_id, case, result, judge_case(case, result).payload(), latency_ms
                )
            runtime_store.finish_evaluation_run(run_id)
        except Exception as exc:
            _json_log("evaluation_failed", runId=str(run_id), errorType=type(exc).__name__)
            try:
                runtime_store.finish_evaluation_run(run_id, failed=True)
            except Exception:
                _json_log("evaluation_failure_record_failed", runId=str(run_id))

    @application.post(
        "/v1/evaluations/runs/{runId}/execute",
        response_model=Envelope,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="executeEvaluationRun",
    )
    def execute_evaluation_run(
        runId: UUID,
        request: EvaluationExecuteRequest,
        background_tasks: BackgroundTasks,
        correlation_id: Annotated[str, Depends(_correlation_id)],
    ) -> Envelope:
        run = runtime_store.get_evaluation_run(runId)
        profiles = set(run.get("sourceProfileIds") or [])
        if not profiles:
            raise InvalidBoundaryError("Golden Set execution requires sourceProfileIds scope")
        golden = load_golden_set()
        cases = [case for case in golden["cases"] if set(case["sourceProfileIds"]).issubset(profiles)]
        if not cases:
            raise InvalidBoundaryError("evaluation scope selects no Golden Set cases")
        runtime_store.start_evaluation_run(runId, len(cases))
        background_tasks.add_task(_execute_golden_cases, runId, cases, request.requested_by)
        return _envelope(
            {"runId": runId, "caseSetId": request.case_set_id, "state": "RUNNING", "totalCases": len(cases)},
            correlation_id,
        )

    @application.get(
        "/v1/evaluations/runs/{runId}/results",
        response_model=Envelope,
        operation_id="listEvaluationResults",
    )
    def list_evaluation_results(
        runId: UUID, correlation_id: Annotated[str, Depends(_correlation_id)]
    ) -> Envelope:
        return _envelope(runtime_store.list_evaluation_results(runId), correlation_id)

    return application


try:
    app = create_app()
except ConfigurationError:
    raise
