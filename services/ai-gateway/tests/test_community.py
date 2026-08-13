from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from app.community import FlarumClient, format_draft, profiles_for_tags
from app.config import Settings
from app.main import create_app
from app.store import MemoryStore


HEADERS = {"X-Correlation-Id": "community-test-0001", "Idempotency-Key": "community-test-idempotency-0001"}


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


class CommunityTests(unittest.TestCase):
    def payload(self) -> dict:
        return {
            "discussionId": "901", "discussionUrl": "https://community.ablecloud.io/d/901",
            "title": "VM 배포가 실패합니다", "question": "어떤 로그를 확인해야 하나요?",
            "authorId": "42", "tagSlugs": ["mold"], "artifactIds": [],
        }

    def test_tag_mapping_is_deterministic(self) -> None:
        self.assertEqual(["CLOUD_DIPLO", "SHARED_DOCS"], profiles_for_tags(["mold", "cube", "mold"]))
        self.assertEqual(["SHARED_DOCS"], profiles_for_tags(["unknown-tag"]))

    def test_format_draft_is_safe_public_projection(self) -> None:
        draft = format_draft({
            "state": "ANSWERED", "report": {"summary": "원인을 확인했습니다.", "observedFacts": ["오류가 있습니다."],
                "currentAssessment": "CURRENT_DEFECT", "previewAssessment": "PREVIEW_IMPROVED",
                "previewGuidance": "개선 검증이 진행 중입니다."},
            "citations": [{"repository": "ablecloud-team/ablestack-docs", "commit": "a" * 40,
                           "path": "docs/test.md", "startLine": 1, "endLine": 3}],
        })
        self.assertIn("ABLESTACK 트러블슈팅 가이드", draft)
        self.assertIn("### 적용 버전", draft)
        self.assertIn("개선이 진행 중", draft)
        self.assertNotIn("github.com", draft)
        self.assertNotIn("docs/test.md", draft)
        self.assertNotIn("a" * 40, draft)

    def test_case_requires_approval_before_publish(self) -> None:
        client = TestClient(create_app(Settings(), MemoryStore()))
        created = client.post("/v1/community/cases", headers=HEADERS, json=self.payload())
        self.assertEqual(201, created.status_code)
        case = created.json()["data"]
        self.assertEqual("DRAFT_PENDING", case["state"])
        by_discussion = client.get("/v1/community/discussions/901/case", headers=HEADERS)
        self.assertEqual(case["caseId"], by_discussion.json()["data"]["caseId"])
        publish = client.post(
            f"/v1/community/cases/{case['caseId']}/publish",
            headers={**HEADERS, "Idempotency-Key": "community-publish-before-approval"},
            json={"requestedBy": "dhslove"},
        )
        self.assertEqual(409, publish.status_code)

    def test_edited_answer_can_be_approved_but_disabled_publish_fails_closed(self) -> None:
        client = TestClient(create_app(Settings(), MemoryStore()))
        case = client.post("/v1/community/cases", headers=HEADERS, json=self.payload()).json()["data"]
        approved = client.post(
            f"/v1/community/cases/{case['caseId']}/decision",
            headers={**HEADERS, "Idempotency-Key": "community-approve-idempotency-0001"},
            json={"decision": "APPROVE", "reviewer": "dhslove", "expectedDraftVersion": 1,
                  "editedAnswer": "담당자가 검토한 답변입니다.", "note": "test"},
        )
        self.assertEqual("APPROVED", approved.json()["data"]["state"])
        publish = client.post(
            f"/v1/community/cases/{case['caseId']}/publish",
            headers={**HEADERS, "Idempotency-Key": "community-publish-idempotency-0001"},
            json={"requestedBy": "dhslove"},
        )
        self.assertEqual(400, publish.status_code)

    def test_empty_visual_flow_edit_uses_existing_draft(self) -> None:
        store = MemoryStore()
        case = store.create_community_case(
            self.payload(),
            {"draftAnswer": "기존 AI 답변 초안", "answerState": "ANSWERED", "citations": []},
            "community-empty-edit-case-0001",
            "community-empty-edit-correlation",
        )
        client = TestClient(create_app(Settings(), store))
        approved = client.post(
            f"/v1/community/cases/{case['caseId']}/decision",
            headers={**HEADERS, "Idempotency-Key": "community-approve-empty-edit-0001"},
            json={"decision": "APPROVE", "reviewer": "chat:ceo", "expectedDraftVersion": 1,
                  "editedAnswer": "", "note": "visual flow optional field"},
        )
        self.assertEqual(200, approved.status_code)
        self.assertEqual("APPROVED", approved.json()["data"]["state"])
        self.assertEqual(case["draftAnswer"], approved.json()["data"]["draftAnswer"])
        retried = client.post(
            f"/v1/community/cases/{case['caseId']}/decision",
            headers={**HEADERS, "Idempotency-Key": "community-approve-empty-edit-retry-0001"},
            json={"decision": "APPROVE", "reviewer": "chat:ceo", "expectedDraftVersion": 1,
                  "editedAnswer": "", "note": "publish retry"},
        )
        self.assertEqual(200, retried.status_code)
        self.assertEqual(1, retried.json()["data"]["approvalVersion"])

    def test_rejected_case_cannot_publish(self) -> None:
        client = TestClient(create_app(Settings(), MemoryStore()))
        case = client.post("/v1/community/cases", headers=HEADERS, json=self.payload()).json()["data"]
        rejected = client.post(
            f"/v1/community/cases/{case['caseId']}/decision",
            headers={**HEADERS, "Idempotency-Key": "community-reject-idempotency-0001"},
            json={"decision": "REJECT", "reviewer": "dhslove", "expectedDraftVersion": 1, "note": "unsafe"},
        )
        self.assertEqual("REJECTED", rejected.json()["data"]["state"])

    def test_already_published_case_is_returned_without_reposting(self) -> None:
        store = MemoryStore()
        client = TestClient(create_app(Settings(), store))
        case = client.post("/v1/community/cases", headers=HEADERS, json=self.payload()).json()["data"]
        client.post(
            f"/v1/community/cases/{case['caseId']}/decision",
            headers={**HEADERS, "Idempotency-Key": "community-approve-replay-test"},
            json={"decision": "APPROVE", "reviewer": "dhslove", "expectedDraftVersion": 1,
                  "editedAnswer": "검토된 답변", "note": "test"},
        )
        store.mark_community_published(
            UUID(case["caseId"]),
            {"postId": "311", "postUrl": "https://community.ablecloud.io/d/142/311"},
            "community-published-replay-test",
        )
        repeated = client.post(
            f"/v1/community/cases/{case['caseId']}/publish",
            headers={**HEADERS, "Idempotency-Key": "community-publish-replay-test"},
            json={"requestedBy": "dhslove"},
        )
        self.assertEqual(200, repeated.status_code)
        self.assertEqual("311", repeated.json()["data"]["publishedPostId"])

    def test_flarum_publish_reuses_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "key"
            key_file.write_text("a" * 40)
            client = FlarumClient(
                "http://172.16.0.234", "https://community.ablecloud.io", str(key_file), True
            )
            with patch("urllib.request.urlopen", return_value=FakeResponse({
                "data": [{"id": "77", "attributes": {"contentHtml": "<!-- marker -->"}}]
            })) as opened:
                result = client.publish_reply("901", "answer", "<!-- marker -->")
            self.assertTrue(result["reused"])
            self.assertTrue(result["postUrl"].startswith("https://community.ablecloud.io/"))
            self.assertEqual(1, opened.call_count)

    def test_assistant_review_reply_is_held_for_moderator_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "key"
            user_file = Path(directory) / "assistant-user-id"
            key_file.write_text("a" * 40, encoding="utf-8")
            user_file.write_text("40", encoding="utf-8")
            client = FlarumClient(
                "http://172.16.0.234", "https://community.ablecloud.io", str(key_file), False,
                str(user_file), True,
            )
            responses = [
                FakeResponse({"data": []}),
                FakeResponse({"data": {"id": "88", "attributes": {"isApproved": False}}}),
            ]
            with patch("urllib.request.urlopen", side_effect=responses) as opened:
                result = client.publish_review_reply("901", "전체 검토 답변", "<!-- review -->")
            self.assertFalse(result["isApproved"])
            self.assertEqual("88", result["postId"])
            create_request = opened.call_args_list[1].args[0]
            self.assertEqual("Token " + "a" * 40 + "; userId=40", create_request.headers["Authorization"])

    def test_memory_case_tracks_flarum_review_approval(self) -> None:
        store = MemoryStore()
        case = store.create_community_case(
            self.payload(), {"draftAnswer": "전체 답변", "answerState": "ANSWERED", "citations": []},
            "review-case-create", "review-case-correlation",
        )
        attached = store.attach_community_review(
            case["caseId"], {"postId": "88", "postUrl": "https://community.ablecloud.io/d/901/88"},
            "review-case-attach",
        )
        self.assertEqual("DRAFT_PENDING", attached["state"])
        self.assertEqual("88", attached["reviewPostId"])
        approved = store.mark_community_review_approved(case["caseId"], "review-case-approved")
        self.assertEqual("PUBLISHED", approved["state"])
        self.assertEqual("flarum:moderator", approved["reviewer"])


if __name__ == "__main__":
    unittest.main()
