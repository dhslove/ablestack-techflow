"""PostgreSQL implementation of the Issue #41 persistence boundary."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from .provider import PROVIDER_PROFILES
from .conversation import conversation_state_for_draft, source_post_id

from .config import Settings
from .indexing import build_index_bundle, reciprocal_rank_fusion
from .source_registry import SOURCE_PROFILES, get_profile, list_profiles, validate_candidate_contract
from .versioned_assist import implementation_identifiers
from .store import (
    KB_SOLUTION_CONFIRMED_EVENT,
    ConflictError,
    InvalidBoundaryError,
    InvalidStateError,
    NotFoundError,
)


LOGGER = logging.getLogger("techflow.ai_gateway.postgres_store")


class PostgresStore:
    def __init__(self, settings: Settings) -> None:
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # pragma: no cover - exercised by container validation
            raise RuntimeError("psycopg[binary,pool] is required for postgres mode") from exc
        self._pool = ConnectionPool(
            conninfo=settings.database_dsn or "",
            min_size=settings.database_pool_min,
            max_size=settings.database_pool_max,
            open=False,
            kwargs={"row_factory": dict_row, "application_name": "techflow-ai-gateway"},
            check=ConnectionPool.check_connection,
            timeout=5,
        )
        self._pool.open(wait=True, timeout=10)
        self._provider_mode = settings.provider_mode

    def close(self) -> None:
        self._pool.close()

    def health(self) -> dict[str, str]:
        try:
            with self._pool.connection(timeout=3) as connection:
                row = connection.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') AS vector_ready"
                ).fetchone()
            return {
                "process": "ready",
                "database": "ready",
                "vector": "ready" if row and row["vector_ready"] else "missing",
                "provider": self._provider_mode,
            }
        except Exception:
            return {"process": "ready", "database": "unavailable", "vector": "unknown", "provider": self._provider_mode}

    @staticmethod
    def _source_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "sourceId": row["source_id"],
            "sourceVersionId": row["source_version_id"],
            "sourceProfileId": row["source_profile_id"],
            "repository": row["repository"],
            "branch": row["branch"],
            "commit": row["commit_sha"],
            "sourceKind": row["source_kind"],
            "classification": row["classification"],
            "licenseSpdx": row["license_spdx"],
            "owner": row.get("owner"),
            "retentionPolicy": row.get("retention_policy"),
            "initialReviewer": row.get("initial_reviewer"),
            "treeSha": row.get("tree_sha"),
            "snapshotHash": row.get("snapshot_hash"),
            "state": row["version_state"],
            "detectedBy": row.get("detected_by"),
            "scannedBy": row.get("scanned_by"),
            "candidateFileCount": row.get("candidate_file_count"),
            "eligibleFileCount": row.get("eligible_file_count"),
            "excludedFileCount": row.get("excluded_file_count"),
            "blockingViolationCount": row.get("blocking_violation_count"),
            "indexedFileCount": row.get("indexed_file_count"),
            "quarantineExclusionsAccepted": row.get("quarantine_exclusions_accepted", False),
            "createdAt": row["created_at"],
            "scannedAt": row.get("scanned_at"),
            "approvedAt": row["approved_at"],
            "approvedBy": row["approved_by"],
        }

    @staticmethod
    def _job_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "jobId": row.get("job_id", row.get("id")),
            "jobType": row["job_type"],
            "sourceId": row["source_id"],
            "sourceVersionId": row["source_version_id"],
            "state": row["state"],
            "failureClass": row["failure_class"],
            "errorCode": row["error_code"],
            "requestedBy": row["requested_by"],
            "correlationId": row.get("correlation_id", "legacy"),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "startedAt": row.get("started_at"),
            "completedAt": row.get("completed_at"),
            "attempt": row.get("attempt", 0),
            "metrics": row.get("metrics", {}),
        }

    def _source_by_version(self, connection: Any, version_id: UUID) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT s.id AS source_id, v.id AS source_version_id, s.source_profile_id,
                   s.repository, s.branch, v.commit_sha, s.source_kind, s.classification,
                   s.license_spdx, s.owner, s.retention_policy, s.initial_reviewer,
                   v.tree_sha, v.snapshot_hash, v.state AS version_state, v.detected_by, v.scanned_by,
                   v.candidate_file_count, v.eligible_file_count, v.excluded_file_count,
                   v.blocking_violation_count, v.indexed_file_count, v.quarantine_exclusions_accepted,
                   v.created_at, v.scanned_at,
                   v.approved_at, v.approved_by
            FROM rag_source s JOIN rag_source_version v ON v.source_id = s.id
            WHERE v.id = %s
            """,
            (version_id,),
        ).fetchone()
        if not row:
            raise NotFoundError("source version not found")
        return self._source_payload(row)

    def list_source_profiles(self) -> list[dict[str, Any]]:
        profile_ids = list(SOURCE_PROFILES)
        with self._pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT source_profile_id, owner, repository, branch, source_kind, classification,
                       license_spdx, retention_policy, initial_reviewer
                FROM rag_source WHERE source_profile_id = ANY(%s) ORDER BY source_profile_id
                """,
                (profile_ids,),
            ).fetchall()
        if len(rows) != 9:
            raise InvalidBoundaryError("database source registry is incomplete")
        return [
            {
                "sourceProfileId": row["source_profile_id"], "owner": row["owner"],
                "repository": row["repository"], "branch": row["branch"], "sourceKind": row["source_kind"],
                "classification": row["classification"], "licenseSpdx": row["license_spdx"],
                "retentionPolicy": row["retention_policy"], "initialReviewer": row["initial_reviewer"],
                "docsRoot": next(item["docsRoot"] for item in list_profiles() if item["sourceProfileId"] == row["source_profile_id"]),
            }
            for row in rows
        ]

    @staticmethod
    def _mirror_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "repository": row["repository"],
            "mirrorKey": row["mirror_key"],
            "state": row["effective_state"],
            "syncPolicy": row["sync_policy"],
            "staleAfterSeconds": row["stale_after_seconds"],
            "lastAttemptAt": row["last_attempt_at"],
            "lastSuccessAt": row["last_success_at"],
            "lastHeadCommit": row["last_head_commit"],
            "lastErrorCode": row["last_error_code"],
            "consecutiveFailures": row["consecutive_failures"],
            "lastDurationMs": row["last_duration_ms"],
        }

    def list_source_mirrors(self) -> list[dict[str, Any]]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT repository, mirror_key,
                       CASE
                           WHEN last_success_at IS NOT NULL
                            AND now() - last_success_at > make_interval(secs => stale_after_seconds)
                           THEN 'STALE'
                           ELSE state
                       END AS effective_state,
                       sync_policy, stale_after_seconds, last_attempt_at, last_success_at,
                       last_head_commit, last_error_code, consecutive_failures, last_duration_ms
                FROM rag_source_mirror ORDER BY repository
                """
            ).fetchall()
        if len(rows) != 7:
            raise InvalidBoundaryError("database source mirror registry is incomplete")
        return [self._mirror_payload(row) for row in rows]

    def record_mirror_sync(
        self, repository: str, commit: str | None, success: bool, error_code: str | None, duration_ms: int
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            if success:
                row = connection.execute(
                    """
                    UPDATE rag_source_mirror SET
                        state='HEALTHY', last_attempt_at=now(), last_success_at=now(),
                        last_head_commit=%s, last_error_code=NULL, consecutive_failures=0,
                        last_duration_ms=%s, updated_at=now()
                    WHERE repository=%s
                    RETURNING repository, mirror_key, state AS effective_state, sync_policy,
                              stale_after_seconds, last_attempt_at, last_success_at, last_head_commit,
                              last_error_code, consecutive_failures, last_duration_ms
                    """,
                    (commit, max(0, duration_ms), repository),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    UPDATE rag_source_mirror SET
                        state='DEGRADED', last_attempt_at=now(), last_error_code=%s,
                        consecutive_failures=consecutive_failures+1, last_duration_ms=%s, updated_at=now()
                    WHERE repository=%s
                    RETURNING repository, mirror_key, state AS effective_state, sync_policy,
                              stale_after_seconds, last_attempt_at, last_success_at, last_head_commit,
                              last_error_code, consecutive_failures, last_duration_ms
                    """,
                    (error_code or "SOURCE_FETCH_FAILED", max(0, duration_ms), repository),
                ).fetchone()
        if not row:
            raise InvalidBoundaryError("repository is not registered for mirroring")
        return self._mirror_payload(row)

    def register_candidate(
        self, profile_id: str, commit: str, detected_by: str, idempotency_key: str
    ) -> dict[str, Any]:
        profile = get_profile(profile_id)
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT id FROM rag_source_version WHERE create_idempotency_key=%s", (idempotency_key,)
            ).fetchone()
            if repeated:
                return self._source_by_version(connection, repeated["id"])
            source = connection.execute(
                "SELECT id, repository, branch, source_kind, classification, initial_reviewer FROM rag_source WHERE source_profile_id=%s FOR UPDATE",
                (profile_id,),
            ).fetchone()
            if not source:
                raise NotFoundError("source profile is not registered")
            if (
                source["repository"], source["branch"], source["source_kind"], source["classification"], source["initial_reviewer"]
            ) != (profile.repository, profile.branch, profile.source_kind, profile.classification, profile.initial_reviewer):
                raise InvalidBoundaryError("database source profile differs from immutable registry")
            existing = connection.execute(
                "SELECT id FROM rag_source_version WHERE source_id=%s AND commit_sha=%s", (source["id"], commit)
            ).fetchone()
            if existing:
                return self._source_by_version(connection, existing["id"])
            version_id = uuid4()
            connection.execute(
                """
                INSERT INTO rag_source_version
                    (id, source_id, commit_sha, state, create_idempotency_key, detected_by)
                VALUES (%s, %s, %s, 'REGISTERED', %s, %s)
                """,
                (version_id, source["id"], commit, idempotency_key, detected_by),
            )
            connection.execute("UPDATE rag_source SET state='REGISTERED', updated_at=now() WHERE id=%s", (source["id"],))
            return self._source_by_version(connection, version_id)

    def create_source(self, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        profile = validate_candidate_contract(request)
        return self.register_candidate(profile.profile_id, request["commit"], "manual-api", idempotency_key)

    def get_source(self, source_id: UUID) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute(
                """
                SELECT s.id AS source_id, v.id AS source_version_id, s.source_profile_id,
                       s.repository, s.branch, v.commit_sha, s.source_kind, s.classification,
                       s.license_spdx, s.owner, s.retention_policy, s.initial_reviewer,
                       v.tree_sha, v.snapshot_hash, v.state AS version_state, v.detected_by, v.scanned_by,
                       v.candidate_file_count, v.eligible_file_count, v.excluded_file_count,
                       v.blocking_violation_count, v.indexed_file_count, v.quarantine_exclusions_accepted,
                       v.created_at, v.scanned_at,
                       v.approved_at, v.approved_by
                FROM rag_source s JOIN rag_source_version v ON v.source_id = s.id
                WHERE s.id = %s ORDER BY v.created_at DESC LIMIT 1
                """,
                (source_id,),
            ).fetchone()
            if not row:
                raise NotFoundError("source not found")
            return self._source_payload(row)

    def get_source_version(self, version_id: UUID) -> dict[str, Any]:
        with self._pool.connection() as connection:
            return self._source_by_version(connection, version_id)

    def record_scan(
        self, version_id: UUID, report: dict[str, Any], scanned_by: str, idempotency_key: str
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT id FROM rag_source_version WHERE scan_idempotency_key=%s", (idempotency_key,)
            ).fetchone()
            if repeated:
                return self._source_by_version(connection, repeated["id"])
            version = connection.execute(
                """
                SELECT v.id, v.source_id, v.commit_sha, v.state, v.snapshot_hash, s.repository
                FROM rag_source_version v JOIN rag_source s ON s.id=v.source_id
                WHERE v.id=%s FOR UPDATE
                """,
                (version_id,),
            ).fetchone()
            if not version:
                raise NotFoundError("source version not found")
            if version["state"] != "REGISTERED" and version["snapshot_hash"] == report["snapshotHash"]:
                return self._source_by_version(connection, version_id)
            if version["state"] != "REGISTERED":
                raise InvalidStateError("only registered candidates can be scanned")
            if version["commit_sha"] != report["commit"]:
                raise ConflictError("scan commit differs from registered candidate")
            if connection.execute(
                "SELECT 1 FROM rag_source_file WHERE source_version_id=%s", (version_id,)
            ).fetchone():
                raise ConflictError("source version scan inventory already exists")
            for raw_file in report["files"]:
                content = raw_file.get("content")
                blob_id = None
                if raw_file["decision"] == "ELIGIBLE":
                    if not raw_file.get("blob_sha") or content is None:
                        raise InvalidBoundaryError("eligible file is missing verified blob content")
                    existing_blob = connection.execute(
                        "SELECT id, content_hash FROM rag_source_blob WHERE repository=%s AND blob_sha=%s",
                        (version["repository"], raw_file["blob_sha"]),
                    ).fetchone()
                    if existing_blob and existing_blob["content_hash"] != raw_file["content_hash"]:
                        raise ConflictError("blob SHA content hash mismatch")
                    if existing_blob:
                        blob_id = existing_blob["id"]
                    else:
                        blob_id = uuid4()
                        connection.execute(
                            """
                            INSERT INTO rag_source_blob
                                (id, repository, blob_sha, content_hash, size_bytes, encoding, classification, content)
                            VALUES (%s, %s, %s, %s, %s, 'utf-8', 'D0', %s)
                            """,
                            (
                                blob_id, version["repository"], raw_file["blob_sha"], raw_file["content_hash"],
                                raw_file["size_bytes"], content,
                            ),
                        )
                connection.execute(
                    """
                    INSERT INTO rag_source_file
                        (id, source_version_id, path, path_hash, blob_sha, source_blob_id, content_hash,
                         size_bytes, source_kind, encoding, decision, rule_ids)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        uuid4(), version_id, raw_file["path"], raw_file["path_hash"], raw_file.get("blob_sha"),
                        blob_id, raw_file.get("content_hash"), raw_file.get("size_bytes"), raw_file.get("source_kind"),
                        raw_file.get("encoding"), raw_file["decision"], list(raw_file.get("rule_ids") or ()),
                    ),
                )
                severity = "BLOCKING" if raw_file["decision"] == "QUARANTINED" else "INFO"
                for rule_id in raw_file.get("rule_ids") or ():
                    connection.execute(
                        """
                        INSERT INTO rag_source_scan_finding (id, source_version_id, path_hash, rule_id, severity)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (uuid4(), version_id, raw_file["path_hash"], rule_id, severity),
                    )
            connection.execute(
                """
                UPDATE rag_source_version SET
                    state='QUARANTINED', tree_sha=%s, snapshot_hash=%s, scanned_by=%s,
                    scan_idempotency_key=%s, scanned_at=now(),
                    candidate_file_count=%s, eligible_file_count=%s, excluded_file_count=%s,
                    blocking_violation_count=%s
                WHERE id=%s
                """,
                (
                    report["treeSha"], report["snapshotHash"], scanned_by, idempotency_key, report["candidateFileCount"],
                    report["eligibleFileCount"], report["excludedFileCount"], report["blockingViolationCount"], version_id,
                ),
            )
            connection.execute(
                "UPDATE rag_source SET state='QUARANTINED', updated_at=now() WHERE id=%s", (version["source_id"],)
            )
            return self._source_by_version(connection, version_id)

    def list_source_files(self, version_id: UUID) -> list[dict[str, Any]]:
        with self._pool.connection() as connection:
            if not connection.execute("SELECT 1 FROM rag_source_version WHERE id=%s", (version_id,)).fetchone():
                raise NotFoundError("source version not found")
            rows = connection.execute(
                """
                SELECT path, path_hash, blob_sha, content_hash, size_bytes, source_kind, encoding, decision, rule_ids
                FROM rag_source_file WHERE source_version_id=%s ORDER BY path
                """,
                (version_id,),
            ).fetchall()
        return [
            {
                "path": row["path"], "pathHash": row["path_hash"], "blobSha": row["blob_sha"],
                "contentHash": row["content_hash"], "sizeBytes": row["size_bytes"], "sourceKind": row["source_kind"],
                "encoding": row["encoding"], "decision": row["decision"], "ruleIds": row["rule_ids"],
            }
            for row in rows
        ]

    def approve_version(self, version_id: UUID, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT id FROM rag_source_version WHERE approval_idempotency_key=%s", (idempotency_key,)
            ).fetchone()
            if repeated:
                return self._source_by_version(connection, repeated["id"])
            row = connection.execute(
                """
                SELECT v.id, v.source_id, v.commit_sha, v.state, v.blocking_violation_count,
                       s.source_profile_id, s.initial_reviewer
                FROM rag_source_version v JOIN rag_source s ON s.id=v.source_id
                WHERE v.id=%s FOR UPDATE
                """,
                (version_id,),
            ).fetchone()
            if not row:
                raise NotFoundError("source version not found")
            if row["state"] != "QUARANTINED":
                raise InvalidStateError("only quarantined source versions can be approved")
            if row["blocking_violation_count"] != 0 and not request.get("acceptQuarantineExclusions", False):
                raise InvalidStateError("blocking quarantine exclusions require explicit reviewer acceptance")
            if request.get("expectedCommit") and request["expectedCommit"] != row["commit_sha"]:
                raise ConflictError("approval commit differs from scanned candidate")
            if request["approvedBy"] != row["initial_reviewer"]:
                raise InvalidBoundaryError("reviewer is not authorized for this source profile")
            connection.execute(
                """
                UPDATE rag_source_version SET state='APPROVED', approved_at=now(), approved_by=%s,
                    approval_note=%s, approval_idempotency_key=%s, quarantine_exclusions_accepted=%s WHERE id=%s
                """,
                (
                    request["approvedBy"], request.get("decisionNote"), idempotency_key,
                    request.get("acceptQuarantineExclusions", False), version_id,
                ),
            )
            connection.execute("UPDATE rag_source SET state='APPROVED', updated_at=now() WHERE id=%s", (row["source_id"],))
            return self._source_by_version(connection, version_id)

    def approve_source(self, source_id: UUID, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT id FROM rag_source_version WHERE source_id = %s ORDER BY created_at DESC LIMIT 1",
                (source_id,),
            ).fetchone()
            if not row:
                raise NotFoundError("source not found")
            version_id = row["id"]
        return self.approve_version(version_id, request, idempotency_key)

    def create_compatibility_set(self, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT id, name, product, product_version, state, created_at FROM rag_compatibility_set WHERE idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if repeated:
                members = connection.execute(
                    "SELECT source_version_id, required FROM rag_compatibility_set_source WHERE compatibility_set_id=%s ORDER BY source_version_id",
                    (repeated["id"],),
                ).fetchall()
                return self._compatibility_payload(repeated, members)
            member_ids = [UUID(str(member["sourceVersionId"])) for member in request["members"]]
            active = connection.execute(
                "SELECT id FROM rag_source_version WHERE id = ANY(%s) AND state='ACTIVE' AND approved_at IS NOT NULL",
                (member_ids,),
            ).fetchall()
            if {row["id"] for row in active} != set(member_ids):
                raise InvalidStateError("compatibility members must be active approved source versions")
            set_id = uuid4()
            row = connection.execute(
                """
                INSERT INTO rag_compatibility_set (id, name, product, product_version, state, idempotency_key)
                VALUES (%s, %s, %s, %s, 'APPROVED', %s)
                RETURNING id, name, product, product_version, state, created_at
                """,
                (set_id, request["name"], request["product"], request["productVersion"], idempotency_key),
            ).fetchone()
            for member in request["members"]:
                connection.execute(
                    "INSERT INTO rag_compatibility_set_source (compatibility_set_id, source_version_id, required) VALUES (%s, %s, %s)",
                    (set_id, member["sourceVersionId"], member["required"]),
                )
            return self._compatibility_payload(row, request["members"])

    def resolve_compatibility_set(self, compatibility_set_id: UUID | None, product_version: str | None) -> dict[str, Any] | None:
        if not compatibility_set_id and not product_version:
            return None
        with self._pool.connection() as connection:
            if compatibility_set_id:
                row = connection.execute(
                    "SELECT id, name, product, product_version, state, created_at FROM rag_compatibility_set WHERE id=%s AND state='APPROVED'",
                    (compatibility_set_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT id, name, product, product_version, state, created_at FROM rag_compatibility_set WHERE product='ABLESTACK' AND product_version=%s AND state='APPROVED' ORDER BY created_at DESC LIMIT 1",
                    (product_version,),
                ).fetchone()
            if not row:
                return None
            members = connection.execute(
                """SELECT css.source_version_id, css.required, s.source_profile_id
                   FROM rag_compatibility_set_source css
                   JOIN rag_source_version v ON v.id=css.source_version_id
                   JOIN rag_source s ON s.id=v.source_id
                   WHERE css.compatibility_set_id=%s ORDER BY s.source_profile_id""",
                (row["id"],),
            ).fetchall()
            return {**self._compatibility_payload(row, members), "sourceProfileIds": [item["source_profile_id"] for item in members]}

    @staticmethod
    def _compatibility_payload(row: dict[str, Any], members: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "compatibilitySetId": row["id"],
            "name": row["name"],
            "product": row["product"],
            "productVersion": row["product_version"],
            "state": row["state"],
            "createdAt": row["created_at"],
            "members": [
                {
                    "sourceVersionId": member.get("source_version_id", member.get("sourceVersionId")),
                    "required": member["required"],
                }
                for member in members
            ],
        }

    def create_ingestion(
        self, source_id: UUID, request: dict[str, Any], idempotency_key: str, correlation_id: str = "legacy"
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT * FROM rag_ingestion_job WHERE idempotency_key=%s", (idempotency_key,)
            ).fetchone()
            if repeated:
                return self._job_payload(repeated)
            version = connection.execute(
                """SELECT id, state FROM rag_source_version
                   WHERE source_id=%s AND state IN ('APPROVED', 'ACTIVE')
                   ORDER BY CASE state WHEN 'APPROVED' THEN 0 ELSE 1 END, created_at DESC
                   LIMIT 1 FOR UPDATE""",
                (source_id,),
            ).fetchone()
            if not version:
                raise InvalidStateError("source must be approved or active before indexing")
            job_type = "REINDEX" if version["state"] == "ACTIVE" else "INGESTION"
            if job_type == "INGESTION":
                connection.execute("UPDATE rag_source_version SET state='INDEXING' WHERE id=%s", (version["id"],))
                connection.execute("UPDATE rag_source SET state='INDEXING', updated_at=now() WHERE id=%s", (source_id,))
            row = connection.execute(
                """
                INSERT INTO rag_ingestion_job
                    (id, job_type, source_id, source_version_id, state, requested_by,
                     idempotency_key, correlation_id)
                VALUES (%s, %s, %s, %s, 'PENDING', %s, %s, %s)
                RETURNING *
                """,
                (uuid4(), job_type, source_id, version["id"], request["requestedBy"], idempotency_key, correlation_id),
            ).fetchone()
            return self._job_payload(row)

    def complete_job(self, job_id: UUID, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT * FROM rag_ingestion_job WHERE completion_idempotency_key=%s", (idempotency_key,)
            ).fetchone()
            if repeated:
                return self._job_payload(repeated)
            job = connection.execute(
                "SELECT * FROM rag_ingestion_job WHERE id=%s FOR UPDATE", (job_id,)
            ).fetchone()
            if not job:
                raise NotFoundError("job not found")
            if job["job_type"] != "INGESTION" or job["state"] not in {"PENDING", "RUNNING"}:
                raise InvalidStateError("job cannot complete indexing")
            version = connection.execute(
                "SELECT id, source_id, state, eligible_file_count FROM rag_source_version WHERE id=%s FOR UPDATE",
                (job["source_version_id"],),
            ).fetchone()
            if not version or version["state"] != "INDEXING":
                raise InvalidStateError("source version is not indexing")
            if request["succeeded"]:
                if request["indexedFileCount"] != version["eligible_file_count"]:
                    raise ConflictError("partial indexing cannot activate a source version")
                connection.execute(
                    "UPDATE rag_source_version SET state='WITHDRAWN' WHERE source_id=%s AND state='ACTIVE' AND id<>%s",
                    (version["source_id"], version["id"]),
                )
                connection.execute(
                    "UPDATE rag_source_version SET state='ACTIVE', indexed_file_count=%s WHERE id=%s",
                    (request["indexedFileCount"], version["id"]),
                )
                connection.execute("UPDATE rag_source SET state='ACTIVE', updated_at=now() WHERE id=%s", (version["source_id"],))
                updated = connection.execute(
                    """
                    UPDATE rag_ingestion_job SET state='SUCCEEDED', failure_class=NULL, error_code=NULL,
                        completion_idempotency_key=%s, updated_at=now() WHERE id=%s RETURNING *
                    """,
                    (idempotency_key, job_id),
                ).fetchone()
            else:
                connection.execute("UPDATE rag_source_version SET state='APPROVED' WHERE id=%s", (version["id"],))
                connection.execute("UPDATE rag_source SET state='APPROVED', updated_at=now() WHERE id=%s", (version["source_id"],))
                updated = connection.execute(
                    """
                    UPDATE rag_ingestion_job SET state='FAILED', failure_class='TERMINAL', error_code=%s,
                        completion_idempotency_key=%s, updated_at=now() WHERE id=%s RETURNING *
                    """,
                    (request["errorCode"], idempotency_key, job_id),
                ).fetchone()
            return self._job_payload(updated)

    def withdraw_source(
        self, source_id: UUID, idempotency_key: str, correlation_id: str = "legacy"
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT * FROM rag_ingestion_job WHERE idempotency_key=%s", (idempotency_key,)
            ).fetchone()
            if repeated:
                return self._job_payload(repeated)
            version = connection.execute(
                "SELECT id FROM rag_source_version WHERE source_id=%s ORDER BY created_at DESC LIMIT 1 FOR UPDATE",
                (source_id,),
            ).fetchone()
            if not version:
                raise NotFoundError("source not found")
            connection.execute("UPDATE rag_source SET state='WITHDRAWN', updated_at=now() WHERE id=%s", (source_id,))
            connection.execute("UPDATE rag_source_version SET state='WITHDRAWN' WHERE source_id=%s", (source_id,))
            connection.execute(
                "UPDATE rag_chunk SET active=false WHERE source_version_id IN (SELECT id FROM rag_source_version WHERE source_id=%s)",
                (source_id,),
            )
            connection.execute(
                "UPDATE rag_code_symbol SET active=false WHERE source_version_id IN (SELECT id FROM rag_source_version WHERE source_id=%s)",
                (source_id,),
            )
            connection.execute(
                "UPDATE rag_code_relation SET active=false WHERE source_version_id IN (SELECT id FROM rag_source_version WHERE source_id=%s)",
                (source_id,),
            )
            job_id = uuid4()
            row = connection.execute(
                """
                INSERT INTO rag_ingestion_job
                    (id, job_type, source_id, source_version_id, state, requested_by,
                     idempotency_key, correlation_id)
                VALUES (%s, 'DELETION', %s, %s, 'PENDING', 'system', %s, %s)
                RETURNING *
                """,
                (job_id, source_id, version["id"], idempotency_key, correlation_id),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO rag_deletion_ledger
                    (id, source_id, source_version_id, job_id, state, excluded_at, policy_deadline_at)
                VALUES (%s, %s, %s, %s, 'PENDING', now(), now() + interval '7 days')
                """,
                (uuid4(), source_id, version["id"], job_id),
            )
            return self._job_payload(row)

    def get_job(self, job_id: UUID) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute("SELECT * FROM rag_ingestion_job WHERE id=%s", (job_id,)).fetchone()
            if not row:
                raise NotFoundError("job not found")
            return self._job_payload(row)

    @staticmethod
    def _vector_literal(values: tuple[float, ...]) -> str:
        return "[" + ",".join(format(value, ".10g") for value in values) + "]"

    def _record_embedding_call(
        self, connection: Any, result: Any, correlation_id: str,
        *, query_id: UUID | None = None, ingestion_job_id: UUID | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO rag_provider_call
                (id, query_id, ingestion_job_id, provider, surface, provider_profile_id, profile_version,
                 requested_model_id, returned_model_id, embedding_dimension, provider_request_id,
                 input_tokens, latency_ms, status, correlation_id)
            VALUES (%s, %s, %s, %s, 'embeddings-api', 'OPENAI_EMBEDDING_V1', 1,
                    %s, %s, 3072, %s, %s, %s, 'SUCCEEDED', %s)
            """,
            (uuid4(), query_id, ingestion_job_id, result.provider, result.requested_model,
             result.returned_model, result.request_id, result.input_tokens, result.latency_ms, correlation_id),
        )

    def run_job(
        self, job_id: UUID, request: dict[str, Any], idempotency_key: str,
        correlation_id: str, adapter: Any, batch_size: int,
    ) -> dict[str, Any]:
        from psycopg.types.json import Jsonb

        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT * FROM rag_ingestion_job WHERE execution_idempotency_key=%s", (idempotency_key,)
            ).fetchone()
            if repeated:
                return self._job_payload(repeated)
            job = connection.execute("SELECT * FROM rag_ingestion_job WHERE id=%s FOR UPDATE", (job_id,)).fetchone()
            if not job:
                raise NotFoundError("job not found")
            if job["state"] != "PENDING":
                raise InvalidStateError("only pending jobs can run")
            job = connection.execute(
                """UPDATE rag_ingestion_job SET state='RUNNING', attempt=attempt+1, started_at=now(),
                   execution_idempotency_key=%s, updated_at=now() WHERE id=%s RETURNING *""",
                (idempotency_key, job_id),
            ).fetchone()

        if job["job_type"] == "DELETION":
            with self._pool.connection() as connection:
                counts = connection.execute(
                    """
                    SELECT
                      (SELECT count(*) FROM rag_code_relation WHERE source_version_id IN
                        (SELECT id FROM rag_source_version WHERE source_id=%s)) AS relations,
                      (SELECT count(*) FROM rag_code_symbol WHERE source_version_id IN
                        (SELECT id FROM rag_source_version WHERE source_id=%s)) AS symbols,
                      (SELECT count(*) FROM rag_chunk_embedding e JOIN rag_chunk c ON c.id=e.chunk_id
                        WHERE c.source_version_id IN (SELECT id FROM rag_source_version WHERE source_id=%s)) AS embeddings,
                      (SELECT count(*) FROM rag_chunk WHERE source_version_id IN
                        (SELECT id FROM rag_source_version WHERE source_id=%s)) AS chunks
                    """, (job["source_id"],) * 4,
                ).fetchone()
                connection.execute("DELETE FROM rag_code_relation WHERE source_version_id IN (SELECT id FROM rag_source_version WHERE source_id=%s)", (job["source_id"],))
                connection.execute("DELETE FROM rag_code_symbol WHERE source_version_id IN (SELECT id FROM rag_source_version WHERE source_id=%s)", (job["source_id"],))
                connection.execute("DELETE FROM rag_chunk WHERE source_version_id IN (SELECT id FROM rag_source_version WHERE source_id=%s)", (job["source_id"],))
                metrics = {"relationsDeleted": counts["relations"], "symbolsDeleted": counts["symbols"],
                           "embeddingsDeleted": counts["embeddings"], "chunksDeleted": counts["chunks"]}
                connection.execute(
                    """UPDATE rag_deletion_ledger SET state='SUCCEEDED', relations_deleted=%s, symbols_deleted=%s,
                       embeddings_deleted=%s, chunks_deleted=%s, completed_at=now() WHERE job_id=%s""",
                    (counts["relations"], counts["symbols"], counts["embeddings"], counts["chunks"], job_id),
                )
                updated = connection.execute(
                    "UPDATE rag_ingestion_job SET state='SUCCEEDED', metrics=%s, completed_at=now(), updated_at=now() WHERE id=%s RETURNING *",
                    (Jsonb(metrics), job_id),
                ).fetchone()
                return self._job_payload(updated)

        try:
            with self._pool.connection() as connection:
                files = connection.execute(
                    """SELECT f.path, f.source_kind AS "sourceKind", b.content FROM rag_source_file f
                       JOIN rag_source_blob b ON b.id=f.source_blob_id
                       WHERE f.source_version_id=%s AND f.decision='ELIGIBLE' ORDER BY f.path""",
                    (job["source_version_id"],),
                ).fetchall()
            bundle = build_index_bundle(job["source_version_id"], files, adapter, batch_size)
            with self._pool.connection() as connection:
                version = connection.execute(
                    "SELECT source_id, state, eligible_file_count FROM rag_source_version WHERE id=%s FOR UPDATE",
                    (job["source_version_id"],),
                ).fetchone()
                expected_state = "ACTIVE" if job["job_type"] == "REINDEX" else "INDEXING"
                if not version or version["state"] != expected_state:
                    raise InvalidStateError("source version is not in the required indexing state")
                if bundle.indexed_file_count != version["eligible_file_count"]:
                    raise ConflictError("partial indexing cannot activate a source version")
                connection.execute("DELETE FROM rag_code_relation WHERE source_version_id=%s", (job["source_version_id"],))
                connection.execute("DELETE FROM rag_code_symbol WHERE source_version_id=%s", (job["source_version_id"],))
                connection.execute("DELETE FROM rag_chunk WHERE source_version_id=%s", (job["source_version_id"],))
                for chunk in bundle.chunks:
                    connection.execute(
                        """INSERT INTO rag_chunk
                           (id, source_version_id, source_kind, path, path_hash, symbol, start_line, end_line,
                            content, content_hash, parser_status, parser_profile_id, chunk_index, token_count)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (chunk.id, chunk.source_version_id, chunk.source_kind, chunk.path, chunk.path_hash, chunk.symbol,
                         chunk.start_line, chunk.end_line, chunk.content, chunk.content_hash, chunk.parser_status,
                         chunk.parser_profile_id, chunk.chunk_index, max(1, len(chunk.content) // 4)),
                    )
                for chunk_id, vector in bundle.embeddings:
                    connection.execute(
                        "INSERT INTO rag_chunk_embedding (chunk_id, embedding_profile_id, embedding) VALUES (%s, '00000000-0000-0000-0000-000000000001', %s::vector)",
                        (chunk_id, self._vector_literal(vector)),
                    )
                for symbol in bundle.symbols:
                    connection.execute(
                        """INSERT INTO rag_code_symbol
                           (id, source_version_id, chunk_id, language, package_name, qualified_name, signature, path, start_line, end_line)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (symbol.id, symbol.source_version_id, symbol.chunk_id, symbol.language, symbol.package_name,
                         symbol.qualified_name, symbol.signature, symbol.path, symbol.start_line, symbol.end_line),
                    )
                symbol_names = {item.qualified_name: item.id for item in bundle.symbols}
                for relation in bundle.relations:
                    connection.execute(
                        """INSERT INTO rag_code_relation
                           (id, source_version_id, from_symbol_id, to_symbol_id, to_qualified_name, relation_type, confidence)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (relation.id, relation.source_version_id, relation.from_symbol_id,
                         symbol_names.get(relation.to_qualified_name), relation.to_qualified_name,
                         relation.relation_type, relation.confidence),
                    )
                for audit in bundle.provider_audits:
                    self._record_embedding_call(connection, audit, correlation_id, ingestion_job_id=job_id)
                if job["job_type"] != "REINDEX":
                    connection.execute("UPDATE rag_chunk SET active=false WHERE source_version_id IN (SELECT id FROM rag_source_version WHERE source_id=%s AND state='ACTIVE')", (version["source_id"],))
                    connection.execute("UPDATE rag_code_symbol SET active=false WHERE source_version_id IN (SELECT id FROM rag_source_version WHERE source_id=%s AND state='ACTIVE')", (version["source_id"],))
                    connection.execute("UPDATE rag_code_relation SET active=false WHERE source_version_id IN (SELECT id FROM rag_source_version WHERE source_id=%s AND state='ACTIVE')", (version["source_id"],))
                    connection.execute("UPDATE rag_source_version SET state='WITHDRAWN' WHERE source_id=%s AND state='ACTIVE'", (version["source_id"],))
                connection.execute("UPDATE rag_source_version SET state='ACTIVE', indexed_file_count=%s WHERE id=%s", (bundle.indexed_file_count, job["source_version_id"]))
                connection.execute("UPDATE rag_source SET state='ACTIVE', updated_at=now() WHERE id=%s", (version["source_id"],))
                metrics = {"indexedFiles": bundle.indexed_file_count, "chunks": len(bundle.chunks),
                           "symbols": len(bundle.symbols), "relations": len(bundle.relations),
                           "embeddingBatches": len(bundle.provider_audits), "parsedFiles": bundle.parsed_file_count,
                           "fallbackFiles": bundle.fallback_file_count}
                updated = connection.execute(
                    """UPDATE rag_ingestion_job SET state='SUCCEEDED', failure_class=NULL, error_code=NULL,
                       metrics=%s, completed_at=now(), updated_at=now() WHERE id=%s RETURNING *""",
                    (Jsonb(metrics), job_id),
                ).fetchone()
                return self._job_payload(updated)
        except Exception as exc:
            safe_error_code = str(getattr(exc, "code", "INDEXING_FAILED"))[:64]
            LOGGER.error(
                "indexing job failed",
                extra={
                    "jobId": str(job_id),
                    "exceptionType": type(exc).__name__,
                    "errorCode": safe_error_code,
                },
            )
            print(
                json.dumps(
                    {
                        "event": "indexing_job_failed",
                        "jobId": str(job_id),
                        "exceptionType": type(exc).__name__,
                        "errorCode": safe_error_code,
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )
            with self._pool.connection() as connection:
                if job["job_type"] != "REINDEX":
                    connection.execute("UPDATE rag_source_version SET state='APPROVED' WHERE id=%s AND state='INDEXING'", (job["source_version_id"],))
                    connection.execute("UPDATE rag_source SET state='APPROVED', updated_at=now() WHERE id=%s", (job["source_id"],))
                connection.execute("UPDATE rag_ingestion_job SET state='FAILED', failure_class='TERMINAL', error_code='INDEXING_FAILED', completed_at=now(), updated_at=now() WHERE id=%s", (job_id,))
            raise

    def retrieve(self, request: dict[str, Any], embedding_result: Any, correlation_id: str) -> dict[str, Any]:
        query_id = UUID(str(request["queryId"]))
        query_vector = self._vector_literal(embedding_result.vectors[0])
        with self._pool.connection() as connection:
            if request.get("compatibilitySetId"):
                version_rows = connection.execute(
                    "SELECT source_version_id AS id FROM rag_compatibility_set_source WHERE compatibility_set_id=%s",
                    (request["compatibilitySetId"],),
                ).fetchall()
                if not version_rows:
                    raise NotFoundError("compatibility set not found")
                version_ids = [item["id"] for item in version_rows]
            else:
                version_rows = connection.execute(
                    """SELECT v.id FROM rag_source_version v JOIN rag_source s ON s.id=v.source_id
                       WHERE v.state='ACTIVE' AND s.source_profile_id=ANY(%s)""",
                    (request.get("sourceProfileIds") or [],),
                ).fetchall()
                version_ids = [item["id"] for item in version_rows]
            if not version_ids:
                self._record_embedding_call(connection, embedding_result, correlation_id, query_id=query_id)
                return {"queryId": query_id, "results": [], "resultCount": 0,
                        "provider": embedding_result.provider, "providerCalled": embedding_result.provider == "openai"}
            base = """SELECT c.id, c.source_version_id, c.source_kind, c.path, c.start_line, c.end_line,
                     c.symbol, c.content, s.source_profile_id, s.repository, s.branch, v.commit_sha
                     FROM rag_chunk c JOIN rag_source_version v ON v.id=c.source_version_id
                     JOIN rag_source s ON s.id=v.source_id"""
            fts = connection.execute(
                base + " WHERE c.active AND v.state='ACTIVE' AND c.source_version_id=ANY(%s) AND c.search_document @@ plainto_tsquery('simple', %s) ORDER BY ts_rank(c.search_document, plainto_tsquery('simple', %s)) DESC, c.id LIMIT 20",
                (version_ids, request["question"], request["question"]),
            ).fetchall()
            identifier = connection.execute(
                base + " WHERE c.active AND v.state='ACTIVE' AND c.source_version_id=ANY(%s) AND c.symbol IS NOT NULL ORDER BY similarity(c.symbol, %s) DESC, c.id LIMIT 20",
                (version_ids, request["question"]),
            ).fetchall()
            identifiers = list(implementation_identifiers(request["question"]))
            implementation = []
            if identifiers:
                implementation = connection.execute(
                    base + """ CROSS JOIN LATERAL (
                        SELECT count(*) AS hits FROM unnest(%s::text[]) AS term
                        WHERE position(lower(term) in lower(c.path)) > 0
                           OR position(lower(term) in lower(coalesce(c.symbol, ''))) > 0
                      ) lexical
                      WHERE c.active AND v.state='ACTIVE' AND c.source_version_id=ANY(%s)
                        AND lexical.hits > 0
                      ORDER BY lexical.hits DESC, c.id LIMIT 20""",
                    (identifiers, version_ids),
                ).fetchall()
            vector = connection.execute(
                base + " JOIN rag_chunk_embedding e ON e.chunk_id=c.id WHERE c.active AND v.state='ACTIVE' AND c.source_version_id=ANY(%s) ORDER BY e.embedding <=> %s::vector, c.id LIMIT 30",
                (version_ids, query_vector),
            ).fetchall()
            lookup = {row["id"]: row for row in [*fts, *identifier, *implementation, *vector]}
            kinds = {key: row["source_kind"] for key, row in lookup.items()}
            ranked = reciprocal_rank_fusion(
                {
                    "fts": [row["id"] for row in fts],
                    "identifier": [row["id"] for row in identifier],
                    "implementation": [row["id"] for row in implementation],
                    "vector": [row["id"] for row in vector],
                }, kinds,
            )[:10]
            self._record_embedding_call(connection, embedding_result, correlation_id, query_id=query_id)
        results = []
        for chunk_id, score, channels in ranked:
            row = lookup[chunk_id]
            results.append({"chunkId": chunk_id, "sourceVersionId": row["source_version_id"],
                            "sourceProfileId": row["source_profile_id"],
                            "repository": row["repository"], "branch": row["branch"],
                            "commit": row["commit_sha"], "path": row["path"], "startLine": row["start_line"],
                            "endLine": row["end_line"], "symbol": row["symbol"], "score": score,
                            "channels": channels, "sourceKind": row["source_kind"], "content": row["content"]})
        return {"queryId": query_id, "results": results, "resultCount": len(results),
                "provider": embedding_result.provider, "providerCalled": embedding_result.provider == "openai"}

    def record_response_call(self, query_id: UUID, result: Any, correlation_id: str) -> None:
        with self._pool.connection() as connection:
            connection.execute(
                """INSERT INTO rag_provider_call
                   (id, query_id, provider, surface, provider_profile_id, profile_version,
                    requested_model_id, returned_model_id, reasoning_effort, provider_request_id,
                    provider_response_id, input_tokens, output_tokens, latency_ms, status, correlation_id)
                   VALUES (%s,%s,%s,'responses-api',%s,1,%s,%s,%s,%s,%s,%s,%s,%s,'SUCCEEDED',%s)""",
                (uuid4(), query_id, result.provider, result.profile_id, result.requested_model_id,
                 result.returned_model_id, PROVIDER_PROFILES[result.profile_id].reasoning_effort,
                 result.request_id, result.response_id, result.input_tokens, result.output_tokens,
                 result.latency_ms, correlation_id),
            )

    def record_response_failure(self, query_id: UUID, error: Any, correlation_id: str) -> None:
        with self._pool.connection() as connection:
            connection.execute(
                """INSERT INTO rag_provider_call
                   (id, query_id, provider, surface, provider_profile_id, profile_version,
                    requested_model_id, reasoning_effort, provider_request_id, latency_ms, status,
                    failure_class, error_code, correlation_id)
                   VALUES (%s,%s,'openai','responses-api',%s,1,%s,%s,%s,%s,'FAILED',%s,%s,%s)""",
                (uuid4(), query_id, error.profile_id, error.requested_model_id,
                 PROVIDER_PROFILES[error.profile_id].reasoning_effort, error.request_id,
                 error.latency_ms, error.failure_class, error.code, correlation_id),
            )

    def create_evaluation_run(
        self, request: dict[str, Any], idempotency_key: str, correlation_id: str = "legacy"
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT * FROM rag_evaluation_run WHERE idempotency_key=%s", (idempotency_key,)
            ).fetchone()
            if repeated:
                return self._evaluation_payload(repeated)
            row = connection.execute(
                """
                INSERT INTO rag_evaluation_run
                    (id, name, source_profile_ids, compatibility_set_id, provider_profile_id,
                     requested_by, state, idempotency_key, correlation_id)
                VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', %s, %s)
                RETURNING *
                """,
                (
                    uuid4(),
                    request["name"],
                    request.get("sourceProfileIds"),
                    request.get("compatibilitySetId"),
                    request["providerProfileId"],
                    request["requestedBy"],
                    idempotency_key,
                    correlation_id,
                ),
            ).fetchone()
            return self._evaluation_payload(row)

    @staticmethod
    def _evaluation_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "runId": row["id"],
            "name": row["name"],
            "sourceProfileIds": row["source_profile_ids"],
            "compatibilitySetId": row["compatibility_set_id"],
            "providerProfileId": row["provider_profile_id"],
            "requestedBy": row["requested_by"],
            "correlationId": row.get("correlation_id", "legacy"),
            "state": row["state"],
            "totalCases": row["total_cases"],
            "passedCases": row["passed_cases"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def get_evaluation_run(self, run_id: UUID) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute("SELECT * FROM rag_evaluation_run WHERE id=%s", (run_id,)).fetchone()
            if not row:
                raise NotFoundError("evaluation run not found")
            return self._evaluation_payload(row)

    def start_evaluation_run(self, run_id: UUID, total_cases: int) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute(
                """UPDATE rag_evaluation_run SET state='RUNNING', total_cases=%s, passed_cases=0,
                   updated_at=now() WHERE id=%s AND state='PENDING' RETURNING *""",
                (total_cases, run_id),
            ).fetchone()
            if row:
                return self._evaluation_payload(row)
            existing = connection.execute("SELECT state FROM rag_evaluation_run WHERE id=%s", (run_id,)).fetchone()
            if not existing:
                raise NotFoundError("evaluation run not found")
            raise InvalidStateError("only pending evaluation runs can start")

    def record_evaluation_result(
        self, run_id: UUID, case: dict[str, Any], result: dict[str, Any], judgment: dict[str, Any], latency_ms: int
    ) -> None:
        case_id = uuid5(NAMESPACE_URL, f"techflow-evaluation:{case['caseKey']}")
        citation_ids = []
        for item in result.get("citations") or []:
            try:
                citation_ids.append(UUID(str(item["chunkId"])))
            except (KeyError, TypeError, ValueError):
                continue
        with self._pool.connection() as connection:
            run = connection.execute(
                "SELECT state FROM rag_evaluation_run WHERE id=%s FOR UPDATE", (run_id,)
            ).fetchone()
            if not run:
                raise NotFoundError("evaluation run not found")
            if run["state"] != "RUNNING":
                raise InvalidStateError("evaluation run is not running")
            connection.execute(
                """INSERT INTO rag_evaluation_case
                       (id, case_key, question, locale, expected_state, expected_citation_ids,
                        forbidden_claims, classification, active)
                   VALUES (%s,%s,%s,%s,%s,'{}',%s,'D0',true)
                   ON CONFLICT (case_key) DO UPDATE SET question=EXCLUDED.question, locale=EXCLUDED.locale,
                     expected_state=EXCLUDED.expected_state, forbidden_claims=EXCLUDED.forbidden_claims,
                     classification='D0', active=true""",
                (case_id, case["caseKey"], case["question"], case["locale"], case["expectedState"],
                 case.get("forbiddenClaims") or []),
            )
            connection.execute(
                """INSERT INTO rag_evaluation_result
                       (id, evaluation_run_id, evaluation_case_id, state, passed, citation_ids, latency_ms, error_code)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (evaluation_run_id, evaluation_case_id) DO UPDATE SET
                     state=EXCLUDED.state, passed=EXCLUDED.passed, citation_ids=EXCLUDED.citation_ids,
                     latency_ms=EXCLUDED.latency_ms, error_code=EXCLUDED.error_code""",
                (uuid4(), run_id, case_id, result.get("state", "FAILED"), judgment["passed"], citation_ids,
                 latency_ms, result.get("errorCode")),
            )

    def finish_evaluation_run(self, run_id: UUID, failed: bool = False) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute(
                """UPDATE rag_evaluation_run r SET state=%s,
                     passed_cases=(SELECT count(*) FROM rag_evaluation_result x WHERE x.evaluation_run_id=r.id AND x.passed),
                     updated_at=now() WHERE r.id=%s AND r.state='RUNNING' RETURNING r.*""",
                ("FAILED" if failed else "SUCCEEDED", run_id),
            ).fetchone()
            if not row:
                existing = connection.execute("SELECT state FROM rag_evaluation_run WHERE id=%s", (run_id,)).fetchone()
                if not existing:
                    raise NotFoundError("evaluation run not found")
                raise InvalidStateError("evaluation run is not running")
            return self._evaluation_payload(row)

    def list_evaluation_results(self, run_id: UUID) -> list[dict[str, Any]]:
        with self._pool.connection() as connection:
            exists = connection.execute("SELECT 1 FROM rag_evaluation_run WHERE id=%s", (run_id,)).fetchone()
            if not exists:
                raise NotFoundError("evaluation run not found")
            rows = connection.execute(
                """SELECT c.case_key, r.state, r.passed, cardinality(r.citation_ids) AS citation_count,
                          r.latency_ms, r.error_code
                   FROM rag_evaluation_result r JOIN rag_evaluation_case c ON c.id=r.evaluation_case_id
                   WHERE r.evaluation_run_id=%s ORDER BY c.case_key""",
                (run_id,),
            ).fetchall()
            return [{
                "caseKey": row["case_key"], "state": row["state"], "passed": row["passed"],
                "citationCount": row["citation_count"], "latencyMs": row["latency_ms"],
                "errorCode": row["error_code"],
            } for row in rows]

    @staticmethod
    def _community_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "caseId": row["id"], "discussionId": row["discussion_id"],
            "discussionUrl": row["discussion_url"], "title": row["title"], "state": row["state"],
            "draftVersion": row["draft_version"], "draftAnswer": row["draft_answer"],
            "answerState": row["answer_state"], "citations": row["citations"] or [],
            "evidenceLedger": (row["source_metadata"] or {}).get("evidenceLedger") or {},
            "approvalVersion": row["approval_version"], "reviewer": row["reviewer"],
            "reviewPostId": row.get("review_post_id"), "reviewPostUrl": row.get("review_post_url"),
            "publishedPostId": row["published_post_id"], "publishedPostUrl": row["published_post_url"],
            "conversationState": row.get("conversation_state") or "WAITING_REVIEW",
            "requesterUserId": row.get("requester_user_id"),
            "lastSeenPostId": row.get("last_seen_post_id"), "contextVersion": row.get("context_version") or 0,
            "resolvedPostId": row.get("resolved_post_id"), "resolvedByUserId": row.get("resolved_by_user_id"),
            "resolvedAt": row.get("resolved_at"), "reopenedAt": row.get("reopened_at"),
            "knowledgeBasePostId": row.get("knowledge_base_post_id"),
            "knowledgeBasePostUrl": row.get("knowledge_base_post_url"),
            "knowledgeBaseSourcePostId": row.get("knowledge_base_source_post_id"),
            "knowledgeBaseAnswer": row.get("knowledge_base_answer"),
            "knowledgeBaseVersion": row.get("knowledge_base_version") or 0,
            "knowledgeBasePublishedAt": row.get("knowledge_base_published_at"),
            "knowledgeBaseSolutionSelectedAt": row.get("knowledge_base_solution_selected_at"),
            "knowledgeBaseSolutionSelectedByUserId": row.get("knowledge_base_solution_selected_by_user_id"),
            "correlationId": row["correlation_id"], "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        }

    def create_community_case(
        self, request: dict[str, Any], draft: dict[str, Any], idempotency_key: str, correlation_id: str
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM community_case WHERE idempotency_key=%s ORDER BY created_at LIMIT 1",
                (idempotency_key,),
            ).fetchone()
            if existing:
                result = self._community_payload(existing)
                result["created"] = False
                result["turnCreated"] = False
                return result
            post_id = source_post_id(request)
            row = connection.execute(
                "SELECT * FROM community_case WHERE discussion_id=%s FOR UPDATE", (request["discussionId"],)
            ).fetchone()
            if row:
                inserted = connection.execute(
                    """INSERT INTO community_turn
                       (id,case_id,source_post_id,post_number,author_user_id,role,content,artifact_ids,correlation_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (case_id,source_post_id) DO NOTHING RETURNING id""",
                    (uuid4(), row["id"], post_id, request.get("postNumber"),
                     request.get("postAuthorId") or request["authorId"], request.get("turnRole") or "REQUESTER",
                     request.get("question") or "", json.dumps([str(item) for item in request.get("artifactIds") or []]),
                     correlation_id),
                ).fetchone()
                if not inserted:
                    result = self._community_payload(row)
                    result.update(created=False, turnCreated=False)
                    return result
                draft_version = row["draft_version"] + 1
                was_resolved = row.get("conversation_state") == "RESOLVED"
                metadata = dict(row.get("source_metadata") or {})
                metadata["evidenceLedger"] = draft.get("evidenceLedger") or {}
                updated = connection.execute(
                    """UPDATE community_case SET state='DRAFT_PENDING',conversation_state=%s,
                       draft_version=%s,draft_answer=%s,answer_state=%s,citations=%s,approval_version=0,
                       reviewer=NULL,approved_at=NULL,review_post_id=NULL,review_post_url=NULL,
                       published_post_id=NULL,published_post_url=NULL,published_at=NULL,
                       last_seen_post_id=%s,context_version=context_version+1,
                       resolved_post_id=CASE WHEN %s THEN NULL ELSE resolved_post_id END,
                       resolved_by_user_id=CASE WHEN %s THEN NULL ELSE resolved_by_user_id END,
                       resolved_at=CASE WHEN %s THEN NULL ELSE resolved_at END,
                       reopened_at=CASE WHEN %s THEN now() ELSE reopened_at END,
                       knowledge_base_post_id=CASE WHEN %s THEN NULL ELSE knowledge_base_post_id END,
                       knowledge_base_post_url=CASE WHEN %s THEN NULL ELSE knowledge_base_post_url END,
                       knowledge_base_source_post_id=CASE WHEN %s THEN NULL ELSE knowledge_base_source_post_id END,
                       knowledge_base_answer=CASE WHEN %s THEN NULL ELSE knowledge_base_answer END,
                       knowledge_base_solution_selected_at=CASE WHEN %s THEN NULL ELSE knowledge_base_solution_selected_at END,
                       knowledge_base_solution_selected_by_user_id=CASE WHEN %s THEN NULL ELSE knowledge_base_solution_selected_by_user_id END,
                       correlation_id=%s,idempotency_key=%s,source_metadata=%s,updated_at=now()
                       WHERE id=%s RETURNING *""",
                    (conversation_state_for_draft(draft), draft_version, draft.get("draftAnswer"),
                     draft.get("answerState"), json.dumps(draft.get("citations") or []), post_id,
                     was_resolved, was_resolved, was_resolved, was_resolved,
                     was_resolved, was_resolved, was_resolved, was_resolved, was_resolved, was_resolved,
                     correlation_id, idempotency_key,
                     json.dumps(metadata), row["id"]),
                ).fetchone()
                connection.execute(
                    """INSERT INTO community_response
                       (id,case_id,draft_version,state,answer,answer_state,correlation_id)
                       VALUES (%s,%s,%s,'DRAFT_PENDING',%s,%s,%s)""",
                    (uuid4(), row["id"], draft_version, draft.get("draftAnswer"), draft.get("answerState"), correlation_id),
                )
                connection.execute(
                    """INSERT INTO community_case_event
                       (id,case_id,event_type,actor,idempotency_key,correlation_id,details)
                       VALUES (%s,%s,%s,'techflow',%s,%s,%s)""",
                    (uuid4(), row["id"], "CONVERSATION_REOPENED" if was_resolved else "FOLLOWUP_DRAFT_CREATED",
                     idempotency_key, correlation_id, json.dumps({"sourcePostId": post_id, "draftVersion": draft_version})),
                )
                result = self._community_payload(updated)
                result.update(created=False, turnCreated=True)
                return result
            case_id = uuid4()
            row = connection.execute(
                """INSERT INTO community_case
                   (id,discussion_id,discussion_url,title,state,conversation_state,requester_user_id,last_seen_post_id,
                    context_version,draft_version,draft_answer,answer_state,citations,approval_version,correlation_id,
                    idempotency_key,source_metadata)
                   VALUES (%s,%s,%s,%s,'DRAFT_PENDING',%s,%s,%s,1,1,%s,%s,%s,0,%s,%s,%s) RETURNING *""",
                (case_id, request["discussionId"], request["discussionUrl"], request["title"],
                 conversation_state_for_draft(draft), request["authorId"], post_id,
                 draft.get("draftAnswer"), draft.get("answerState"), json.dumps(draft.get("citations") or []),
                 correlation_id, idempotency_key,
                 json.dumps({"authorId": request["authorId"], "tagSlugs": request.get("tagSlugs") or [],
                             "evidenceLedger": draft.get("evidenceLedger") or {}})),
            ).fetchone()
            connection.execute(
                """INSERT INTO community_turn
                   (id,case_id,source_post_id,post_number,author_user_id,role,content,artifact_ids,correlation_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (uuid4(), case_id, post_id, request.get("postNumber"),
                 request.get("postAuthorId") or request["authorId"], request.get("turnRole") or "REQUESTER",
                 request.get("question") or "", json.dumps([str(item) for item in request.get("artifactIds") or []]),
                 correlation_id),
            )
            connection.execute(
                """INSERT INTO community_response
                   (id,case_id,draft_version,state,answer,answer_state,correlation_id)
                   VALUES (%s,%s,1,'DRAFT_PENDING',%s,%s,%s)""",
                (uuid4(), case_id, draft.get("draftAnswer"), draft.get("answerState"), correlation_id),
            )
            connection.execute(
                "INSERT INTO community_case_event (id,case_id,event_type,actor,correlation_id,details) VALUES (%s,%s,'DRAFT_CREATED','techflow',%s,%s)",
                (uuid4(), case_id, correlation_id, json.dumps({"answerState": draft.get("answerState")})),
            )
            result = self._community_payload(row)
            result["created"] = True
            result["turnCreated"] = True
            return result

    def community_turn_exists(self, discussion_id: str, source_post_id_value: str) -> bool:
        with self._pool.connection() as connection:
            row = connection.execute(
                """SELECT 1 FROM community_turn t JOIN community_case c ON c.id=t.case_id
                   WHERE c.discussion_id=%s AND t.source_post_id=%s""",
                (discussion_id, source_post_id_value),
            ).fetchone()
            return bool(row)

    def retry_failed_community_case(
        self, request: dict[str, Any], draft: dict[str, Any], idempotency_key: str, correlation_id: str
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT c.* FROM community_case_event e JOIN community_case c ON c.id=e.case_id WHERE e.idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if repeated:
                result = self._community_payload(repeated)
                result.update(created=False, turnCreated=False)
                return result
            row = connection.execute(
                "SELECT * FROM community_case WHERE discussion_id=%s FOR UPDATE", (request["discussionId"],)
            ).fetchone()
            post_id = source_post_id(request)
            if not row:
                raise NotFoundError("community conversation not found")
            if not (
                row["state"] == "DRAFT_PENDING"
                and row.get("answer_state") == "FAILED"
                and not row.get("draft_answer")
                and row.get("last_seen_post_id") == post_id
            ):
                raise InvalidStateError("only the current failed community draft can be retried")
            metadata = dict(row.get("source_metadata") or {})
            metadata["evidenceLedger"] = draft.get("evidenceLedger") or {}
            updated = connection.execute(
                """UPDATE community_case SET conversation_state=%s,draft_answer=%s,answer_state=%s,
                   citations=%s,correlation_id=%s,idempotency_key=%s,source_metadata=%s,updated_at=now()
                   WHERE id=%s RETURNING *""",
                (conversation_state_for_draft(draft), draft.get("draftAnswer"), draft.get("answerState"),
                 json.dumps(draft.get("citations") or []), correlation_id, idempotency_key,
                 json.dumps(metadata), row["id"]),
            ).fetchone()
            connection.execute(
                """UPDATE community_response SET answer=%s,answer_state=%s,correlation_id=%s,updated_at=now()
                   WHERE case_id=%s AND draft_version=%s""",
                (draft.get("draftAnswer"), draft.get("answerState"), correlation_id,
                 row["id"], row["draft_version"]),
            )
            connection.execute(
                """INSERT INTO community_case_event
                   (id,case_id,event_type,actor,idempotency_key,correlation_id,details)
                   VALUES (%s,%s,'FAILED_DRAFT_RETRIED','techflow',%s,%s,%s)""",
                (uuid4(), row["id"], idempotency_key, correlation_id,
                 json.dumps({"sourcePostId": post_id, "draftVersion": row["draft_version"]})),
            )
            result = self._community_payload(updated)
            result.update(created=False, turnCreated=True)
            return result

    def list_community_turns(self, discussion_id: str) -> list[dict[str, Any]]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                """SELECT t.* FROM community_turn t JOIN community_case c ON c.id=t.case_id
                   WHERE c.discussion_id=%s ORDER BY t.post_number NULLS FIRST,t.created_at""",
                (discussion_id,),
            ).fetchall()
            return [{
                "turnId": row["id"], "caseId": row["case_id"], "sourcePostId": row["source_post_id"],
                "postNumber": row["post_number"], "authorUserId": row["author_user_id"], "role": row["role"],
                "content": row["content"], "artifactIds": row["artifact_ids"] or [],
                "correlationId": row["correlation_id"], "createdAt": row["created_at"],
            } for row in rows]

    def record_community_turn(
        self, request: dict[str, Any], idempotency_key: str, correlation_id: str
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT * FROM community_case WHERE discussion_id=%s FOR UPDATE", (request["discussionId"],)
            ).fetchone()
            if not row:
                raise NotFoundError("community conversation not found")
            post_id = source_post_id(request)
            inserted = connection.execute(
                """INSERT INTO community_turn
                   (id,case_id,source_post_id,post_number,author_user_id,role,content,artifact_ids,correlation_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (case_id,source_post_id) DO NOTHING RETURNING id""",
                (uuid4(), row["id"], post_id, request.get("postNumber"),
                 request.get("postAuthorId") or request["authorId"], request.get("turnRole") or "STAFF",
                 request.get("question") or "", json.dumps([str(item) for item in request.get("artifactIds") or []]),
                 correlation_id),
            ).fetchone()
            if not inserted:
                result = self._community_payload(row)
                result["turnCreated"] = False
                return result
            reopened = row.get("conversation_state") == "RESOLVED" and request.get("turnRole") == "REQUESTER"
            updated = connection.execute(
                """UPDATE community_case SET last_seen_post_id=%s,context_version=context_version+1,
                   conversation_state=CASE WHEN %s THEN 'ANALYZING' ELSE conversation_state END,
                   resolved_post_id=CASE WHEN %s THEN NULL ELSE resolved_post_id END,
                   resolved_by_user_id=CASE WHEN %s THEN NULL ELSE resolved_by_user_id END,
                   resolved_at=CASE WHEN %s THEN NULL ELSE resolved_at END,
                   reopened_at=CASE WHEN %s THEN now() ELSE reopened_at END,
                   knowledge_base_post_id=CASE WHEN %s THEN NULL ELSE knowledge_base_post_id END,
                   knowledge_base_post_url=CASE WHEN %s THEN NULL ELSE knowledge_base_post_url END,
                   knowledge_base_source_post_id=CASE WHEN %s THEN NULL ELSE knowledge_base_source_post_id END,
                   knowledge_base_answer=CASE WHEN %s THEN NULL ELSE knowledge_base_answer END,
                   knowledge_base_solution_selected_at=CASE WHEN %s THEN NULL ELSE knowledge_base_solution_selected_at END,
                   knowledge_base_solution_selected_by_user_id=CASE WHEN %s THEN NULL ELSE knowledge_base_solution_selected_by_user_id END,
                   updated_at=now()
                   WHERE id=%s RETURNING *""",
                (post_id, reopened, reopened, reopened, reopened, reopened,
                 reopened, reopened, reopened, reopened, reopened, reopened, row["id"]),
            ).fetchone()
            connection.execute(
                """INSERT INTO community_case_event
                   (id,case_id,event_type,actor,idempotency_key,correlation_id,details)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (uuid4(), row["id"], "CONVERSATION_REOPENED" if reopened else "TURN_RECORDED",
                 (request.get("turnRole") or "STAFF").lower(), idempotency_key, correlation_id,
                 json.dumps({"sourcePostId": post_id})),
            )
            result = self._community_payload(updated)
            result["turnCreated"] = True
            return result

    def sync_community_resolution(
        self, request: dict[str, Any], idempotency_key: str, correlation_id: str
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT c.* FROM community_case_event e JOIN community_case c ON c.id=e.case_id WHERE e.idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if repeated:
                return self._community_payload(repeated)
            row = connection.execute(
                "SELECT * FROM community_case WHERE discussion_id=%s FOR UPDATE", (request["discussionId"],)
            ).fetchone()
            if not row:
                raise NotFoundError("community conversation not found")
            best_post = request.get("bestAnswerPostId")
            best_user = request.get("bestAnswerUserId")
            selected_by_administrator = request.get("bestAnswerSelectedByAdministrator") is True
            knowledge_post = row.get("knowledge_base_post_id")
            if best_post and knowledge_post and best_post == knowledge_post:
                state, event_type = "RESOLVED", KB_SOLUTION_CONFIRMED_EVENT
                changed = (
                    row.get("conversation_state") != state
                    or row.get("knowledge_base_solution_selected_at") is None
                )
                resolved_at = row.get("resolved_at")
                preserve_resolution = True
            elif best_post and (best_user == row.get("requester_user_id") or selected_by_administrator):
                state = "RESOLVED"
                event_type = (
                    "RESOLVED_BY_REQUESTER"
                    if best_user == row.get("requester_user_id")
                    else "RESOLVED_BY_ADMINISTRATOR"
                )
                changed = row.get("conversation_state") != state or row.get("resolved_post_id") != best_post
                resolved_at = request.get("bestAnswerSetAt")
                preserve_resolution = False
            elif best_post:
                state, event_type = "WAITING_RESOLUTION", "RESOLUTION_REVIEW_REQUIRED"
                changed = row.get("resolved_post_id") != best_post or row.get("conversation_state") == "RESOLVED"
                resolved_at = None
                preserve_resolution = False
            elif row.get("conversation_state") == "RESOLVED":
                state, event_type, changed, resolved_at = "ANALYZING", "RESOLUTION_UNSET_REOPENED", True, None
                preserve_resolution = False
            else:
                result = self._community_payload(row)
                result["resolutionChanged"] = False
                return result
            updated = connection.execute(
                """UPDATE community_case SET conversation_state=%s,
                   resolved_post_id=CASE WHEN %s THEN resolved_post_id ELSE %s END,
                   resolved_by_user_id=CASE WHEN %s THEN resolved_by_user_id ELSE %s END,
                   resolved_at=CASE WHEN %s='RESOLVED' THEN COALESCE(%s,now()) ELSE NULL END,
                   reopened_at=CASE WHEN %s='ANALYZING' THEN now() ELSE reopened_at END,
                   knowledge_base_post_id=CASE WHEN %s='ANALYZING' THEN NULL ELSE knowledge_base_post_id END,
                   knowledge_base_post_url=CASE WHEN %s='ANALYZING' THEN NULL ELSE knowledge_base_post_url END,
                   knowledge_base_source_post_id=CASE WHEN %s='ANALYZING' THEN NULL ELSE knowledge_base_source_post_id END,
                   knowledge_base_answer=CASE WHEN %s='ANALYZING' THEN NULL ELSE knowledge_base_answer END,
                   knowledge_base_solution_selected_at=CASE
                       WHEN %s='ANALYZING' THEN NULL
                       WHEN %s THEN COALESCE(%s,now())
                       ELSE NULL END,
                   knowledge_base_solution_selected_by_user_id=CASE
                       WHEN %s THEN %s ELSE NULL END,
                   updated_at=now()
                   WHERE id=%s RETURNING *""",
                (state, preserve_resolution, best_post, preserve_resolution, best_user,
                 state, resolved_at, state, state, state, state, state,
                 state, preserve_resolution, request.get("bestAnswerSetAt"),
                 preserve_resolution, best_user, row["id"]),
            ).fetchone()
            if changed:
                connection.execute(
                    """INSERT INTO community_case_event
                       (id,case_id,event_type,actor,idempotency_key,correlation_id,details)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (uuid4(), row["id"], event_type, f"flarum:{best_user or row.get('requester_user_id') or 'unknown'}",
                     idempotency_key, correlation_id, json.dumps({
                         "bestAnswerPostId": best_post,
                         "resolutionActorRole": (
                             "REQUESTER" if best_user == row.get("requester_user_id")
                             else "ADMINISTRATOR" if selected_by_administrator
                             else "OTHER"
                         ),
                     })),
                )
            result = self._community_payload(updated)
            result["resolutionChanged"] = changed
            return result

    def get_community_case(self, case_id: UUID) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute("SELECT * FROM community_case WHERE id=%s", (case_id,)).fetchone()
            if not row:
                raise NotFoundError("community case not found")
            return self._community_payload(row)

    def get_community_case_by_discussion(self, discussion_id: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT * FROM community_case WHERE discussion_id=%s", (discussion_id,)
            ).fetchone()
            if not row:
                raise NotFoundError("community case not found")
            return self._community_payload(row)

    def resolve_community_case(self, reference: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            if reference.isdigit():
                row = connection.execute(
                    "SELECT * FROM community_case WHERE discussion_id=%s", (reference,)
                ).fetchone()
                if row:
                    return self._community_payload(row)
            rows = connection.execute(
                "SELECT * FROM community_case WHERE id::text LIKE %s ORDER BY created_at DESC LIMIT 2",
                (reference.lower() + "%",),
            ).fetchall()
            if len(rows) != 1:
                raise NotFoundError("Community case reference is not unique")
            return self._community_payload(rows[0])

    def list_community_cases(self, states: tuple[str, ...] | None = None, limit: int = 10) -> list[dict[str, Any]]:
        with self._pool.connection() as connection:
            if states:
                rows = connection.execute(
                    "SELECT * FROM community_case WHERE state=ANY(%s) ORDER BY updated_at DESC LIMIT %s",
                    (list(states), limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM community_case ORDER BY updated_at DESC LIMIT %s", (limit,)
                ).fetchall()
            return [self._community_payload(row) for row in rows]

    def list_community_case_events(self, case_id: UUID, limit: int = 10) -> list[dict[str, Any]]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                "SELECT case_id,event_type,actor,details,created_at FROM community_case_event "
                "WHERE case_id=%s ORDER BY created_at DESC LIMIT %s",
                (case_id, limit),
            ).fetchall()
            return [{
                "caseId": row["case_id"], "eventType": row["event_type"], "actor": row["actor"],
                "details": row["details"] or {}, "createdAt": row["created_at"],
            } for row in rows]

    def decide_community_case(self, case_id: UUID, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT c.* FROM community_case_event e JOIN community_case c ON c.id=e.case_id WHERE e.idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if repeated:
                return self._community_payload(repeated)
            row = connection.execute("SELECT * FROM community_case WHERE id=%s FOR UPDATE", (case_id,)).fetchone()
            if not row:
                raise NotFoundError("community case not found")
            target_state = "APPROVED" if request["decision"] == "APPROVE" else "REJECTED"
            if row["state"] == target_state and row["draft_version"] == request["expectedDraftVersion"]:
                edited_answer = request.get("editedAnswer")
                if edited_answer and edited_answer != row["draft_answer"]:
                    raise InvalidStateError("draft state or version changed")
                return self._community_payload(row)
            if row["state"] != "DRAFT_PENDING" or row["draft_version"] != request["expectedDraftVersion"]:
                raise InvalidStateError("draft state or version changed")
            answer = request.get("editedAnswer") or row["draft_answer"]
            if request["decision"] == "APPROVE" and not answer:
                raise InvalidStateError("an answer is required for approval")
            state = target_state
            updated = connection.execute(
                """UPDATE community_case SET state=%s,draft_answer=%s,reviewer=%s,approval_version=approval_version+1,
                   conversation_state=CASE WHEN %s='REJECTED' THEN 'ANALYZING' ELSE conversation_state END,
                   approved_at=CASE WHEN %s='APPROVED' THEN now() ELSE NULL END,updated_at=now() WHERE id=%s RETURNING *""",
                (state, answer, request["reviewer"], state, state, case_id),
            ).fetchone()
            connection.execute(
                """UPDATE community_response SET state=CASE WHEN %s='REJECTED' THEN 'REJECTED' ELSE state END,
                   answer=%s,reviewer=%s,updated_at=now() WHERE case_id=%s AND draft_version=%s""",
                (state, answer, request["reviewer"], case_id, row["draft_version"]),
            )
            connection.execute(
                """INSERT INTO community_case_event
                   (id,case_id,event_type,actor,idempotency_key,correlation_id,details)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (uuid4(), case_id, state, request["reviewer"], idempotency_key, row["correlation_id"],
                 json.dumps({"draftVersion": row["draft_version"], "note": request.get("note")})),
            )
            return self._community_payload(updated)

    def attach_community_review(self, case_id: UUID, review: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT c.* FROM community_case_event e JOIN community_case c ON c.id=e.case_id WHERE e.idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if repeated:
                return self._community_payload(repeated)
            row = connection.execute("SELECT * FROM community_case WHERE id=%s FOR UPDATE", (case_id,)).fetchone()
            if not row:
                raise NotFoundError("community case not found")
            if row.get("review_post_id") and row["review_post_id"] != review["postId"]:
                raise ConflictError("community review post already attached")
            updated = connection.execute(
                """UPDATE community_case SET review_post_id=%s,review_post_url=%s,updated_at=now()
                   WHERE id=%s RETURNING *""",
                (review["postId"], review["postUrl"], case_id),
            ).fetchone()
            connection.execute(
                """UPDATE community_response SET review_post_id=%s,review_post_url=%s,updated_at=now()
                   WHERE case_id=%s AND draft_version=%s""",
                (review["postId"], review["postUrl"], case_id, row["draft_version"]),
            )
            connection.execute(
                """INSERT INTO community_case_event
                   (id,case_id,event_type,actor,idempotency_key,correlation_id,details)
                   VALUES (%s,%s,'REVIEW_POST_CREATED','techflow-assistant',%s,%s,%s)""",
                (uuid4(), case_id, idempotency_key, row["correlation_id"], json.dumps(review)),
            )
            return self._community_payload(updated)

    def mark_community_review_approved(self, case_id: UUID, idempotency_key: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT c.* FROM community_case_event e JOIN community_case c ON c.id=e.case_id WHERE e.idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if repeated:
                return self._community_payload(repeated)
            row = connection.execute("SELECT * FROM community_case WHERE id=%s FOR UPDATE", (case_id,)).fetchone()
            if not row or not row.get("review_post_id"):
                raise NotFoundError("community review post not found")
            if row["state"] == "PUBLISHED":
                return self._community_payload(row)
            if row["state"] != "DRAFT_PENDING":
                raise InvalidStateError("only pending review posts can be approved")
            updated = connection.execute(
                """UPDATE community_case SET state='PUBLISHED',conversation_state='WAITING_RESOLUTION',reviewer='flarum:moderator',
                   approval_version=approval_version+1,approved_at=now(),published_post_id=review_post_id,
                   published_post_url=review_post_url,published_at=now(),updated_at=now()
                   WHERE id=%s RETURNING *""",
                (case_id,),
            ).fetchone()
            connection.execute(
                """UPDATE community_response SET state='PUBLISHED',reviewer='flarum:moderator',published_at=now(),updated_at=now()
                   WHERE case_id=%s AND draft_version=%s""",
                (case_id, row["draft_version"]),
            )
            connection.execute(
                """INSERT INTO community_case_event
                   (id,case_id,event_type,actor,idempotency_key,correlation_id,details)
                   VALUES (%s,%s,'PUBLISHED','flarum:moderator',%s,%s,%s)""",
                (uuid4(), case_id, idempotency_key, row["correlation_id"],
                 json.dumps({"approvalSurface": "FLARUM_APPROVAL"})),
            )
            return self._community_payload(updated)

    def mark_community_review_missing(self, case_id: UUID, idempotency_key: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT c.* FROM community_case_event e JOIN community_case c ON c.id=e.case_id WHERE e.idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if repeated:
                return self._community_payload(repeated)
            row = connection.execute("SELECT * FROM community_case WHERE id=%s FOR UPDATE", (case_id,)).fetchone()
            if not row:
                raise NotFoundError("community case not found")
            if row["state"] != "DRAFT_PENDING":
                return self._community_payload(row)
            updated = connection.execute(
                """UPDATE community_case SET state='REJECTED',conversation_state='ANALYZING',
                   reviewer='techflow:reconcile',updated_at=now() WHERE id=%s RETURNING *""",
                (case_id,),
            ).fetchone()
            connection.execute(
                """UPDATE community_response SET state='REJECTED',reviewer='techflow:reconcile',updated_at=now()
                   WHERE case_id=%s AND draft_version=%s""",
                (case_id, row["draft_version"]),
            )
            connection.execute(
                """INSERT INTO community_case_event
                   (id,case_id,event_type,actor,idempotency_key,correlation_id,details)
                   VALUES (%s,%s,'REVIEW_POST_MISSING','techflow:reconcile',%s,%s,%s)""",
                (uuid4(), case_id, idempotency_key, row["correlation_id"],
                 json.dumps({"reviewPostId": row.get("review_post_id")})),
            )
            return self._community_payload(updated)

    def mark_community_published(self, case_id: UUID, publication: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT c.* FROM community_case_event e JOIN community_case c ON c.id=e.case_id WHERE e.idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if repeated:
                return self._community_payload(repeated)
            row = connection.execute("SELECT * FROM community_case WHERE id=%s FOR UPDATE", (case_id,)).fetchone()
            if not row:
                raise NotFoundError("community case not found")
            if row["state"] != "APPROVED":
                raise InvalidStateError("only approved drafts can be published")
            updated = connection.execute(
                """UPDATE community_case SET state='PUBLISHED',conversation_state='WAITING_RESOLUTION',published_post_id=%s,published_post_url=%s,
                   published_at=now(),updated_at=now() WHERE id=%s RETURNING *""",
                (publication["postId"], publication["postUrl"], case_id),
            ).fetchone()
            connection.execute(
                """INSERT INTO community_case_event
                   (id,case_id,event_type,actor,idempotency_key,correlation_id,details)
                   VALUES (%s,%s,'PUBLISHED','techflow',%s,%s,%s)""",
                (uuid4(), case_id, idempotency_key, row["correlation_id"], json.dumps(publication)),
            )
            return self._community_payload(updated)

    def mark_community_auto_published(
        self, case_id: UUID, answer: str, publication: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT c.* FROM community_case_event e JOIN community_case c ON c.id=e.case_id WHERE e.idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if repeated:
                return self._community_payload(repeated)
            row = connection.execute("SELECT * FROM community_case WHERE id=%s FOR UPDATE", (case_id,)).fetchone()
            if not row:
                raise NotFoundError("community case not found")
            if row["state"] == "PUBLISHED" and row.get("published_post_id") == publication["postId"]:
                return self._community_payload(row)
            if (
                row["state"] not in {"DRAFT_PENDING", "PUBLISHED"}
                or row.get("reviewer") == "techflow:auto"
                or not answer.strip()
            ):
                raise InvalidStateError("only generated community answers can be auto-published")
            updated = connection.execute(
                """UPDATE community_case SET state='PUBLISHED',conversation_state='WAITING_RESOLUTION',
                   reviewer='techflow:auto',draft_answer=%s,published_post_id=%s,published_post_url=%s,published_at=now(),updated_at=now()
                   WHERE id=%s RETURNING *""",
                (answer, publication["postId"], publication["postUrl"], case_id),
            ).fetchone()
            connection.execute(
                """UPDATE community_response SET state='PUBLISHED',answer=%s,reviewer='techflow:auto',published_at=now(),updated_at=now()
                   WHERE case_id=%s AND draft_version=%s""",
                (answer, case_id, row["draft_version"]),
            )
            connection.execute(
                """INSERT INTO community_case_event
                   (id,case_id,event_type,actor,idempotency_key,correlation_id,details)
                   VALUES (%s,%s,'AUTO_PUBLISHED','techflow-assistant',%s,%s,%s)""",
                (uuid4(), case_id, idempotency_key, row["correlation_id"], json.dumps(publication)),
            )
            return self._community_payload(updated)

    def mark_community_knowledge_published(
        self, case_id: UUID, answer: str, publication: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT c.* FROM community_case_event e JOIN community_case c ON c.id=e.case_id WHERE e.idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if repeated:
                return self._community_payload(repeated)
            row = connection.execute("SELECT * FROM community_case WHERE id=%s FOR UPDATE", (case_id,)).fetchone()
            if not row:
                raise NotFoundError("community case not found")
            if row.get("conversation_state") != "RESOLVED" or not row.get("resolved_post_id"):
                raise InvalidStateError("knowledge base publication requires a requester or administrator resolution")
            updated = connection.execute(
                """UPDATE community_case SET knowledge_base_post_id=%s,knowledge_base_post_url=%s,
                   knowledge_base_source_post_id=resolved_post_id,knowledge_base_answer=%s,
                   knowledge_base_version=knowledge_base_version+1,knowledge_base_published_at=now(),
                   knowledge_base_solution_selected_at=NULL,
                   knowledge_base_solution_selected_by_user_id=NULL,updated_at=now()
                   WHERE id=%s RETURNING *""",
                (publication["postId"], publication["postUrl"], answer, case_id),
            ).fetchone()
            connection.execute(
                """INSERT INTO community_case_event
                   (id,case_id,event_type,actor,idempotency_key,correlation_id,details)
                   VALUES (%s,%s,'KNOWLEDGE_BASE_PUBLISHED','techflow-assistant',%s,%s,%s)""",
                (uuid4(), case_id, idempotency_key, row["correlation_id"],
                 json.dumps({**publication, "resolvedPostId": row["resolved_post_id"]})),
            )
            return self._community_payload(updated)

    def mark_community_knowledge_solution_selected(
        self, case_id: UUID, selection: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            repeated = connection.execute(
                "SELECT c.* FROM community_case_event e JOIN community_case c ON c.id=e.case_id WHERE e.idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if repeated:
                return self._community_payload(repeated)
            row = connection.execute("SELECT * FROM community_case WHERE id=%s FOR UPDATE", (case_id,)).fetchone()
            if not row:
                raise NotFoundError("community case not found")
            if row.get("conversation_state") != "RESOLVED" or not row.get("knowledge_base_post_id"):
                raise InvalidStateError("knowledge base solution selection requires a published knowledge base")
            if str(selection.get("postId")) != str(row["knowledge_base_post_id"]):
                raise ConflictError("selected solution does not match the knowledge base post")
            updated = connection.execute(
                """UPDATE community_case SET knowledge_base_solution_selected_at=now(),
                   knowledge_base_solution_selected_by_user_id=%s,updated_at=now()
                   WHERE id=%s RETURNING *""",
                (selection.get("selectedByUserId"), case_id),
            ).fetchone()
            connection.execute(
                """INSERT INTO community_case_event
                   (id,case_id,event_type,actor,idempotency_key,correlation_id,details)
                   VALUES (%s,%s,'KNOWLEDGE_BASE_SOLUTION_SELECTED','techflow-integration',%s,%s,%s)""",
                (uuid4(), case_id, idempotency_key, row["correlation_id"], json.dumps(selection)),
            )
            return self._community_payload(updated)

    def upsert_chat_reviewer(self, user_id: str, username: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute(
                """INSERT INTO chat_reviewer_identity (user_id,username,last_seen_at)
                   VALUES (%s,%s,now())
                   ON CONFLICT (user_id) DO UPDATE SET username=EXCLUDED.username,last_seen_at=now()
                   RETURNING user_id,username,last_seen_at""",
                (user_id, username),
            ).fetchone()
            return {"userId": row["user_id"], "username": row["username"], "lastSeenAt": row["last_seen_at"]}

    def list_chat_reviewers(self) -> list[dict[str, Any]]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                "SELECT user_id,username,last_seen_at FROM chat_reviewer_identity WHERE enabled=true ORDER BY username"
            ).fetchall()
            return [{"userId": row["user_id"], "username": row["username"], "lastSeenAt": row["last_seen_at"]}
                    for row in rows]

    @staticmethod
    def _chat_conversation_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "userId": row["user_id"], "username": row["username"], "state": row["state"],
            "contextVersion": row["context_version"], "openedAt": row["opened_at"],
            "resolvedAt": row["resolved_at"], "updatedAt": row["updated_at"],
        }

    def open_chat_conversation(self, user_id: str, username: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT * FROM chat_assist_conversation WHERE user_id=%s FOR UPDATE", (user_id,),
            ).fetchone()
            if not row:
                row = connection.execute(
                    """INSERT INTO chat_assist_conversation(user_id,username,state)
                       VALUES (%s,%s,'ACTIVE') RETURNING *""", (user_id, username),
                ).fetchone()
            elif row["state"] == "RESOLVED":
                row = connection.execute(
                    """UPDATE chat_assist_conversation SET username=%s,state='ACTIVE',
                       context_version=context_version+1,opened_at=now(),resolved_at=NULL,updated_at=now()
                       WHERE user_id=%s RETURNING *""", (username, user_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "UPDATE chat_assist_conversation SET username=%s,updated_at=now() WHERE user_id=%s RETURNING *",
                    (username, user_id),
                ).fetchone()
            return self._chat_conversation_payload(row)

    def list_chat_turns(self, user_id: str, limit: int = 12) -> list[dict[str, Any]]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                """SELECT t.* FROM chat_assist_turn t JOIN chat_assist_conversation c ON c.user_id=t.user_id
                   WHERE t.user_id=%s AND c.state='ACTIVE' AND t.context_version=c.context_version
                   ORDER BY t.created_at DESC LIMIT %s""", (user_id, max(1, min(limit, 50))),
            ).fetchall()
            return [{
                "turnId": row["id"], "userId": row["user_id"], "contextVersion": row["context_version"],
                "postId": row["post_id"], "role": row["role"], "content": row["content"],
                "contentSha256": row["content_sha256"], "createdAt": row["created_at"],
            } for row in reversed(rows)]

    def record_chat_turn(self, user_id: str, post_id: str, role: str, content: str) -> dict[str, Any]:
        import hashlib
        with self._pool.connection() as connection:
            conversation = connection.execute(
                "SELECT * FROM chat_assist_conversation WHERE user_id=%s AND state='ACTIVE'", (user_id,),
            ).fetchone()
            if not conversation:
                raise InvalidStateError("active Chat conversation is required")
            row = connection.execute(
                """INSERT INTO chat_assist_turn
                   (id,user_id,context_version,post_id,role,content,content_sha256)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (user_id,context_version,post_id,role) DO UPDATE SET post_id=EXCLUDED.post_id
                   RETURNING *""",
                (uuid4(), user_id, conversation["context_version"], post_id, role, content[:16000],
                 hashlib.sha256(content.encode("utf-8")).hexdigest()),
            ).fetchone()
            return {
                "turnId": row["id"], "userId": row["user_id"], "contextVersion": row["context_version"],
                "postId": row["post_id"], "role": row["role"], "content": row["content"],
                "contentSha256": row["content_sha256"], "createdAt": row["created_at"],
            }

    def resolve_chat_conversation(self, user_id: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute(
                """UPDATE chat_assist_conversation SET state='RESOLVED',resolved_at=COALESCE(resolved_at,now()),
                   updated_at=now() WHERE user_id=%s RETURNING *""", (user_id,),
            ).fetchone()
            if not row:
                raise NotFoundError("active Chat conversation not found")
            return self._chat_conversation_payload(row)

    @staticmethod
    def _chat_job_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "jobId": row["id"], "userId": row["user_id"], "contextVersion": row["context_version"],
            "postId": row["post_id"], "state": row["state"], "attemptCount": row["attempt_count"],
            "maxAttempts": row["max_attempts"], "lastErrorType": row["last_error_type"],
            "correlationId": row["correlation_id"], "nextAttemptAt": row["next_attempt_at"],
            "startedAt": row["started_at"], "completedAt": row["completed_at"],
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        }

    def enqueue_chat_job(
        self, user_id: str, post_id: str, correlation_id: str, max_attempts: int = 3
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            conversation = connection.execute(
                "SELECT * FROM chat_assist_conversation WHERE user_id=%s AND state='ACTIVE' FOR UPDATE", (user_id,),
            ).fetchone()
            if not conversation:
                raise InvalidStateError("active Chat conversation is required")
            created = connection.execute(
                """INSERT INTO chat_assist_job
                   (id,user_id,context_version,post_id,state,max_attempts,correlation_id,next_attempt_at)
                   VALUES (%s,%s,%s,%s,'PENDING',%s,%s,now())
                   ON CONFLICT (user_id,context_version,post_id) DO NOTHING RETURNING *""",
                (uuid4(), user_id, conversation["context_version"], post_id,
                 max(1, min(max_attempts, 10)), correlation_id),
            ).fetchone()
            row = created or connection.execute(
                """SELECT * FROM chat_assist_job
                   WHERE user_id=%s AND context_version=%s AND post_id=%s""",
                (user_id, conversation["context_version"], post_id),
            ).fetchone()
            result = self._chat_job_payload(row)
            result["created"] = bool(created)
            return result

    def get_chat_job(self, job_id: UUID) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute("SELECT * FROM chat_assist_job WHERE id=%s", (job_id,)).fetchone()
            if not row:
                raise NotFoundError("Chat Assist job not found")
            return self._chat_job_payload(row)

    def claim_chat_job(self, job_id: UUID) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute("SELECT * FROM chat_assist_job WHERE id=%s FOR UPDATE", (job_id,)).fetchone()
            if not row:
                raise NotFoundError("Chat Assist job not found")
            if row["state"] not in {"PENDING", "RETRYING"} or (
                row.get("next_attempt_at") and row["next_attempt_at"] > datetime.now(timezone.utc)
            ):
                return self._chat_job_payload(row)
            row = connection.execute(
                """UPDATE chat_assist_job SET state='RUNNING',attempt_count=attempt_count+1,
                   next_attempt_at=NULL,started_at=now(),updated_at=now() WHERE id=%s RETURNING *""",
                (job_id,),
            ).fetchone()
            return self._chat_job_payload(row)

    def complete_chat_job(self, job_id: UUID) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute("SELECT * FROM chat_assist_job WHERE id=%s FOR UPDATE", (job_id,)).fetchone()
            if not row:
                raise NotFoundError("Chat Assist job not found")
            if row["state"] == "CANCELLED":
                return self._chat_job_payload(row)
            if row["state"] != "RUNNING":
                raise InvalidStateError("only running Chat Assist job can complete")
            row = connection.execute(
                """UPDATE chat_assist_job SET state='COMPLETED',last_error_type=NULL,
                   completed_at=now(),updated_at=now() WHERE id=%s RETURNING *""", (job_id,),
            ).fetchone()
            return self._chat_job_payload(row)

    def fail_chat_job(self, job_id: UUID, error_type: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute("SELECT * FROM chat_assist_job WHERE id=%s FOR UPDATE", (job_id,)).fetchone()
            if not row:
                raise NotFoundError("Chat Assist job not found")
            if row["state"] == "CANCELLED":
                return self._chat_job_payload(row)
            exhausted = row["attempt_count"] >= row["max_attempts"]
            row = connection.execute(
                """UPDATE chat_assist_job SET state=%s,last_error_type=%s,
                   next_attempt_at=CASE WHEN %s THEN NULL
                     ELSE now()+make_interval(secs => power(2,greatest(attempt_count-1,0))::int) END,
                   updated_at=now() WHERE id=%s RETURNING *""",
                ("DEAD_LETTER" if exhausted else "RETRYING", error_type[:128], exhausted, job_id),
            ).fetchone()
            return self._chat_job_payload(row)

    def cancel_chat_jobs(self, user_id: str) -> int:
        with self._pool.connection() as connection:
            result = connection.execute(
                """UPDATE chat_assist_job j SET state='CANCELLED',next_attempt_at=NULL,
                   completed_at=now(),updated_at=now() FROM chat_assist_conversation c
                   WHERE j.user_id=c.user_id AND j.context_version=c.context_version
                     AND j.user_id=%s AND j.state IN ('PENDING','RUNNING','RETRYING')""",
                (user_id,),
            )
            return result.rowcount

    def recover_chat_jobs(self) -> list[dict[str, Any]]:
        with self._pool.connection() as connection:
            connection.execute(
                """UPDATE chat_assist_job SET state='RETRYING',next_attempt_at=now(),updated_at=now()
                   WHERE state='RUNNING'"""
            )
            rows = connection.execute(
                """SELECT * FROM chat_assist_job WHERE state IN ('PENDING','RETRYING')
                   ORDER BY created_at"""
            ).fetchall()
            return [self._chat_job_payload(row) for row in rows]

    @staticmethod
    def _operation_failure_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "failureId": row["id"], "subsystem": row["subsystem"], "operation": row["operation"],
            "fingerprint": row["fingerprint"], "state": row["state"], "attemptCount": row["attempt_count"],
            "maxAttempts": row["max_attempts"], "lastErrorType": row["last_error_type"],
            "correlationId": row["correlation_id"], "nextRetryAt": row["next_retry_at"],
            "failureNotifiedAt": row["failure_notified_at"], "recoveryNotifiedAt": row["recovery_notified_at"],
            "firstFailedAt": row["first_failed_at"], "lastFailedAt": row["last_failed_at"],
            "recoveredAt": row["recovered_at"], "updatedAt": row["updated_at"],
        }

    def record_operation_failure(
        self, subsystem: str, operation: str, fingerprint: str, error_type: str,
        correlation_id: str, max_attempts: int = 3,
    ) -> dict[str, Any]:
        with self._pool.connection() as connection:
            current = connection.execute(
                "SELECT * FROM operation_failure WHERE fingerprint=%s FOR UPDATE", (fingerprint,),
            ).fetchone()
            notify = not current or current["state"] == "RECOVERED"
            if notify:
                if current:
                    row = connection.execute(
                        """UPDATE operation_failure SET subsystem=%s,operation=%s,state='OPEN',attempt_count=1,
                           max_attempts=%s,last_error_type=%s,correlation_id=%s,next_retry_at=now()+interval '1 second',
                           failure_notified_at=now(),recovery_notified_at=NULL,first_failed_at=now(),last_failed_at=now(),
                           recovered_at=NULL,updated_at=now() WHERE id=%s RETURNING *""",
                        (subsystem, operation, max_attempts, error_type, correlation_id, current["id"]),
                    ).fetchone()
                else:
                    row = connection.execute(
                        """INSERT INTO operation_failure
                           (id,subsystem,operation,fingerprint,state,attempt_count,max_attempts,last_error_type,
                            correlation_id,next_retry_at,failure_notified_at)
                           VALUES (%s,%s,%s,%s,'OPEN',1,%s,%s,%s,now()+interval '1 second',now()) RETURNING *""",
                        (uuid4(), subsystem, operation, fingerprint, max_attempts, error_type, correlation_id),
                    ).fetchone()
            else:
                row = connection.execute(
                    """UPDATE operation_failure SET attempt_count=attempt_count+1,
                       state=CASE WHEN attempt_count+1>=max_attempts THEN 'DEAD_LETTER' ELSE 'OPEN' END,
                       last_error_type=%s,correlation_id=%s,last_failed_at=now(),updated_at=now(),
                       next_retry_at=CASE WHEN attempt_count+1>=max_attempts THEN NULL
                           ELSE now() + make_interval(secs => power(2,least(attempt_count,8))::int) END
                       WHERE id=%s RETURNING *""", (error_type, correlation_id, current["id"]),
                ).fetchone()
            return {"failure": self._operation_failure_payload(row), "notifyFailure": notify}

    def recover_operation_failure(self, fingerprint: str, correlation_id: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            current = connection.execute(
                "SELECT * FROM operation_failure WHERE fingerprint=%s FOR UPDATE", (fingerprint,),
            ).fetchone()
            if not current:
                return {"failure": None, "notifyRecovery": False}
            if current["state"] == "RECOVERED":
                return {"failure": self._operation_failure_payload(current), "notifyRecovery": False}
            row = connection.execute(
                """UPDATE operation_failure SET state='RECOVERED',correlation_id=%s,next_retry_at=NULL,
                   recovery_notified_at=now(),recovered_at=now(),updated_at=now() WHERE id=%s RETURNING *""",
                (correlation_id, current["id"]),
            ).fetchone()
            return {"failure": self._operation_failure_payload(row), "notifyRecovery": True}

    def retry_operation_failure(self, failure_id: UUID, correlation_id: str) -> dict[str, Any]:
        with self._pool.connection() as connection:
            row = connection.execute(
                """UPDATE operation_failure SET state='RETRYING',correlation_id=%s,next_retry_at=now(),updated_at=now()
                   WHERE id=%s AND state<>'RECOVERED' RETURNING *""", (correlation_id, failure_id),
            ).fetchone()
            if not row:
                raise NotFoundError("retryable operation failure not found")
            return self._operation_failure_payload(row)

    def list_operation_failures(self, states: tuple[str, ...] | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._pool.connection() as connection:
            if states:
                rows = connection.execute(
                    "SELECT * FROM operation_failure WHERE state=ANY(%s) ORDER BY updated_at DESC LIMIT %s",
                    (list(states), max(1, min(limit, 200))),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM operation_failure ORDER BY updated_at DESC LIMIT %s", (max(1, min(limit, 200)),),
                ).fetchall()
            return [self._operation_failure_payload(row) for row in rows]

    def operations_kpis(self, window_hours: int = 24) -> dict[str, Any]:
        hours = max(1, min(window_hours, 720))
        with self._pool.connection() as connection:
            community = connection.execute(
                """SELECT count(*) AS cases,count(*) FILTER (WHERE state='PUBLISHED') AS published,
                   count(*) FILTER (WHERE conversation_state='RESOLVED') AS resolved,
                   count(*) FILTER (WHERE answer_state='NEEDS_INFORMATION') AS needs_information
                   FROM community_case WHERE updated_at>=now()-make_interval(hours=>%s)""", (hours,),
            ).fetchone()
            chat = connection.execute(
                """SELECT count(*) AS conversations,count(*) FILTER (WHERE state='ACTIVE') AS active,
                   count(*) FILTER (WHERE state='RESOLVED') AS resolved
                   FROM chat_assist_conversation WHERE updated_at>=now()-make_interval(hours=>%s)""", (hours,),
            ).fetchone()
            turns = connection.execute(
                "SELECT count(*) AS count FROM chat_assist_turn WHERE created_at>=now()-make_interval(hours=>%s)",
                (hours,),
            ).fetchone()["count"]
            chat_jobs = connection.execute(
                """SELECT count(*) AS jobs,
                   count(*) FILTER (WHERE state IN ('PENDING','RUNNING','RETRYING')) AS active,
                   count(*) FILTER (WHERE state='COMPLETED') AS completed,
                   count(*) FILTER (WHERE state='DEAD_LETTER') AS dead_letter,
                   count(*) FILTER (WHERE state='CANCELLED') AS cancelled
                   FROM chat_assist_job WHERE updated_at>=now()-make_interval(hours=>%s)""",
                (hours,),
            ).fetchone()
            failures = connection.execute(
                """SELECT count(*) AS failures,count(*) FILTER (WHERE state='OPEN') AS open,
                   count(*) FILTER (WHERE state='DEAD_LETTER') AS dead_letter,
                   count(*) FILTER (WHERE state='RECOVERED') AS recovered
                   FROM operation_failure WHERE updated_at>=now()-make_interval(hours=>%s)""", (hours,),
            ).fetchone()
            coverage_rows = connection.execute(
                """SELECT entry->>'sourceProfileId' AS profile_id,
                   count(DISTINCT c.id) FILTER (WHERE entry->>'state'='EVIDENCE_FOUND') AS found_cases
                   FROM community_case c
                   CROSS JOIN LATERAL jsonb_array_elements(
                       COALESCE(c.source_metadata->'evidenceLedger'->'coverage','[]'::jsonb)
                   ) AS entry
                   WHERE c.updated_at>=now()-make_interval(hours=>%s)
                   GROUP BY entry->>'sourceProfileId'""", (hours,),
            ).fetchall()
            coverage = {row["profile_id"]: row["found_cases"] for row in coverage_rows}
            artifact_turns = connection.execute(
                """SELECT count(*) AS count FROM community_turn
                   WHERE created_at>=now()-make_interval(hours=>%s) AND jsonb_array_length(artifact_ids)>0""",
                (hours,),
            ).fetchone()["count"]
            cases = int(community["cases"])
            return {
                "windowHours": hours,
                "community": {"cases": cases, "published": community["published"], "resolved": community["resolved"],
                              "needsInformation": community["needs_information"],
                              "publicationRatePct": round(100.0 * community["published"] / cases, 1) if cases else 100.0},
                "chat": {"conversations": chat["conversations"], "active": chat["active"],
                         "resolved": chat["resolved"], "turns": turns,
                         "jobs": chat_jobs["jobs"], "jobsActive": chat_jobs["active"],
                         "jobsCompleted": chat_jobs["completed"],
                         "jobsDeadLetter": chat_jobs["dead_letter"], "jobsCancelled": chat_jobs["cancelled"]},
                "operations": {"failures": failures["failures"], "open": failures["open"],
                               "deadLetter": failures["dead_letter"], "recovered": failures["recovered"]},
                "sourceCoverage": {
                    "docCases": coverage.get("SHARED_DOCS", 0), "diploCases": coverage.get("CLOUD_DIPLO", 0),
                    "europaPreviewCases": coverage.get("CLOUD_EUROPA", 0),
                    "otherCodeCases": sum(value for key, value in coverage.items()
                                          if key not in {"SHARED_DOCS", "CLOUD_DIPLO", "CLOUD_EUROPA"}),
                },
                "artifacts": {"ingestedTurnsWithArtifacts": artifact_turns},
                "privacy": {"rawContentIncluded": False, "internalEvidenceExposed": False},
            }
