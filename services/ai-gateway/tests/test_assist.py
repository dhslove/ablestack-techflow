from __future__ import annotations

import base64
import gzip
from io import BytesIO
import json
import stat
import tempfile
import tarfile
from types import SimpleNamespace
import unittest
from uuid import uuid4
import zipfile

from fastapi.testclient import TestClient

from app.artifacts import ArtifactStore
from app.comprehensive import plan_query
from app.config import Settings
from app.main import create_app
from app.provider import ComprehensiveResponsesRequest, ContextChunk, ImageArtifact, LogArtifact
from app.responses import COMPREHENSIVE_SCHEMA, OpenAIResponsesAdapter
from app.store import InvalidBoundaryError, MemoryStore


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
CORRELATION = {"X-Correlation-Id": "assist-test-correlation-0001"}


class PlannerTest(unittest.TestCase):
    def test_cloud_branch_is_never_guessed(self) -> None:
        plan = plan_query("가상머신 배포가 실패합니다")
        self.assertEqual("NEEDS_INFORMATION", plan.state)
        self.assertIn("브랜치", plan.questions_needed[0])

    def test_multi_domain_plan_is_deterministic(self) -> None:
        plan = plan_query("europa VM의 RBD 스토리지 마이그레이션을 확인해줘")
        self.assertEqual("READY", plan.state)
        self.assertEqual(("CLOUD_EUROPA", "WALL_MAIN", "QEMU_EXEC_TOOLS_MAIN"), plan.profile_ids)


