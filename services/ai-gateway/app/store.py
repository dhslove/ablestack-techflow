"""Storage interface and deterministic in-memory implementation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Protocol
from uuid import UUID, uuid4

from .provider import PROVIDER_PROFILES
from .conversation import conversation_state_for_draft, source_post_id


class StoreError(RuntimeError):
    code = "STORE_ERROR"
    http_status = 500


class NotFoundError(StoreError):
    code = "NOT_FOUND"
    http_status = 404


class ConflictError(StoreError):
    code = "CONFLICT"
    http_status = 409


class InvalidStateError(StoreError):
    code = "INVALID_STATE"
    http_status = 409


class InvalidBoundaryError(StoreError):
    code = "INVALID_BOUNDARY"
    http_status = 400


class Store(Protocol):
    def health(self) -> dict[str, str]: ...
    def close(self) -> None: ...
    def list_source_profiles(self) -> list[dict[str, Any]]: ...
    def list_source_mirrors(self) -> list[dict[str, Any]]: ...
    def record_mirror_sync(
        self, repository: str, commit: str | None, success: bool, error_code: str | None, duration_ms: int
    ) -> dict[str, Any]: ...
    def register_candidate(self, profile_id: str, commit: str, detected_by: str, idempotency_key: str) -> dict[str, Any]: ...
    def get_source_version(self, version_id: UUID) -> dict[str, Any]: ...
    def record_scan(self, version_id: UUID, report: dict[str, Any], scanned_by: str, idempotency_key: str) -> dict[str, Any]: ...
    def list_source_files(self, version_id: UUID) -> list[dict[str, Any]]: ...
    def approve_version(self, version_id: UUID, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def complete_job(self, job_id: UUID, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def create_source(self, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def get_source(self, source_id: UUID) -> dict[str, Any]: ...
    def approve_source(self, source_id: UUID, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def create_compatibility_set(self, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def resolve_compatibility_set(self, compatibility_set_id: UUID | None, product_version: str | None) -> dict[str, Any] | None: ...
    def create_ingestion(
        self, source_id: UUID, request: dict[str, Any], idempotency_key: str, correlation_id: str = "legacy"
    ) -> dict[str, Any]: ...
    def withdraw_source(
        self, source_id: UUID, idempotency_key: str, correlation_id: str = "legacy"
    ) -> dict[str, Any]: ...
    def get_job(self, job_id: UUID) -> dict[str, Any]: ...
    def run_job(
        self, job_id: UUID, request: dict[str, Any], idempotency_key: str,
        correlation_id: str, adapter: Any, batch_size: int,
    ) -> dict[str, Any]: ...
    def retrieve(self, request: dict[str, Any], embedding_result: Any, correlation_id: str) -> dict[str, Any]: ...
    def record_response_call(self, query_id: UUID, result: Any, correlation_id: str) -> None: ...
    def record_response_failure(self, query_id: UUID, error: Any, correlation_id: str) -> None: ...
    def create_evaluation_run(
        self, request: dict[str, Any], idempotency_key: str, correlation_id: str = "legacy"
    ) -> dict[str, Any]: ...
    def get_evaluation_run(self, run_id: UUID) -> dict[str, Any]: ...
    def start_evaluation_run(self, run_id: UUID, total_cases: int) -> dict[str, Any]: ...
    def record_evaluation_result(
        self, run_id: UUID, case: dict[str, Any], result: dict[str, Any], judgment: dict[str, Any], latency_ms: int
    ) -> None: ...
    def finish_evaluation_run(self, run_id: UUID, failed: bool = False) -> dict[str, Any]: ...
    def list_evaluation_results(self, run_id: UUID) -> list[dict[str, Any]]: ...
    def create_community_case(self, request: dict[str, Any], draft: dict[str, Any], idempotency_key: str, correlation_id: str) -> dict[str, Any]: ...
    def retry_failed_community_case(self, request: dict[str, Any], draft: dict[str, Any], idempotency_key: str, correlation_id: str) -> dict[str, Any]: ...
    def community_turn_exists(self, discussion_id: str, source_post_id: str) -> bool: ...
    def list_community_turns(self, discussion_id: str) -> list[dict[str, Any]]: ...
    def record_community_turn(self, request: dict[str, Any], idempotency_key: str, correlation_id: str) -> dict[str, Any]: ...
    def sync_community_resolution(self, request: dict[str, Any], idempotency_key: str, correlation_id: str) -> dict[str, Any]: ...
    def get_community_case(self, case_id: UUID) -> dict[str, Any]: ...
    def get_community_case_by_discussion(self, discussion_id: str) -> dict[str, Any]: ...
    def resolve_community_case(self, reference: str) -> dict[str, Any]: ...
    def list_community_cases(self, states: tuple[str, ...] | None = None, limit: int = 10) -> list[dict[str, Any]]: ...
    def list_community_case_events(self, case_id: UUID, limit: int = 10) -> list[dict[str, Any]]: ...
    def decide_community_case(self, case_id: UUID, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def attach_community_review(self, case_id: UUID, review: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def mark_community_review_approved(self, case_id: UUID, idempotency_key: str) -> dict[str, Any]: ...
    def mark_community_review_missing(self, case_id: UUID, idempotency_key: str) -> dict[str, Any]: ...
    def mark_community_published(self, case_id: UUID, publication: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def mark_community_auto_published(self, case_id: UUID, answer: str, publication: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def mark_community_knowledge_published(self, case_id: UUID, answer: str, publication: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def mark_community_knowledge_solution_selected(self, case_id: UUID, selection: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def upsert_chat_reviewer(self, user_id: str, username: str) -> dict[str, Any]: ...
    def list_chat_reviewers(self) -> list[dict[str, Any]]: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStore:
    """Thread-safe store used by unit tests and the non-network PoC canary."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._sources: dict[UUID, dict[str, Any]] = {}
        self._source_versions: dict[UUID, dict[str, Any]] = {}
        self._source_by_profile: dict[str, UUID] = {}
        self._version_by_profile_commit: dict[tuple[str, str], UUID] = {}
        self._source_files: dict[UUID, dict[str, dict[str, Any]]] = {}
        self._blob_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._compatibility_sets: dict[UUID, dict[str, Any]] = {}
        self._jobs: dict[UUID, dict[str, Any]] = {}
        self._evaluation_runs: dict[UUID, dict[str, Any]] = {}
        self._chunks: dict[UUID, Any] = {}
        self._embeddings: dict[UUID, tuple[float, ...]] = {}
        self._symbols: dict[UUID, Any] = {}
        self._relations: dict[UUID, Any] = {}
        self._provider_calls: list[dict[str, Any]] = []
        self._community_cases: dict[UUID, dict[str, Any]] = {}
        self._community_by_discussion: dict[str, UUID] = {}
        self._community_turns: dict[UUID, list[dict[str, Any]]] = {}
        self._community_responses: dict[UUID, list[dict[str, Any]]] = {}
        self._community_events: list[dict[str, Any]] = []
        self._chat_reviewers: dict[str, dict[str, Any]] = {}
        self._idempotency: dict[tuple[str, str], dict[str, Any]] = {}
        from .source_registry import list_repositories, mirror_key

        self._source_mirrors = {
            repository: {
                "repository": repository,
                "mirrorKey": mirror_key(repository),
                "state": "UNINITIALIZED",
                "syncPolicy": "SCHEDULE_6H_RECONCILIATION",
                "staleAfterSeconds": 86400,
                "lastAttemptAt": None,
                "lastSuccessAt": None,
                "lastHeadCommit": None,
                "lastErrorCode": None,
                "consecutiveFailures": 0,
                "lastDurationMs": None,
            }
            for repository in list_repositories()
        }

    def _repeat(self, operation: str, key: str) -> dict[str, Any] | None:
        value = self._idempotency.get((operation, key))
        return deepcopy(value) if value else None

    def _remember(self, operation: str, key: str, value: dict[str, Any]) -> dict[str, Any]:
        self._idempotency[(operation, key)] = deepcopy(value)
        return deepcopy(value)

    def health(self) -> dict[str, str]:
        return {"process": "ready", "database": "ready", "vector": "ready", "provider": "mock"}

    def close(self) -> None:
        return None

    def list_source_profiles(self) -> list[dict[str, Any]]:
        from .source_registry import list_profiles

        return list_profiles()

    def list_source_mirrors(self) -> list[dict[str, Any]]:
        with self._lock:
            now = utc_now()
            result: list[dict[str, Any]] = []
            for repository in sorted(self._source_mirrors):
                item = deepcopy(self._source_mirrors[repository])
                last_success = item["lastSuccessAt"]
                if last_success and now - last_success > timedelta(seconds=item["staleAfterSeconds"]):
                    item["state"] = "STALE"
                result.append(item)
            return result

    def record_mirror_sync(
        self, repository: str, commit: str | None, success: bool, error_code: str | None, duration_ms: int
    ) -> dict[str, Any]:
        with self._lock:
            item = self._source_mirrors.get(repository)
            if item is None:
                raise InvalidBoundaryError("repository is not registered for mirroring")
            now = utc_now()
            item["lastAttemptAt"] = now
            item["lastDurationMs"] = max(0, duration_ms)
            if success:
                item.update(
                    state="HEALTHY", lastSuccessAt=now, lastHeadCommit=commit,
                    lastErrorCode=None, consecutiveFailures=0,
                )
            else:
                item.update(
                    state="DEGRADED", lastErrorCode=error_code or "SOURCE_FETCH_FAILED",
                    consecutiveFailures=item["consecutiveFailures"] + 1,
                )
            return deepcopy(item)

    def _version_payload(self, version: dict[str, Any]) -> dict[str, Any]:
        return deepcopy(version)

    def _latest_version(self, source_id: UUID) -> dict[str, Any]:
        versions = [item for item in self._source_versions.values() if item["sourceId"] == source_id]
        if not versions:
            raise NotFoundError("source version not found")
        return max(versions, key=lambda item: item["createdAt"])

    def register_candidate(
        self, profile_id: str, commit: str, detected_by: str, idempotency_key: str
    ) -> dict[str, Any]:
        from .source_registry import get_profile

        with self._lock:
            if repeated := self._repeat("register_candidate", idempotency_key):
                return repeated
            profile = get_profile(profile_id)
            existing_id = self._version_by_profile_commit.get((profile_id, commit))
            if existing_id:
                return self._remember("register_candidate", idempotency_key, self._source_versions[existing_id])
            source_id = self._source_by_profile.get(profile_id)
            if source_id is None:
                source_id = uuid4()
                self._source_by_profile[profile_id] = source_id
                self._sources[source_id] = {"sourceId": source_id, **profile.payload()}
            version_id, created_at = uuid4(), utc_now()
            version = {
                "sourceId": source_id,
                "sourceVersionId": version_id,
                **profile.payload(),
                "commit": commit,
                "treeSha": None,
                "snapshotHash": None,
                "state": "REGISTERED",
                "detectedBy": detected_by,
                "candidateFileCount": None,
                "eligibleFileCount": None,
                "excludedFileCount": None,
                "blockingViolationCount": None,
                "indexedFileCount": None,
                "quarantineExclusionsAccepted": False,
                "createdAt": created_at,
                "scannedAt": None,
                "approvedAt": None,
                "approvedBy": None,
            }
            self._source_versions[version_id] = version
            self._version_by_profile_commit[(profile_id, commit)] = version_id
            self._source_files[version_id] = {}
            return self._remember("register_candidate", idempotency_key, version)

    def create_source(self, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        from .source_registry import validate_candidate_contract

        profile = validate_candidate_contract(request)
        return self.register_candidate(profile.profile_id, request["commit"], "manual-api", idempotency_key)

    def get_source(self, source_id: UUID) -> dict[str, Any]:
        with self._lock:
            if source_id not in self._sources:
                raise NotFoundError("source not found")
            return self._version_payload(self._latest_version(source_id))

    def get_source_version(self, version_id: UUID) -> dict[str, Any]:
        with self._lock:
            version = self._source_versions.get(version_id)
            if not version:
                raise NotFoundError("source version not found")
            return self._version_payload(version)

    def record_scan(
        self, version_id: UUID, report: dict[str, Any], scanned_by: str, idempotency_key: str
    ) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("record_scan", idempotency_key):
                return repeated
            version = self._source_versions.get(version_id)
            if not version:
                raise NotFoundError("source version not found")
            if version["state"] != "REGISTERED" and version.get("snapshotHash") == report["snapshotHash"]:
                return self._remember("record_scan", idempotency_key, version)
            if version["state"] != "REGISTERED":
                raise InvalidStateError("only registered candidates can be scanned")
            if report["commit"] != version["commit"]:
                raise ConflictError("scan commit differs from registered candidate")
            records: dict[str, dict[str, Any]] = {}
            repository = version["repository"]
            for raw_file in report["files"]:
                file_record = deepcopy(raw_file)
                content = file_record.pop("content", None)
                blob_sha = file_record.get("blob_sha")
                if file_record["decision"] == "ELIGIBLE" and blob_sha and content is not None:
                    cache_key = (repository, blob_sha)
                    cached = self._blob_cache.get(cache_key)
                    if cached and cached["contentHash"] != file_record["content_hash"]:
                        raise ConflictError("blob SHA content hash mismatch")
                    self._blob_cache.setdefault(
                        cache_key,
                        {"repository": repository, "blobSha": blob_sha, "contentHash": file_record["content_hash"], "content": content},
                    )
                records[file_record["path"]] = {
                    "path": file_record["path"],
                    "pathHash": file_record["path_hash"],
                    "blobSha": blob_sha,
                    "contentHash": file_record.get("content_hash"),
                    "sizeBytes": file_record.get("size_bytes"),
                    "sourceKind": file_record.get("source_kind"),
                    "encoding": file_record.get("encoding"),
                    "decision": file_record["decision"],
                    "ruleIds": list(file_record.get("rule_ids") or ()),
                }
            self._source_files[version_id] = records
            version.update(
                {
                    "treeSha": report["treeSha"],
                    "snapshotHash": report["snapshotHash"],
                    "state": "QUARANTINED",
                    "scannedBy": scanned_by,
                    "candidateFileCount": report["candidateFileCount"],
                    "eligibleFileCount": report["eligibleFileCount"],
                    "excludedFileCount": report["excludedFileCount"],
                    "blockingViolationCount": report["blockingViolationCount"],
                    "scannedAt": utc_now(),
                }
            )
            return self._remember("record_scan", idempotency_key, version)

    def list_source_files(self, version_id: UUID) -> list[dict[str, Any]]:
        with self._lock:
            if version_id not in self._source_versions:
                raise NotFoundError("source version not found")
            return deepcopy(sorted(self._source_files[version_id].values(), key=lambda item: item["path"]))

    def approve_version(self, version_id: UUID, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        from .source_registry import get_profile

        with self._lock:
            if repeated := self._repeat("approve_version", idempotency_key):
                return repeated
            version = self._source_versions.get(version_id)
            if not version:
                raise NotFoundError("source version not found")
            if version["state"] != "QUARANTINED":
                raise InvalidStateError("only quarantined source versions can be approved")
            if version["blockingViolationCount"] != 0 and not request.get("acceptQuarantineExclusions", False):
                raise InvalidStateError("blocking quarantine exclusions require explicit reviewer acceptance")
            expected_commit = request.get("expectedCommit")
            if expected_commit and expected_commit != version["commit"]:
                raise ConflictError("approval commit differs from scanned candidate")
            profile = get_profile(version["sourceProfileId"])
            if request["approvedBy"] != profile.initial_reviewer:
                raise InvalidBoundaryError("reviewer is not authorized for this source profile")
            version.update(
                {
                    "state": "APPROVED", "approvedAt": utc_now(), "approvedBy": request["approvedBy"],
                    "quarantineExclusionsAccepted": request.get("acceptQuarantineExclusions", False),
                }
            )
            return self._remember("approve_version", idempotency_key, version)

    def approve_source(self, source_id: UUID, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        with self._lock:
            if source_id not in self._sources:
                raise NotFoundError("source not found")
            version_id = self._latest_version(source_id)["sourceVersionId"]
        return self.approve_version(version_id, request, idempotency_key)

    def create_compatibility_set(self, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("create_compatibility_set", idempotency_key):
                return repeated
            for member in request["members"]:
                version = self._source_versions.get(UUID(str(member["sourceVersionId"])))
                if not version or version["state"] != "ACTIVE":
                    raise InvalidStateError("compatibility members must be active approved source versions")
            set_id = uuid4()
            value = {
                "compatibilitySetId": set_id,
                **request,
                "state": "APPROVED",
                "createdAt": utc_now(),
            }
            self._compatibility_sets[set_id] = value
            return self._remember("create_compatibility_set", idempotency_key, value)

    def resolve_compatibility_set(self, compatibility_set_id: UUID | None, product_version: str | None) -> dict[str, Any] | None:
        with self._lock:
            candidates = [item for item in self._compatibility_sets.values() if item["state"] == "APPROVED"]
            if compatibility_set_id:
                candidates = [item for item in candidates if item["compatibilitySetId"] == compatibility_set_id]
            elif product_version:
                candidates = [item for item in candidates if item["productVersion"] == product_version]
            else:
                return None
            if not candidates:
                return None
            selected = max(candidates, key=lambda item: item["createdAt"])
            profiles = []
            for member in selected["members"]:
                version = self._source_versions.get(UUID(str(member["sourceVersionId"])))
                if version:
                    profiles.append(version["sourceProfileId"])
            return {**deepcopy(selected), "sourceProfileIds": profiles}

    def create_ingestion(
        self, source_id: UUID, request: dict[str, Any], idempotency_key: str, correlation_id: str = "legacy"
    ) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("create_ingestion", idempotency_key):
                return repeated
            if source_id not in self._sources:
                raise NotFoundError("source not found")
            source = self._latest_version(source_id)
            if source["state"] not in {"APPROVED", "ACTIVE"}:
                raise InvalidStateError("source must be approved or active before indexing")
            job_type = "REINDEX" if source["state"] == "ACTIVE" else "INGESTION"
            if job_type == "INGESTION":
                source["state"] = "INDEXING"
            job_id = uuid4()
            value = {
                "jobId": job_id,
                "jobType": job_type,
                "sourceId": source_id,
                "sourceVersionId": source["sourceVersionId"],
                "state": "PENDING",
                "failureClass": None,
                "errorCode": None,
                "requestedBy": request["requestedBy"],
                "correlationId": correlation_id,
                "createdAt": utc_now(),
                "updatedAt": utc_now(),
            }
            self._jobs[job_id] = value
            return self._remember("create_ingestion", idempotency_key, value)

    def complete_job(self, job_id: UUID, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("complete_job", idempotency_key):
                return repeated
            job = self._jobs.get(job_id)
            if not job:
                raise NotFoundError("job not found")
            if job["jobType"] != "INGESTION" or job["state"] not in {"PENDING", "RUNNING"}:
                raise InvalidStateError("job cannot complete indexing")
            version = self._source_versions[job["sourceVersionId"]]
            if version["state"] != "INDEXING":
                raise InvalidStateError("source version is not indexing")
            if request["succeeded"]:
                if request["indexedFileCount"] != version["eligibleFileCount"]:
                    raise ConflictError("partial indexing cannot activate a source version")
                for candidate in self._source_versions.values():
                    if candidate["sourceId"] == version["sourceId"] and candidate["state"] == "ACTIVE":
                        candidate["state"] = "WITHDRAWN"
                version.update({"state": "ACTIVE", "indexedFileCount": request["indexedFileCount"]})
                job.update({"state": "SUCCEEDED", "failureClass": None, "errorCode": None, "updatedAt": utc_now()})
            else:
                version["state"] = "APPROVED"
                job.update(
                    {"state": "FAILED", "failureClass": "TERMINAL", "errorCode": request["errorCode"], "updatedAt": utc_now()}
                )
            return self._remember("complete_job", idempotency_key, job)

    def withdraw_source(
        self, source_id: UUID, idempotency_key: str, correlation_id: str = "legacy"
    ) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("withdraw_source", idempotency_key):
                return repeated
            source = self._sources.get(source_id)
            if not source:
                raise NotFoundError("source not found")
            version = self._latest_version(source_id)
            version["state"] = "WITHDRAWN"
            job_id = uuid4()
            value = {
                "jobId": job_id,
                "jobType": "DELETION",
                "sourceId": source_id,
                "sourceVersionId": version["sourceVersionId"],
                "state": "PENDING",
                "failureClass": None,
                "errorCode": None,
                "requestedBy": "system",
                "correlationId": correlation_id,
                "createdAt": utc_now(),
                "updatedAt": utc_now(),
            }
            self._jobs[job_id] = value
            return self._remember("withdraw_source", idempotency_key, value)

    def get_job(self, job_id: UUID) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise NotFoundError("job not found")
            return deepcopy(self._jobs[job_id])

    def run_job(
        self, job_id: UUID, request: dict[str, Any], idempotency_key: str,
        correlation_id: str, adapter: Any, batch_size: int,
    ) -> dict[str, Any]:
        from .indexing import build_index_bundle

        with self._lock:
            if repeated := self._repeat("run_job", idempotency_key):
                return repeated
            job = self._jobs.get(job_id)
            if not job:
                raise NotFoundError("job not found")
            if job["state"] != "PENDING":
                raise InvalidStateError("only pending jobs can run")
            job.update(state="RUNNING", startedAt=utc_now(), updatedAt=utc_now(), attempt=1)
            if job["jobType"] == "DELETION":
                version_ids = {
                    version_id for version_id, version in self._source_versions.items()
                    if version["sourceId"] == job["sourceId"]
                }
                chunk_ids = {chunk_id for chunk_id, chunk in self._chunks.items() if chunk.source_version_id in version_ids}
                counts = {
                    "chunksDeleted": len(chunk_ids),
                    "embeddingsDeleted": sum(chunk_id in self._embeddings for chunk_id in chunk_ids),
                    "symbolsDeleted": sum(symbol.source_version_id in version_ids for symbol in self._symbols.values()),
                    "relationsDeleted": sum(relation.source_version_id in version_ids for relation in self._relations.values()),
                }
                self._chunks = {key: value for key, value in self._chunks.items() if key not in chunk_ids}
                self._embeddings = {key: value for key, value in self._embeddings.items() if key not in chunk_ids}
                self._symbols = {key: value for key, value in self._symbols.items() if value.source_version_id not in version_ids}
                self._relations = {key: value for key, value in self._relations.items() if value.source_version_id not in version_ids}
                job.update(state="SUCCEEDED", metrics=counts, completedAt=utc_now(), updatedAt=utc_now())
                return self._remember("run_job", idempotency_key, job)
            version = self._source_versions[job["sourceVersionId"]]
            files = []
            for item in self._source_files[job["sourceVersionId"]].values():
                if item["decision"] != "ELIGIBLE":
                    continue
                blob = self._blob_cache[(version["repository"], item["blobSha"])]
                files.append({"path": item["path"], "sourceKind": item["sourceKind"], "content": blob["content"]})
            try:
                bundle = build_index_bundle(job["sourceVersionId"], files, adapter, batch_size)
                if bundle.indexed_file_count != version["eligibleFileCount"]:
                    raise ConflictError("partial indexing cannot activate a source version")
            except Exception:
                if job["jobType"] != "REINDEX":
                    version["state"] = "APPROVED"
                job.update(state="FAILED", failureClass="TERMINAL", errorCode="INDEXING_FAILED", updatedAt=utc_now())
                raise
            if job["jobType"] == "REINDEX":
                version_ids = {version["sourceVersionId"]}
                chunk_ids = {chunk_id for chunk_id, chunk in self._chunks.items() if chunk.source_version_id in version_ids}
                self._chunks = {key: value for key, value in self._chunks.items() if key not in chunk_ids}
                self._embeddings = {key: value for key, value in self._embeddings.items() if key not in chunk_ids}
                self._symbols = {key: value for key, value in self._symbols.items() if value.source_version_id not in version_ids}
                self._relations = {key: value for key, value in self._relations.items() if value.source_version_id not in version_ids}
            self._chunks.update({item.id: item for item in bundle.chunks})
            self._embeddings.update(dict(bundle.embeddings))
            self._symbols.update({item.id: item for item in bundle.symbols})
            self._relations.update({item.id: item for item in bundle.relations})
            if job["jobType"] != "REINDEX":
                for candidate in self._source_versions.values():
                    if candidate["sourceId"] == version["sourceId"] and candidate["state"] == "ACTIVE":
                        candidate["state"] = "WITHDRAWN"
            version.update(state="ACTIVE", indexedFileCount=bundle.indexed_file_count)
            job.update(
                state="SUCCEEDED", completedAt=utc_now(), updatedAt=utc_now(),
                metrics={"indexedFiles": bundle.indexed_file_count, "chunks": len(bundle.chunks),
                         "symbols": len(bundle.symbols), "relations": len(bundle.relations),
                         "embeddingBatches": len(bundle.provider_audits), "parsedFiles": bundle.parsed_file_count,
                         "fallbackFiles": bundle.fallback_file_count},
            )
            return self._remember("run_job", idempotency_key, job)

    def retrieve(self, request: dict[str, Any], embedding_result: Any, correlation_id: str) -> dict[str, Any]:
        from .indexing import cosine_similarity, reciprocal_rank_fusion

        with self._lock:
            version_ids: set[UUID]
            if request.get("compatibilitySetId"):
                compatibility = self._compatibility_sets.get(UUID(str(request["compatibilitySetId"])))
                if not compatibility:
                    raise NotFoundError("compatibility set not found")
                version_ids = {UUID(str(item["sourceVersionId"])) for item in compatibility["members"]}
            else:
                profiles = set(request.get("sourceProfileIds") or ())
                version_ids = {key for key, value in self._source_versions.items()
                               if value["sourceProfileId"] in profiles and value["state"] == "ACTIVE"}
            candidates = [chunk for chunk in self._chunks.values() if chunk.source_version_id in version_ids]
            terms = {term.lower() for term in request["question"].split() if len(term) > 1}
            fts = sorted(candidates, key=lambda c: (-sum(term in c.content.lower() for term in terms), str(c.id)))[:20]
            identifier = sorted(candidates, key=lambda c: (-sum(term in (c.symbol or "").lower() for term in terms), str(c.id)))[:20]
            query_vector = embedding_result.vectors[0]
            vector = sorted(candidates, key=lambda c: (-cosine_similarity(query_vector, self._embeddings[c.id]), str(c.id)))[:30]
            kinds = {chunk.id: chunk.source_kind for chunk in candidates}
            ranked = reciprocal_rank_fusion(
                {"fts": [c.id for c in fts], "identifier": [c.id for c in identifier], "vector": [c.id for c in vector]},
                kinds,
            )[:10]
            lookup = {chunk.id: chunk for chunk in candidates}
            results = []
            for chunk_id, score, channels in ranked:
                chunk = lookup[chunk_id]
                version = self._source_versions[chunk.source_version_id]
                results.append({
                    "chunkId": chunk.id, "sourceVersionId": chunk.source_version_id,
                    "sourceProfileId": version["sourceProfileId"],
                    "repository": version["repository"], "branch": version["branch"],
                    "commit": version["commit"], "path": chunk.path, "startLine": chunk.start_line,
                    "endLine": chunk.end_line, "symbol": chunk.symbol, "score": score, "channels": channels,
                    "sourceKind": chunk.source_kind, "content": chunk.content,
                })
            return {"queryId": request["queryId"], "results": results, "resultCount": len(results),
                    "provider": embedding_result.provider, "providerCalled": embedding_result.provider == "openai"}

    def record_response_call(self, query_id: UUID, result: Any, correlation_id: str) -> None:
        with self._lock:
            self._provider_calls.append({
                "queryId": query_id, "surface": "responses-api", "provider": result.provider,
                "providerProfileId": result.profile_id, "requestedModelId": result.requested_model_id,
                "returnedModelId": result.returned_model_id, "requestId": result.request_id,
                "responseId": result.response_id, "inputTokens": result.input_tokens,
                "outputTokens": result.output_tokens, "latencyMs": result.latency_ms,
                "reasoningEffort": PROVIDER_PROFILES[result.profile_id].reasoning_effort,
                "status": "SUCCEEDED", "correlationId": correlation_id,
            })

    def record_response_failure(self, query_id: UUID, error: Any, correlation_id: str) -> None:
        with self._lock:
            self._provider_calls.append({
                "queryId": query_id, "surface": "responses-api", "provider": "openai",
                "providerProfileId": error.profile_id, "requestedModelId": error.requested_model_id,
                "returnedModelId": None, "requestId": error.request_id, "responseId": None,
                "inputTokens": None, "outputTokens": None, "latencyMs": error.latency_ms,
                "reasoningEffort": PROVIDER_PROFILES[error.profile_id].reasoning_effort,
                "status": "FAILED", "failureClass": error.failure_class, "errorCode": error.code,
                "correlationId": correlation_id,
            })

    def create_evaluation_run(
        self, request: dict[str, Any], idempotency_key: str, correlation_id: str = "legacy"
    ) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("create_evaluation_run", idempotency_key):
                return repeated
            run_id = uuid4()
            value = {
                "runId": run_id,
                **request,
                "correlationId": correlation_id,
                "state": "PENDING",
                "totalCases": 0,
                "passedCases": 0,
                "createdAt": utc_now(),
                "updatedAt": utc_now(),
            }
            self._evaluation_runs[run_id] = value
            return self._remember("create_evaluation_run", idempotency_key, value)

    def get_evaluation_run(self, run_id: UUID) -> dict[str, Any]:
        with self._lock:
            if run_id not in self._evaluation_runs:
                raise NotFoundError("evaluation run not found")
            return deepcopy(self._evaluation_runs[run_id])

    def start_evaluation_run(self, run_id: UUID, total_cases: int) -> dict[str, Any]:
        with self._lock:
            if run_id not in self._evaluation_runs:
                raise NotFoundError("evaluation run not found")
            value = self._evaluation_runs[run_id]
            if value["state"] != "PENDING":
                raise InvalidStateError("only pending evaluation runs can start")
            value.update(state="RUNNING", totalCases=total_cases, passedCases=0, updatedAt=utc_now())
            value["results"] = []
            return deepcopy(value)

    def record_evaluation_result(
        self, run_id: UUID, case: dict[str, Any], result: dict[str, Any], judgment: dict[str, Any], latency_ms: int
    ) -> None:
        with self._lock:
            if run_id not in self._evaluation_runs or self._evaluation_runs[run_id]["state"] != "RUNNING":
                raise InvalidStateError("evaluation run is not running")
            self._evaluation_runs[run_id]["results"].append({
                "caseKey": case["caseKey"], "state": result.get("state"), "passed": judgment["passed"],
                "citationCount": len(result.get("citations") or []), "latencyMs": latency_ms,
                "errorCode": result.get("errorCode"),
            })

    def finish_evaluation_run(self, run_id: UUID, failed: bool = False) -> dict[str, Any]:
        with self._lock:
            if run_id not in self._evaluation_runs:
                raise NotFoundError("evaluation run not found")
            value = self._evaluation_runs[run_id]
            results = value.get("results", [])
            value.update(
                state="FAILED" if failed else "SUCCEEDED",
                passedCases=sum(bool(item["passed"]) for item in results),
                updatedAt=utc_now(),
            )
            return deepcopy(value)

    def list_evaluation_results(self, run_id: UUID) -> list[dict[str, Any]]:
        with self._lock:
            if run_id not in self._evaluation_runs:
                raise NotFoundError("evaluation run not found")
            return deepcopy(self._evaluation_runs[run_id].get("results", []))

    def create_community_case(
        self, request: dict[str, Any], draft: dict[str, Any], idempotency_key: str, correlation_id: str
    ) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("create_community_case", idempotency_key):
                repeated["created"] = False
                repeated["turnCreated"] = False
                return repeated
            discussion_id = request["discussionId"]
            post_id = source_post_id(request)
            if discussion_id in self._community_by_discussion:
                case_id = self._community_by_discussion[discussion_id]
                value = self._community_cases[case_id]
                if any(item["sourcePostId"] == post_id for item in self._community_turns.get(case_id, [])):
                    existing = deepcopy(value)
                    existing.update(created=False, turnCreated=False)
                    return self._remember("create_community_case", idempotency_key, existing)
                turn = self._append_memory_turn(case_id, request, correlation_id)
                was_resolved = value.get("conversationState") == "RESOLVED"
                value.update(
                    state="DRAFT_PENDING",
                    conversationState=conversation_state_for_draft(draft),
                    draftVersion=value["draftVersion"] + 1,
                    draftAnswer=draft.get("draftAnswer"),
                    answerState=draft.get("answerState"),
                    citations=deepcopy(draft.get("citations") or []),
                    evidenceLedger=deepcopy(draft.get("evidenceLedger") or {}),
                    reviewPostId=None,
                    reviewPostUrl=None,
                    publishedPostId=None,
                    publishedPostUrl=None,
                    reviewer=None,
                    lastSeenPostId=post_id,
                    contextVersion=value.get("contextVersion", 0) + 1,
                    reopenedAt=utc_now() if was_resolved else value.get("reopenedAt"),
                    resolvedPostId=None if was_resolved else value.get("resolvedPostId"),
                    resolvedByUserId=None if was_resolved else value.get("resolvedByUserId"),
                    resolvedAt=None if was_resolved else value.get("resolvedAt"),
                    knowledgeBasePostId=None if was_resolved else value.get("knowledgeBasePostId"),
                    knowledgeBasePostUrl=None if was_resolved else value.get("knowledgeBasePostUrl"),
                    knowledgeBaseSourcePostId=None if was_resolved else value.get("knowledgeBaseSourcePostId"),
                    knowledgeBaseAnswer=None if was_resolved else value.get("knowledgeBaseAnswer"),
                    knowledgeBaseSolutionSelectedAt=None if was_resolved else value.get("knowledgeBaseSolutionSelectedAt"),
                    knowledgeBaseSolutionSelectedByUserId=None if was_resolved else value.get("knowledgeBaseSolutionSelectedByUserId"),
                    updatedAt=utc_now(),
                )
                self._community_responses.setdefault(case_id, []).append({
                    "draftVersion": value["draftVersion"], "state": "DRAFT_PENDING",
                    "answer": value["draftAnswer"], "answerState": value["answerState"],
                    "reviewPostId": None, "reviewPostUrl": None, "correlationId": correlation_id,
                })
                self._community_events.append({
                    "caseId": case_id, "eventType": "CONVERSATION_REOPENED" if was_resolved else "FOLLOWUP_DRAFT_CREATED",
                    "actor": "techflow", "createdAt": value["updatedAt"],
                    "details": {"sourcePostId": turn["sourcePostId"], "draftVersion": value["draftVersion"]},
                })
                result = self._remember("create_community_case", idempotency_key, value)
                result.update(created=False, turnCreated=True)
                return result
            case_id = uuid4()
            value = {
                "caseId": case_id, "discussionId": discussion_id, "discussionUrl": request["discussionUrl"],
                "title": request["title"], "state": "DRAFT_PENDING", "draftVersion": 1,
                "draftAnswer": draft.get("draftAnswer"), "answerState": draft.get("answerState"),
                "citations": deepcopy(draft.get("citations") or []), "approvalVersion": 0,
                "evidenceLedger": deepcopy(draft.get("evidenceLedger") or {}),
                "reviewer": None, "reviewPostId": None, "reviewPostUrl": None,
                "publishedPostId": None, "publishedPostUrl": None,
                "conversationState": conversation_state_for_draft(draft),
                "requesterUserId": request["authorId"], "lastSeenPostId": post_id, "contextVersion": 1,
                "resolvedPostId": None, "resolvedByUserId": None, "resolvedAt": None, "reopenedAt": None,
                "knowledgeBasePostId": None, "knowledgeBasePostUrl": None,
                "knowledgeBaseSourcePostId": None, "knowledgeBaseAnswer": None,
                "knowledgeBaseVersion": 0, "knowledgeBasePublishedAt": None,
                "knowledgeBaseSolutionSelectedAt": None, "knowledgeBaseSolutionSelectedByUserId": None,
                "correlationId": correlation_id, "createdAt": utc_now(), "updatedAt": utc_now(),
            }
            self._community_cases[case_id] = value
            self._community_by_discussion[discussion_id] = case_id
            self._community_turns[case_id] = []
            self._append_memory_turn(case_id, request, correlation_id)
            self._community_responses[case_id] = [{
                "draftVersion": 1, "state": "DRAFT_PENDING", "answer": value["draftAnswer"],
                "answerState": value["answerState"], "reviewPostId": None, "reviewPostUrl": None,
                "correlationId": correlation_id,
            }]
            self._community_events.append({
                "caseId": case_id, "eventType": "DRAFT_CREATED", "actor": "techflow",
                "createdAt": value["createdAt"], "details": {"answerState": value["answerState"]},
            })
            result = self._remember("create_community_case", idempotency_key, value)
            result["created"] = True
            result["turnCreated"] = True
            return result

    def _append_memory_turn(
        self, case_id: UUID, request: dict[str, Any], correlation_id: str
    ) -> dict[str, Any]:
        turn = {
            "turnId": uuid4(), "caseId": case_id, "sourcePostId": source_post_id(request),
            "postNumber": request.get("postNumber"),
            "authorUserId": request.get("postAuthorId") or request["authorId"],
            "role": request.get("turnRole") or "REQUESTER", "content": request.get("question") or "",
            "artifactIds": deepcopy(request.get("artifactIds") or []),
            "correlationId": correlation_id, "createdAt": utc_now(),
        }
        self._community_turns.setdefault(case_id, []).append(turn)
        return turn

    def community_turn_exists(self, discussion_id: str, source_post_id_value: str) -> bool:
        with self._lock:
            case_id = self._community_by_discussion.get(discussion_id)
            return bool(case_id and any(
                item["sourcePostId"] == source_post_id_value for item in self._community_turns.get(case_id, [])
            ))

    def retry_failed_community_case(
        self, request: dict[str, Any], draft: dict[str, Any], idempotency_key: str, correlation_id: str
    ) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("retry_failed_community_case", idempotency_key):
                repeated.update(created=False, turnCreated=False)
                return repeated
            case_id = self._community_by_discussion.get(request["discussionId"])
            if not case_id:
                raise NotFoundError("community conversation not found")
            value = self._community_cases[case_id]
            post_id = source_post_id(request)
            if not (
                value.get("state") == "DRAFT_PENDING"
                and value.get("answerState") == "FAILED"
                and not value.get("draftAnswer")
                and value.get("lastSeenPostId") == post_id
            ):
                raise InvalidStateError("only the current failed community draft can be retried")
            value.update(
                conversationState=conversation_state_for_draft(draft),
                draftAnswer=draft.get("draftAnswer"), answerState=draft.get("answerState"),
                citations=deepcopy(draft.get("citations") or []),
                evidenceLedger=deepcopy(draft.get("evidenceLedger") or {}),
                correlationId=correlation_id, updatedAt=utc_now(),
            )
            responses = self._community_responses.get(case_id) or []
            if responses:
                responses[-1].update(
                    answer=value["draftAnswer"], answerState=value["answerState"],
                    correlationId=correlation_id,
                )
            self._community_events.append({
                "caseId": case_id, "eventType": "FAILED_DRAFT_RETRIED", "actor": "techflow",
                "createdAt": value["updatedAt"],
                "details": {"sourcePostId": post_id, "draftVersion": value["draftVersion"]},
            })
            result = self._remember("retry_failed_community_case", idempotency_key, value)
            result.update(created=False, turnCreated=True)
            return result

    def list_community_turns(self, discussion_id: str) -> list[dict[str, Any]]:
        with self._lock:
            case_id = self._community_by_discussion.get(discussion_id)
            if not case_id:
                return []
            return deepcopy(self._community_turns.get(case_id, []))

    def record_community_turn(
        self, request: dict[str, Any], idempotency_key: str, correlation_id: str
    ) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("record_community_turn", idempotency_key):
                repeated["turnCreated"] = False
                return repeated
            case_id = self._community_by_discussion.get(request["discussionId"])
            if not case_id:
                raise NotFoundError("community conversation not found")
            value = self._community_cases[case_id]
            post_id = source_post_id(request)
            if any(item["sourcePostId"] == post_id for item in self._community_turns.get(case_id, [])):
                result = deepcopy(value)
                result["turnCreated"] = False
                return self._remember("record_community_turn", idempotency_key, result)
            turn = self._append_memory_turn(case_id, request, correlation_id)
            reopened = value.get("conversationState") == "RESOLVED" and turn["role"] == "REQUESTER"
            value.update(
                lastSeenPostId=post_id, contextVersion=value.get("contextVersion", 0) + 1,
                updatedAt=utc_now(),
            )
            if reopened:
                value.update(
                    conversationState="ANALYZING", resolvedPostId=None, resolvedByUserId=None,
                    resolvedAt=None, reopenedAt=value["updatedAt"], knowledgeBasePostId=None,
                    knowledgeBasePostUrl=None, knowledgeBaseSourcePostId=None, knowledgeBaseAnswer=None,
                    knowledgeBaseSolutionSelectedAt=None, knowledgeBaseSolutionSelectedByUserId=None,
                )
            self._community_events.append({
                "caseId": case_id, "eventType": "CONVERSATION_REOPENED" if reopened else "TURN_RECORDED",
                "actor": turn["role"].lower(), "createdAt": value["updatedAt"],
                "details": {"sourcePostId": post_id},
            })
            result = self._remember("record_community_turn", idempotency_key, value)
            result["turnCreated"] = True
            return result

    def sync_community_resolution(
        self, request: dict[str, Any], idempotency_key: str, correlation_id: str
    ) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("sync_community_resolution", idempotency_key):
                return repeated
            case_id = self._community_by_discussion.get(request["discussionId"])
            if not case_id:
                raise NotFoundError("community conversation not found")
            value = self._community_cases[case_id]
            best_post = request.get("bestAnswerPostId")
            best_user = request.get("bestAnswerUserId")
            selected_by_administrator = request.get("bestAnswerSelectedByAdministrator") is True
            requester = value.get("requesterUserId")
            now = utc_now()
            knowledge_post = value.get("knowledgeBasePostId")
            if best_post and knowledge_post and best_post == knowledge_post:
                changed = (
                    value.get("conversationState") != "RESOLVED"
                    or value.get("knowledgeBaseSolutionSelectedAt") is None
                )
                value.update(
                    conversationState="RESOLVED",
                    knowledgeBaseSolutionSelectedAt=request.get("bestAnswerSetAt") or now,
                    knowledgeBaseSolutionSelectedByUserId=best_user,
                    updatedAt=now,
                )
                event_type = "KNOWLEDGE_BASE_SOLUTION_CONFIRMED"
            elif best_post and (best_user == requester or selected_by_administrator):
                changed = value.get("conversationState") != "RESOLVED" or value.get("resolvedPostId") != best_post
                value.update(
                    conversationState="RESOLVED", resolvedPostId=best_post, resolvedByUserId=best_user,
                    resolvedAt=request.get("bestAnswerSetAt") or now,
                    knowledgeBaseSolutionSelectedAt=None,
                    knowledgeBaseSolutionSelectedByUserId=None,
                    updatedAt=now,
                )
                event_type = "RESOLVED_BY_REQUESTER" if best_user == requester else "RESOLVED_BY_ADMINISTRATOR"
            elif best_post:
                changed = value.get("resolvedPostId") != best_post or value.get("conversationState") == "RESOLVED"
                value.update(
                    conversationState="WAITING_RESOLUTION", resolvedPostId=best_post,
                    resolvedByUserId=best_user, resolvedAt=None,
                    knowledgeBaseSolutionSelectedAt=None,
                    knowledgeBaseSolutionSelectedByUserId=None,
                    updatedAt=now,
                )
                event_type = "RESOLUTION_REVIEW_REQUIRED"
            elif value.get("conversationState") == "RESOLVED":
                changed = True
                value.update(
                    conversationState="ANALYZING", resolvedPostId=None, resolvedByUserId=None,
                    resolvedAt=None, reopenedAt=now, knowledgeBasePostId=None,
                    knowledgeBasePostUrl=None, knowledgeBaseSourcePostId=None,
                    knowledgeBaseAnswer=None, knowledgeBaseSolutionSelectedAt=None,
                    knowledgeBaseSolutionSelectedByUserId=None, updatedAt=now,
                )
                event_type = "RESOLUTION_UNSET_REOPENED"
            else:
                changed = False
                event_type = "RESOLUTION_UNCHANGED"
            if changed:
                self._community_events.append({
                    "caseId": case_id, "eventType": event_type, "actor": f"flarum:{best_user or requester or 'unknown'}",
                    "createdAt": now, "details": {
                        "bestAnswerPostId": best_post,
                        "resolutionActorRole": (
                            "REQUESTER" if best_user == requester
                            else "ADMINISTRATOR" if selected_by_administrator
                            else "OTHER"
                        ),
                    },
                })
            result = self._remember("sync_community_resolution", idempotency_key, value)
            result["resolutionChanged"] = changed
            return result

    def get_community_case(self, case_id: UUID) -> dict[str, Any]:
        with self._lock:
            if case_id not in self._community_cases:
                raise NotFoundError("community case not found")
            return deepcopy(self._community_cases[case_id])

    def get_community_case_by_discussion(self, discussion_id: str) -> dict[str, Any]:
        with self._lock:
            case_id = self._community_by_discussion.get(discussion_id)
            if not case_id:
                raise NotFoundError("community case not found")
            return deepcopy(self._community_cases[case_id])

    def resolve_community_case(self, reference: str) -> dict[str, Any]:
        with self._lock:
            if reference in self._community_by_discussion:
                return deepcopy(self._community_cases[self._community_by_discussion[reference]])
            matches = [value for key, value in self._community_cases.items() if str(key).startswith(reference.lower())]
            if len(matches) != 1:
                raise NotFoundError("Community case reference is not unique")
            return deepcopy(matches[0])

    def list_community_cases(self, states: tuple[str, ...] | None = None, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            values = [item for item in self._community_cases.values() if not states or item["state"] in states]
            values.sort(key=lambda item: item["updatedAt"], reverse=True)
            return deepcopy(values[:limit])

    def list_community_case_events(self, case_id: UUID, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            values = [item for item in self._community_events if item["caseId"] == case_id]
            values.sort(key=lambda item: item["createdAt"], reverse=True)
            return deepcopy(values[:limit])

    def decide_community_case(self, case_id: UUID, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("decide_community_case", idempotency_key):
                return repeated
            value = self._community_cases.get(case_id)
            if not value:
                raise NotFoundError("community case not found")
            target_state = "APPROVED" if request["decision"] == "APPROVE" else "REJECTED"
            if value["state"] == target_state and value["draftVersion"] == request["expectedDraftVersion"]:
                edited_answer = request.get("editedAnswer")
                if edited_answer and edited_answer != value.get("draftAnswer"):
                    raise InvalidStateError("draft state or version changed")
                return self._remember("decide_community_case", idempotency_key, value)
            if value["state"] != "DRAFT_PENDING" or value["draftVersion"] != request["expectedDraftVersion"]:
                raise InvalidStateError("draft state or version changed")
            if request["decision"] == "APPROVE" and not (request.get("editedAnswer") or value.get("draftAnswer")):
                raise InvalidStateError("an answer is required for approval")
            value["state"] = target_state
            value["draftAnswer"] = request.get("editedAnswer") or value.get("draftAnswer")
            value["reviewer"] = request["reviewer"]
            value["approvalVersion"] += 1
            if value["state"] == "REJECTED":
                value["conversationState"] = "ANALYZING"
            value["updatedAt"] = utc_now()
            if self._community_responses.get(case_id):
                self._community_responses[case_id][-1].update(
                    state="REJECTED" if value["state"] == "REJECTED" else "DRAFT_PENDING",
                    answer=value["draftAnswer"], reviewer=value["reviewer"],
                )
            self._community_events.append({
                "caseId": case_id, "eventType": value["state"], "actor": request["reviewer"],
                "createdAt": value["updatedAt"],
                "details": {"draftVersion": value["draftVersion"], "note": request.get("note")},
            })
            return self._remember("decide_community_case", idempotency_key, value)

    def attach_community_review(self, case_id: UUID, review: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("attach_community_review", idempotency_key):
                return repeated
            value = self._community_cases.get(case_id)
            if not value:
                raise NotFoundError("community case not found")
            if value.get("reviewPostId") and value["reviewPostId"] != review["postId"]:
                raise ConflictError("community review post already attached")
            value.update(reviewPostId=review["postId"], reviewPostUrl=review["postUrl"], updatedAt=utc_now())
            if self._community_responses.get(case_id):
                self._community_responses[case_id][-1].update(
                    reviewPostId=review["postId"], reviewPostUrl=review["postUrl"],
                )
            self._community_events.append({
                "caseId": case_id, "eventType": "REVIEW_POST_CREATED", "actor": "techflow-assistant",
                "createdAt": value["updatedAt"], "details": deepcopy(review),
            })
            return self._remember("attach_community_review", idempotency_key, value)

    def mark_community_review_approved(self, case_id: UUID, idempotency_key: str) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("approve_community_review", idempotency_key):
                return repeated
            value = self._community_cases.get(case_id)
            if not value or not value.get("reviewPostId"):
                raise NotFoundError("community review post not found")
            if value["state"] == "PUBLISHED":
                return self._remember("approve_community_review", idempotency_key, value)
            if value["state"] != "DRAFT_PENDING":
                raise InvalidStateError("only pending review posts can be approved")
            value.update(
                state="PUBLISHED", reviewer="flarum:moderator", approvalVersion=value["approvalVersion"] + 1,
                publishedPostId=value["reviewPostId"], publishedPostUrl=value["reviewPostUrl"],
                conversationState="WAITING_RESOLUTION", updatedAt=utc_now(),
            )
            if self._community_responses.get(case_id):
                self._community_responses[case_id][-1].update(
                    state="PUBLISHED", reviewer="flarum:moderator", publishedAt=value["updatedAt"],
                )
            self._community_events.append({
                "caseId": case_id, "eventType": "PUBLISHED", "actor": "flarum:moderator",
                "createdAt": value["updatedAt"], "details": {"approvalSurface": "FLARUM_APPROVAL"},
            })
            return self._remember("approve_community_review", idempotency_key, value)

    def mark_community_review_missing(self, case_id: UUID, idempotency_key: str) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("missing_community_review", idempotency_key):
                return repeated
            value = self._community_cases.get(case_id)
            if not value:
                raise NotFoundError("community case not found")
            if value["state"] != "DRAFT_PENDING":
                return self._remember("missing_community_review", idempotency_key, value)
            value.update(state="REJECTED", conversationState="ANALYZING", reviewer="techflow:reconcile", updatedAt=utc_now())
            if self._community_responses.get(case_id):
                self._community_responses[case_id][-1].update(state="REJECTED", reviewer="techflow:reconcile")
            self._community_events.append({
                "caseId": case_id, "eventType": "REVIEW_POST_MISSING", "actor": "techflow:reconcile",
                "createdAt": value["updatedAt"], "details": {"reviewPostId": value.get("reviewPostId")},
            })
            return self._remember("missing_community_review", idempotency_key, value)

    def mark_community_published(self, case_id: UUID, publication: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("publish_community_case", idempotency_key):
                return repeated
            value = self._community_cases.get(case_id)
            if not value:
                raise NotFoundError("community case not found")
            if value["state"] != "APPROVED":
                raise InvalidStateError("only approved drafts can be published")
            value.update(state="PUBLISHED", publishedPostId=publication["postId"],
                         publishedPostUrl=publication["postUrl"], conversationState="WAITING_RESOLUTION",
                         updatedAt=utc_now())
            self._community_events.append({
                "caseId": case_id, "eventType": "PUBLISHED", "actor": "techflow",
                "createdAt": value["updatedAt"], "details": deepcopy(publication),
            })
            return self._remember("publish_community_case", idempotency_key, value)

    def mark_community_auto_published(
        self, case_id: UUID, answer: str, publication: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("auto_publish_community_case", idempotency_key):
                return repeated
            value = self._community_cases.get(case_id)
            if not value:
                raise NotFoundError("community case not found")
            if value["state"] == "PUBLISHED" and value.get("publishedPostId") == publication["postId"]:
                return self._remember("auto_publish_community_case", idempotency_key, value)
            if (
                value["state"] not in {"DRAFT_PENDING", "PUBLISHED"}
                or value.get("reviewer") == "techflow:auto"
                or not answer.strip()
            ):
                raise InvalidStateError("only generated community answers can be auto-published")
            now = utc_now()
            value.update(
                state="PUBLISHED", reviewer="techflow:auto", publishedPostId=publication["postId"],
                publishedPostUrl=publication["postUrl"], draftAnswer=answer, conversationState="WAITING_RESOLUTION",
                updatedAt=now,
            )
            if self._community_responses.get(case_id):
                self._community_responses[case_id][-1].update(
                    state="PUBLISHED", answer=answer, reviewer="techflow:auto", publishedAt=now,
                )
            self._community_events.append({
                "caseId": case_id, "eventType": "AUTO_PUBLISHED", "actor": "techflow-assistant",
                "createdAt": now, "details": deepcopy(publication),
            })
            return self._remember("auto_publish_community_case", idempotency_key, value)

    def mark_community_knowledge_published(
        self, case_id: UUID, answer: str, publication: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("publish_community_knowledge", idempotency_key):
                return repeated
            value = self._community_cases.get(case_id)
            if not value:
                raise NotFoundError("community case not found")
            if value.get("conversationState") != "RESOLVED" or not value.get("resolvedPostId"):
                raise InvalidStateError("knowledge base publication requires a requester or administrator resolution")
            now = utc_now()
            value.update(
                knowledgeBasePostId=publication["postId"], knowledgeBasePostUrl=publication["postUrl"],
                knowledgeBaseSourcePostId=value["resolvedPostId"], knowledgeBaseAnswer=answer,
                knowledgeBaseVersion=value.get("knowledgeBaseVersion", 0) + 1,
                knowledgeBasePublishedAt=now, knowledgeBaseSolutionSelectedAt=None,
                knowledgeBaseSolutionSelectedByUserId=None, updatedAt=now,
            )
            self._community_events.append({
                "caseId": case_id, "eventType": "KNOWLEDGE_BASE_PUBLISHED", "actor": "techflow-assistant",
                "createdAt": now,
                "details": {**deepcopy(publication), "resolvedPostId": value["resolvedPostId"]},
            })
            return self._remember("publish_community_knowledge", idempotency_key, value)

    def mark_community_knowledge_solution_selected(
        self, case_id: UUID, selection: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        with self._lock:
            if repeated := self._repeat("select_community_knowledge_solution", idempotency_key):
                return repeated
            value = self._community_cases.get(case_id)
            if not value:
                raise NotFoundError("community case not found")
            if value.get("conversationState") != "RESOLVED" or not value.get("knowledgeBasePostId"):
                raise InvalidStateError("knowledge base solution selection requires a published knowledge base")
            if str(selection.get("postId")) != str(value["knowledgeBasePostId"]):
                raise ConflictError("selected solution does not match the knowledge base post")
            now = utc_now()
            value.update(
                knowledgeBaseSolutionSelectedAt=now,
                knowledgeBaseSolutionSelectedByUserId=selection.get("selectedByUserId"),
                updatedAt=now,
            )
            self._community_events.append({
                "caseId": case_id, "eventType": "KNOWLEDGE_BASE_SOLUTION_SELECTED",
                "actor": "techflow-integration", "createdAt": now, "details": deepcopy(selection),
            })
            return self._remember("select_community_knowledge_solution", idempotency_key, value)

    def upsert_chat_reviewer(self, user_id: str, username: str) -> dict[str, Any]:
        with self._lock:
            value = {"userId": user_id, "username": username, "lastSeenAt": utc_now()}
            self._chat_reviewers[user_id] = value
            return deepcopy(value)

    def list_chat_reviewers(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(sorted(self._chat_reviewers.values(), key=lambda item: item["username"]))
