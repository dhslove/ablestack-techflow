from __future__ import annotations

import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.source_policy import TreeEntry
from app.store import MemoryStore


CORRELATION = "test-correlation-0001"
HEADERS = {"X-Correlation-Id": CORRELATION, "Idempotency-Key": "test-idempotency-0001"}


class FakeSnapshot:
    commit = "a" * 40
    tree_sha = "c" * 40

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def entries(self):
        return [TreeEntry("src/main.py", "b" * 40, "blob", "100644", 12)]

    def read_blob(self, object_id: str) -> bytes:
        self.last_object_id = object_id
        return b"print('ok')\n"


class FakeFetcher:
    def resolve_head(self, profile):
        return "a" * 40

    def open_snapshot(self, profile, commit):
        assert commit == "a" * 40
        return FakeSnapshot()


class ApiContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app(Settings(), MemoryStore(), FakeFetcher()))

    @staticmethod
    def source_body(profile: str = "CLOUD_MAIN") -> dict[str, object]:
        return {
            "sourceProfileId": profile,
            "repository": "ablecloud-team/ablestack-cloud",
            "branch": "main",
            "commit": "a" * 40,
            "sourceKind": "SOURCE_CODE",
            "classification": "D0",
            "licenseSpdx": "Apache-2.0",
        }

    def create_source(self, key: str = "test-create-source-0001") -> dict[str, object]:
        response = self.client.post(
            "/v1/sources",
            json=self.source_body(),
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": key},
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()["data"]

    def scan_source(self, source: dict[str, object]) -> dict[str, object]:
        response = self.client.post(
            f"/v1/source-versions/{source['sourceVersionId']}/scan",
            json={"scannedBy": "source-fetcher"},
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": f"test-scan-{source['sourceVersionId']}"},
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()["data"]

    def approve_source(self, source: dict[str, object]) -> dict[str, object]:
        response = self.client.post(
            f"/v1/source-versions/{source['sourceVersionId']}/approve",
            json={"approvedBy": "dhslove", "expectedCommit": source["commit"]},
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": f"test-approve-{source['sourceVersionId']}"},
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()["data"]

    def test_health_exposes_mock_profiles_without_secrets(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual(3, len(body["data"]["providerProfiles"]))
        self.assertEqual("disabled", body["data"]["officialWebSearch"])
        self.assertNotIn("credential", response.text.lower())

    def test_guest_os_question_fails_closed_when_required_official_search_is_disabled(self) -> None:
        response = self.client.post(
            "/v1/assist/query",
            headers={"X-Correlation-Id": CORRELATION},
            json={
                "queryId": str(uuid4()),
                "question": "Debian 12 가상머신에서 SMB 공유를 마운트하는 명령을 알려주세요.",
                "actorId": "test-guest-os",
                "productVersion": "diplo",
                "artifactIds": [],
                "locale": "ko-KR",
                "classification": "D0",
            },
        )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("FAILED", response.json()["data"]["state"])
        self.assertEqual("OFFICIAL_WEB_SEARCH_DISABLED", response.json()["data"]["errorCode"])

    def test_missing_correlation_is_rejected(self) -> None:
        response = self.client.get(f"/v1/sources/{uuid4()}")
        self.assertEqual(400, response.status_code)
        self.assertEqual("INVALID_CORRELATION_ID", response.json()["error"]["code"])

    def test_missing_idempotency_is_rejected(self) -> None:
        response = self.client.post("/v1/sources", json=self.source_body(), headers={"X-Correlation-Id": CORRELATION})
        self.assertEqual(400, response.status_code)
        self.assertEqual("INVALID_BOUNDARY", response.json()["error"]["code"])

    def test_create_get_and_approve_source(self) -> None:
        source = self.create_source()
        get_response = self.client.get(
            f"/v1/sources/{source['sourceId']}", headers={"X-Correlation-Id": CORRELATION}
        )
        self.assertEqual("REGISTERED", get_response.json()["data"]["state"])
        self.assertEqual("QUARANTINED", self.scan_source(source)["state"])
        approved = self.approve_source(source)
        self.assertEqual("APPROVED", approved["state"])

    def test_create_source_is_idempotent(self) -> None:
        first = self.create_source("test-create-source-repeat")
        second = self.create_source("test-create-source-repeat")
        self.assertEqual(first["sourceId"], second["sourceId"])

    def test_ingestion_job_contract(self) -> None:
        source = self.create_source("test-create-source-ingest")
        self.scan_source(source)
        self.approve_source(source)
        response = self.client.post(
            f"/v1/sources/{source['sourceId']}/ingestions",
            json={"requestedBy": "activepieces"},
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": "test-ingestion-job-0001"},
        )
        self.assertEqual(202, response.status_code, response.text)
        job = response.json()["data"]
        self.assertEqual(CORRELATION, job["correlationId"])
        status_response = self.client.get(
            f"/v1/jobs/{job['jobId']}", headers={"X-Correlation-Id": CORRELATION}
        )
        self.assertEqual("PENDING", status_response.json()["data"]["state"])
        complete = self.client.post(
            f"/v1/jobs/{job['jobId']}/complete",
            json={"succeeded": True, "indexedFileCount": 1},
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": "test-complete-job-0001"},
        )
        self.assertEqual(200, complete.status_code, complete.text)
        self.assertEqual("ACTIVE", self.client.get(
            f"/v1/source-versions/{source['sourceVersionId']}", headers={"X-Correlation-Id": CORRELATION}
        ).json()["data"]["state"])
        repeated_scan = self.client.post(
            f"/v1/source-versions/{source['sourceVersionId']}/scan",
            json={"scannedBy": "activepieces"},
            headers={"X-Correlation-Id": CORRELATION,
                     "Idempotency-Key": f"test-repeat-scan-{source['sourceVersionId']}"},
        )
        self.assertEqual(200, repeated_scan.status_code, repeated_scan.text)
        self.assertEqual("ACTIVE", repeated_scan.json()["data"]["state"])

    def test_compatibility_set_accepts_only_approved_version(self) -> None:
        source = self.create_source("test-create-source-compat")
        self.scan_source(source)
        approved = self.approve_source(source)
        job = self.client.post(
            f"/v1/sources/{source['sourceId']}/ingestions",
            json={"requestedBy": "indexer"},
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": "test-ingest-compat"},
        ).json()["data"]
        self.client.post(
            f"/v1/jobs/{job['jobId']}/complete", json={"succeeded": True, "indexedFileCount": 1},
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": "test-complete-compat"},
        )
        response = self.client.post(
            "/v1/compatibility-sets",
            json={
                "name": "ABLESTACK Main Baseline",
                "product": "ABLESTACK",
                "productVersion": "main",
                "members": [{"sourceVersionId": approved["sourceVersionId"], "required": True}],
            },
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": "test-compatibility-set"},
        )
        self.assertEqual(201, response.status_code, response.text)
        self.assertEqual("APPROVED", response.json()["data"]["state"])

    def test_query_returns_grounded_mock_answer(self) -> None:
        source = self.create_source("test-create-source-query")
        self.scan_source(source)
        self.approve_source(source)
        job = self.client.post(
            f"/v1/sources/{source['sourceId']}/ingestions", json={"requestedBy": "indexer"},
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": "test-ingest-query"},
        ).json()["data"]
        run = self.client.post(
            f"/v1/jobs/{job['jobId']}/run", json={"requestedBy": "indexer"},
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": "test-run-query-index"},
        )
        self.assertEqual(200, run.status_code, run.text)
        response = self.client.post(
            "/v1/rag/query",
            json={
                "queryId": str(uuid4()),
                "question": "ABLESTACK 상태를 설명해줘",
                "actorId": "test-user",
                "sourceProfileIds": ["CLOUD_MAIN"],
                "classification": "D0",
            },
            headers={"X-Correlation-Id": CORRELATION},
        )
        self.assertEqual(200, response.status_code, response.text)
        data = response.json()["data"]
        self.assertEqual("ANSWERED", data["state"])
        self.assertFalse(data["retrievalProviderCalled"])
        self.assertFalse(data["generationProviderCalled"])
        self.assertIsNone(data["abstainReason"])
        self.assertGreaterEqual(len(data["citations"]), 1)
        self.assertEqual("SOURCE_CODE", data["citations"][0]["sourceKind"])
        self.assertNotIn("content", response.text)
        calls = self.client.app.state.store._provider_calls
        self.assertEqual("responses-api", calls[-1]["surface"])
        self.assertNotIn("question", calls[-1])

    def test_retrieve_returns_commit_pinned_citation(self) -> None:
        source = self.create_source("test-create-source-retrieve")
        self.scan_source(source)
        self.approve_source(source)
        job = self.client.post(
            f"/v1/sources/{source['sourceId']}/ingestions", json={"requestedBy": "indexer"},
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": "test-ingest-retrieve"},
        ).json()["data"]
        self.client.post(
            f"/v1/jobs/{job['jobId']}/run", json={"requestedBy": "indexer"},
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": "test-run-retrieve"},
        )
        response = self.client.post(
            "/v1/rag/retrieve",
            json={"queryId": str(uuid4()), "question": "src/main.py print ok", "sourceProfileIds": ["CLOUD_MAIN"]},
            headers={"X-Correlation-Id": CORRELATION},
        )
        self.assertEqual(200, response.status_code, response.text)
        result = response.json()["data"]["results"][0]
        self.assertEqual("a" * 40, result["commit"])
        self.assertEqual("src/main.py", result["path"])
        self.assertIn("implementation", result["channels"])

    def test_query_requires_exactly_one_scope(self) -> None:
        response = self.client.post(
            "/v1/rag/query",
            json={"queryId": str(uuid4()), "question": "question", "actorId": "test-user"},
            headers={"X-Correlation-Id": CORRELATION},
        )
        self.assertEqual(422, response.status_code)

    def test_validation_response_does_not_echo_question(self) -> None:
        sensitive = "do-not-echo-this-question"
        response = self.client.post(
            "/v1/rag/query",
            json={"queryId": "invalid", "question": sensitive, "actorId": "test-user",
                  "sourceProfileIds": ["CLOUD_MAIN"]},
            headers={"X-Correlation-Id": CORRELATION},
        )
        self.assertEqual(422, response.status_code)
        self.assertNotIn(sensitive, response.text)
        self.assertEqual(len(response.content), int(response.headers["content-length"]))

    def test_withdrawal_creates_deletion_job(self) -> None:
        source = self.create_source("test-create-source-delete")
        response = self.client.delete(
            f"/v1/sources/{source['sourceId']}",
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": "test-delete-source-0001"},
        )
        self.assertEqual(202, response.status_code)
        self.assertEqual("DELETION", response.json()["data"]["jobType"])

    def test_evaluation_run_contract(self) -> None:
        response = self.client.post(
            "/v1/evaluations/runs",
            json={
                "name": "Issue 41 Contract",
                "sourceProfileIds": ["CLOUD_MAIN"],
                "providerProfileId": "OPENAI_RAG_DEFAULT_V1",
                "requestedBy": "evaluator",
            },
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": "test-evaluation-run"},
        )
        self.assertEqual(202, response.status_code, response.text)
        run_id = response.json()["data"]["runId"]
        self.assertEqual(CORRELATION, response.json()["data"]["correlationId"])
        get_response = self.client.get(
            f"/v1/evaluations/runs/{run_id}", headers={"X-Correlation-Id": CORRELATION}
        )
        self.assertEqual("PENDING", get_response.json()["data"]["state"])
        execute = self.client.post(
            f"/v1/evaluations/runs/{run_id}/execute",
            json={"caseSetId": "ABLESTACK_GOLDEN_V1", "requestedBy": "evaluator"},
            headers={"X-Correlation-Id": CORRELATION},
        )
        self.assertEqual(202, execute.status_code, execute.text)
        completed = self.client.get(
            f"/v1/evaluations/runs/{run_id}", headers={"X-Correlation-Id": CORRELATION}
        ).json()["data"]
        self.assertEqual("SUCCEEDED", completed["state"])
        results = self.client.get(
            f"/v1/evaluations/runs/{run_id}/results", headers={"X-Correlation-Id": CORRELATION}
        ).json()["data"]
        self.assertEqual(completed["totalCases"], len(results))
        self.assertTrue(all("caseKey" in item and "passed" in item for item in results))

    def test_registry_contains_nine_profiles_and_discovery_is_registered(self) -> None:
        profiles = self.client.get("/v1/source-profiles", headers={"X-Correlation-Id": CORRELATION})
        self.assertEqual(9, len(profiles.json()["data"]))
        discovered = self.client.post(
            "/v1/source-profiles/CLOUD_EUROPA/discoveries",
            json={"detectedBy": "activepieces"},
            headers={"X-Correlation-Id": CORRELATION, "Idempotency-Key": "test-discover-europa"},
        )
        self.assertEqual(201, discovered.status_code, discovered.text)
        self.assertEqual("ablestack-europa", discovered.json()["data"]["branch"])
        self.assertEqual("REGISTERED", discovered.json()["data"]["state"])
        mirrors = self.client.get("/v1/source-mirrors", headers={"X-Correlation-Id": CORRELATION})
        self.assertEqual(7, len(mirrors.json()["data"]))
        cloud = next(item for item in mirrors.json()["data"] if item["repository"].endswith("ablestack-cloud"))
        self.assertEqual("HEALTHY", cloud["state"])
        self.assertEqual("a" * 40, cloud["lastHeadCommit"])

    def test_openapi_contains_thirty_nine_operations(self) -> None:
        schema = self.client.get("/openapi.json").json()
        operations = [
            operation
            for path in schema["paths"].values()
            for method, operation in path.items()
            if method.lower() in {"get", "post", "delete", "put", "patch"}
        ]
        self.assertEqual(39, len(operations))
        self.assertEqual(39, len({operation["operationId"] for operation in operations}))

    def test_all_responses_disable_cache_and_echo_correlation(self) -> None:
        response = self.client.get("/v1/jobs/00000000-0000-0000-0000-000000000000", headers={"X-Correlation-Id": CORRELATION})
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertEqual(CORRELATION, response.headers["x-correlation-id"])


if __name__ == "__main__":
    unittest.main()