class ArtifactTest(unittest.TestCase):
    def test_store_validates_and_deletes_png(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root, retention_hours=1, max_bytes=1024 * 1024)
            record = store.put("screen.png", "image/png", PNG)
            self.assertEqual((1, 1), (record.width, record.height))
            self.assertEqual(PNG, store.image(record.artifact_id).data)
            self.assertTrue(store.delete(record.artifact_id))

    def test_media_type_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root, retention_hours=1, max_bytes=1024 * 1024)
            with self.assertRaises(InvalidBoundaryError):
                store.put("screen.jpg", "image/jpeg", PNG)

    def test_raw_upload_metadata_and_delete_api(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            settings = Settings(artifact_root=root)
            client = TestClient(create_app(settings, MemoryStore()))
            response = client.post("/v1/artifacts", content=PNG, headers={**CORRELATION, "Content-Type": "image/png", "X-Artifact-Filename": "screen.png", "X-Artifact-Classification": "D0"})
            self.assertEqual(201, response.status_code, response.text)
            artifact_id = response.json()["data"]["artifactId"]
            metadata = client.get(f"/v1/artifacts/{artifact_id}", headers=CORRELATION)
            self.assertEqual("image/png", metadata.json()["data"]["mediaType"])
            deleted = client.delete(f"/v1/artifacts/{artifact_id}", headers={**CORRELATION, "Idempotency-Key": "delete-artifact-test-0001"})
            self.assertTrue(deleted.json()["data"]["deleted"])

    def test_plain_log_is_secret_masked_and_line_addressable(self) -> None:
        data = b"2026-08-11 INFO starting\n2026-08-11 ERROR database timeout token=supersecret\n2026-08-11 INFO stopped\n"
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root, retention_hours=1, max_bytes=1024 * 1024)
            record = store.put("management.log", "text/plain", data)
            artifact = store.evidence(record.artifact_id)
            self.assertEqual("LOG", record.kind)
            self.assertEqual(1, record.entry_count)
            self.assertEqual(1, record.redaction_count)
            self.assertIsInstance(artifact, LogArtifact)
            self.assertIn("@@ management.log:1-3", artifact.evidence_text)
            self.assertIn("ERROR database timeout", artifact.evidence_text)
            self.assertIn("[REDACTED]", artifact.evidence_text)
            self.assertNotIn("supersecret", artifact.evidence_text)

    def test_zip_log_bundle_is_normalized_without_extracting_to_disk(self) -> None:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("management/server.log", "INFO ready\nERROR 530 insufficient capacity\n")
            archive.writestr("agent/agent.log.1", "WARN reconnect\n")
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root, retention_hours=1, max_bytes=1024 * 1024)
            record = store.put("support-logs.zip", "application/zip", buffer.getvalue())
            artifact = store.evidence(record.artifact_id)
            self.assertEqual(2, artifact.entry_count)
            self.assertIn("management/server.log", artifact.evidence_text)
            self.assertIn("agent/agent.log.1", artifact.evidence_text)

    def test_gzip_log_is_supported(self) -> None:
        payload = gzip.compress(b"INFO before\nFATAL service unavailable\n")
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root, retention_hours=1, max_bytes=1024 * 1024)
            artifact = store.evidence(store.put("mold-agent.log.gz", "application/gzip", payload).artifact_id)
            self.assertIn("FATAL service unavailable", artifact.evidence_text)

    def test_tar_gzip_log_bundle_is_supported(self) -> None:
        buffer = BytesIO()
        content = b"INFO agent start\nERROR libvirt connection refused\n"
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            info = tarfile.TarInfo("hosts/mold-agent.log")
            info.size = len(content)
            archive.addfile(info, BytesIO(content))
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root, retention_hours=1, max_bytes=1024 * 1024)
            artifact = store.evidence(store.put("support.tar.gz", "application/gzip", buffer.getvalue()).artifact_id)
            self.assertIn("hosts/mold-agent.log", artifact.evidence_text)
            self.assertIn("libvirt connection refused", artifact.evidence_text)

    def test_archive_path_traversal_is_rejected(self) -> None:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("../escape.log", "ERROR unsafe\n")
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root, retention_hours=1, max_bytes=1024 * 1024)
            with self.assertRaises(InvalidBoundaryError):
                store.put("unsafe.zip", "application/zip", buffer.getvalue())

    def test_archive_bomb_and_nested_archive_are_rejected(self) -> None:
        bomb = BytesIO()
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("repeated.log", "A" * 200_000)
        nested = BytesIO()
        with zipfile.ZipFile(nested, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("nested.log.gz", gzip.compress(b"ERROR hidden\n"))
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root, retention_hours=1, max_bytes=1024 * 1024)
            with self.assertRaises(InvalidBoundaryError):
                store.put("bomb.zip", "application/zip", bomb.getvalue())
            with self.assertRaises(InvalidBoundaryError):
                store.put("nested.zip", "application/zip", nested.getvalue())

    def test_archive_entry_count_and_symbolic_link_are_rejected(self) -> None:
        too_many = BytesIO()
        with zipfile.ZipFile(too_many, "w", zipfile.ZIP_STORED) as archive:
            for index in range(101):
                archive.writestr(f"node-{index}.log", "INFO ready\n")
        linked = BytesIO()
        with zipfile.ZipFile(linked, "w", zipfile.ZIP_STORED) as archive:
            info = zipfile.ZipInfo("linked.log")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "target.log")
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root, retention_hours=1, max_bytes=1024 * 1024)
            with self.assertRaises(InvalidBoundaryError):
                store.put("too-many.zip", "application/zip", too_many.getvalue())
            with self.assertRaises(InvalidBoundaryError):
                store.put("linked.zip", "application/zip", linked.getvalue())

    def test_zip_special_file_and_embedded_drive_path_are_rejected(self) -> None:
        special = BytesIO()
        with zipfile.ZipFile(special, "w", zipfile.ZIP_STORED) as archive:
            info = zipfile.ZipInfo("pipe.log")
            info.create_system = 3
            info.external_attr = (stat.S_IFIFO | 0o600) << 16
            archive.writestr(info, "ERROR blocked\n")
        drive_path = BytesIO()
        with zipfile.ZipFile(drive_path, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("logs/C:/escaped.log", "ERROR blocked\n")
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root, retention_hours=1, max_bytes=1024 * 1024)
            with self.assertRaises(InvalidBoundaryError):
                store.put("special.zip", "application/zip", special.getvalue())
            with self.assertRaises(InvalidBoundaryError):
                store.put("drive.zip", "application/zip", drive_path.getvalue())

    def test_binary_log_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root, retention_hours=1, max_bytes=1024 * 1024)
            with self.assertRaises(InvalidBoundaryError):
                store.put("binary.log", "text/plain", b"INFO\x00ERROR\n")

    def test_log_upload_api_returns_normalization_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            client = TestClient(create_app(Settings(artifact_root=root), MemoryStore()))
            response = client.post(
                "/v1/artifacts", content=b"INFO start\nERROR failed\n",
                headers={**CORRELATION, "Content-Type": "text/plain", "X-Artifact-Filename": "service.log", "X-Artifact-Classification": "D0"},
            )
            self.assertEqual(201, response.status_code, response.text)
            self.assertEqual("LOG", response.json()["data"]["kind"])
            self.assertEqual(1, response.json()["data"]["entryCount"])

    def test_octet_stream_log_is_content_validated_and_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root, retention_hours=1, max_bytes=1024 * 1024)
            record = store.put("service.log", "application/octet-stream", b"INFO start\nERROR stopped\n")
            self.assertEqual("text/plain", record.media_type)
            self.assertEqual("LOG", record.kind)


class _Responses:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            output_text='{"state":"ANSWERED","summary":"ok","observedFacts":[],"diagnoses":[],"recommendedActions":[],"unknowns":[],"confidence":"HIGH","citationsUsed":["chunk-1"],"artifactEvidence":[{"artifactId":"artifact-1","finding":"visible","region":"all"}],"currentAssessment":"CURRENT_DEFECT","previewAssessment":"PREVIEW_IMPROVED","previewGuidance":"개선 중","abstainReason":null}',
            model="gpt-5.6-sol", id="resp", _request_id="req",
        )


class _RetryResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            output = '{"state":"ANSWERED","summary":"retry","observedFacts":[],"diagnoses":[{"title":"x","likelihood":"LOW","evidenceIds":["invented-id"]}],"recommendedActions":[],"unknowns":[],"confidence":"LOW","citationsUsed":["invented-id"],"artifactEvidence":[],"currentAssessment":"INSUFFICIENT_EVIDENCE","previewAssessment":"PREVIEW_INSUFFICIENT","previewGuidance":null,"abstainReason":null}'
        else:
            output = '{"state":"ANSWERED","summary":"ok","observedFacts":[],"diagnoses":[{"title":"x","likelihood":"LOW","evidenceIds":["chunk-1","artifact-1"]}],"recommendedActions":[],"unknowns":[],"confidence":"LOW","citationsUsed":["chunk-1"],"artifactEvidence":[{"artifactId":"artifact-1","finding":"error","region":"server.log:1-1"}],"currentAssessment":"CURRENT_DEFECT","previewAssessment":"PREVIEW_NOT_FOUND","previewGuidance":"보완 필요","abstainReason":null}'
        return SimpleNamespace(output_text=output, model="gpt-5.6-sol", id="resp", _request_id="req")


class ComprehensiveOpenAITest(unittest.TestCase):
    def test_image_is_original_detail_and_storage_tools_are_disabled(self) -> None:
        responses = _Responses()
        adapter = OpenAIResponsesAdapter("unused", "unused", client=SimpleNamespace(responses=responses))
        context = (ContextChunk("chunk-1", "D0", "ablecloud-team/ablestack-docs", "main", "a" * 40, "guide.md", "doc", source_profile_id="SHARED_DOCS", source_kind="DOCUMENTATION"),)
        artifact = ImageArtifact("artifact-1", "image/png", PNG, "digest")
        result = adapter.generate_comprehensive(ComprehensiveResponsesRequest("query", "question", context, (artifact,), safety_identifier="tf-" + "a" * 61))
        user_content = responses.kwargs["input"][1]["content"]
        text_payload = json.loads(user_content[0]["text"])
        self.assertEqual("artifact-1", text_payload["artifacts"][0]["artifactId"])
        self.assertEqual(1, text_payload["context"][0]["evidencePriority"])
        self.assertEqual("ABLESTACK_DOCUMENTATION", text_payload["context"][0]["evidenceTier"])
        self.assertEqual("original", user_content[1]["detail"])
        self.assertTrue(user_content[1]["image_url"].startswith("data:image/png;base64,"))
        self.assertFalse(responses.kwargs["store"])
        self.assertEqual([], responses.kwargs["tools"])
        self.assertEqual(COMPREHENSIVE_SCHEMA, responses.kwargs["text"]["format"]["schema"])
        self.assertEqual("ANSWERED", result.report["state"])

    def test_log_evidence_is_normalized_text_not_a_raw_provider_file(self) -> None:
        responses = _Responses()
        adapter = OpenAIResponsesAdapter("unused", "unused", client=SimpleNamespace(responses=responses))
        context = (ContextChunk("chunk-1", "D0", "ablecloud-team/ablestack-cloud", "ablestack-europa", "a" * 40, "x.java", "code"),)
        artifact = LogArtifact("artifact-1", "application/zip", "digest", "@@ server.log:1-1\n1: ERROR failed\n", 1, 32, False, 0)
        result = adapter.generate_comprehensive(ComprehensiveResponsesRequest("query", "question", context, (artifact,), safety_identifier="tf-" + "a" * 61))
        user_content = responses.kwargs["input"][1]["content"]
        payload = json.loads(user_content[0]["text"])
        self.assertEqual("LOG", payload["artifacts"][0]["kind"])
        self.assertEqual("artifact-1", payload["logEvidence"][0]["artifactId"])
        self.assertIn("server.log:1-1", payload["logEvidence"][0]["text"])
        self.assertEqual(1, len(user_content))
        self.assertEqual("ANSWERED", result.report["state"])

    def test_invalid_evidence_identifiers_are_retried_once_with_exact_contract(self) -> None:
        responses = _RetryResponses()
        adapter = OpenAIResponsesAdapter("unused", "unused", client=SimpleNamespace(responses=responses))
        context = (ContextChunk("chunk-1", "D0", "ablecloud-team/ablestack-cloud", "ablestack-europa", "a" * 40, "x.java", "code"),)
        artifact = LogArtifact("artifact-1", "text/plain", "digest", "@@ server.log:1-1\n1: ERROR failed\n", 1, 32, False, 0)
        result = adapter.generate_comprehensive(ComprehensiveResponsesRequest("query", "question", context, (artifact,), safety_identifier="tf-" + "a" * 61))
        self.assertEqual(2, len(responses.calls))
        self.assertIn("CONTRACT RETRY", responses.calls[1]["input"][0]["content"])
        self.assertEqual(5000, responses.calls[1]["max_output_tokens"])
        self.assertEqual("ANSWERED", result.report["state"])


if __name__ == "__main__":
    unittest.main()
