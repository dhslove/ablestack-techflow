from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.community import FlarumClient, FlarumResourceNotFound, conversationalize_answer, format_draft, profiles_for_tags
from app.versioned_assist import format_knowledge_base
from app.config import Settings
from app.main import _available_conversation_artifact_ids, _resolution_administrator_ids, create_app
from app.store import KB_SOLUTION_CONFIRMED_EVENT, MemoryStore, NotFoundError


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
        self.assertTrue(draft.startswith("원인을 확인했습니다."))
        self.assertNotIn("## ABLESTACK 트러블슈팅 가이드", draft)
        self.assertNotIn("### 적용 버전", draft)
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

    def test_attachment_processing_warning_does_not_modify_stored_question(self) -> None:
        store = MemoryStore()
        client = TestClient(create_app(Settings(), store))
        payload = {
            **self.payload(),
            "artifactWarnings": ["첨부자료가 본문에 있지만 분석 대상으로 가져오지 못했습니다."],
        }
        created = client.post(
            "/v1/community/cases",
            headers={**HEADERS, "Idempotency-Key": "community-warning-original-question"},
            json=payload,
        )
        self.assertEqual(201, created.status_code)
        turns = store.list_community_turns("901")
        self.assertEqual(self.payload()["question"], turns[0]["content"])
        self.assertNotIn("[첨부 처리 안내]", turns[0]["content"])

    def test_staff_reply_is_recorded_without_creating_an_ai_draft(self) -> None:
        store = MemoryStore()
        client = TestClient(create_app(Settings(), store))
        created = client.post(
            "/v1/community/cases",
            headers={**HEADERS, "Idempotency-Key": "community-staff-silence-first"},
            json={**self.payload(), "postId": "100", "postNumber": 1},
        )
        self.assertEqual(201, created.status_code, created.text)
        case = created.json()["data"]

        response = client.post(
            "/v1/community/cases",
            headers={**HEADERS, "Idempotency-Key": "community-staff-silence-second"},
            json={
                **self.payload(),
                "question": "관리자가 질문자에게 직접 안내했습니다.",
                "postId": "101", "postNumber": 2, "postAuthorId": "7",
                "turnRole": "STAFF", "responseRequested": False,
                "responseReason": "STAFF_RECORDED",
            },
        )

        self.assertEqual(201, response.status_code, response.text)
        result = response.json()["data"]
        self.assertEqual(1, result["draftVersion"])
        self.assertEqual("101", result["lastSeenPostId"])
        self.assertTrue(result["turnCreated"])
        self.assertEqual(["100", "101"], [item["sourcePostId"] for item in store.list_community_turns("901")])
        events = store.list_community_case_events(UUID(case["caseId"]), 10)
        recorded = next(item for item in events if item["eventType"] == "TURN_RECORDED")
        self.assertEqual("STAFF_RECORDED", recorded["details"]["responseReason"])

    def test_legacy_flow_infers_staff_suppression_reason(self) -> None:
        store = MemoryStore()
        first = {
            **self.payload(), "postId": "100", "postNumber": 1,
            "postAuthorId": "42", "turnRole": "REQUESTER", "responseRequested": True,
        }
        case = store.create_community_case(
            first,
            {"draftAnswer": "초기 답변", "answerState": "ANSWERED", "citations": []},
            "community-legacy-reason-first", "community-legacy-reason-correlation",
        )
        client = TestClient(create_app(Settings(), store))

        response = client.post(
            "/v1/community/cases",
            headers={**HEADERS, "Idempotency-Key": "community-legacy-reason-staff"},
            json={
                **self.payload(), "question": "관리자가 직접 답변했습니다.",
                "postId": "101", "postNumber": 2, "postAuthorId": "7",
                "turnRole": "STAFF", "responseRequested": False,
            },
        )

        self.assertEqual(201, response.status_code, response.text)
        events = store.list_community_case_events(case["caseId"], 10)
        recorded = next(item for item in events if item["eventType"] == "TURN_RECORDED")
        self.assertEqual("STAFF_RECORDED", recorded["details"]["responseReason"])

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

    def test_flarum_idempotency_marker_is_not_visible_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "key"
            assistant_file = Path(directory) / "assistant"
            key_file.write_text("a" * 40)
            assistant_file.write_text("40")
            client = FlarumClient(
                "http://172.16.0.234", "https://community.ablecloud.io", str(key_file), True,
                str(assistant_file), False,
            )
            marker = "<!-- techflow-answer:case:v1 -->"
            responses = [
                FakeResponse({"data": []}),
                FakeResponse({"data": {"id": "78", "attributes": {"isApproved": True}}}),
            ]
            with patch("urllib.request.urlopen", side_effect=responses) as opened:
                client.publish_assistant_reply("901", "친절한 답변입니다.", marker)
            posted = json.loads(opened.call_args_list[1].args[0].data.decode("utf-8"))
            content = posted["data"]["attributes"]["content"]
            self.assertNotIn(marker, content)
            self.assertIn("/_techflow/", content)
            self.assertIn("\u200b", content)

    def test_legacy_sectioned_draft_becomes_a_friendly_reply(self) -> None:
        answer = conversationalize_answer(
            "### 증상\n- 콘솔이 연결중에서 멈춥니다.\n\n"
            "### 원인\n- 이전 VNC 연결이 남아 있을 수 있습니다.\n\n"
            "### 해결 방법\n- 먼저 라이브 마이그레이션을 실행합니다.\n\n"
            "### 추가로 필요한 정보\n- 조치 결과를 알려주세요."
        )
        self.assertTrue(answer.startswith("말씀해 주신 현상을 확인해 보겠습니다."))
        self.assertIn("먼저 다음 해결 방법을 적용해 보세요.", answer)
        self.assertLess(answer.index("먼저 다음 해결 방법"), answer.index("이 방법을 먼저 권장하는 이유"))
        self.assertIn("위 조치로 해결되지 않으면 아래 결과를 알려주세요.", answer)
        self.assertNotIn("###", answer)

    def test_assistant_reply_is_automatically_made_public(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "key"
            user_file = Path(directory) / "assistant-user-id"
            selector_file = Path(directory) / "solution-selector-user-id"
            key_file.write_text("a" * 40, encoding="utf-8")
            user_file.write_text("40", encoding="utf-8")
            selector_file.write_text("1", encoding="utf-8")
            client = FlarumClient(
                "http://172.16.0.234", "https://community.ablecloud.io", str(key_file), True,
                str(user_file), False, str(selector_file),
            )
            responses = [
                FakeResponse({"data": []}),
                FakeResponse({"data": {"id": "89", "attributes": {"isApproved": False}}}),
                FakeResponse({"data": {"id": "89", "attributes": {"isApproved": True}}}),
            ]
            with patch("urllib.request.urlopen", side_effect=responses) as opened:
                result = client.publish_assistant_reply("901", "친절한 답변", "<!-- answer -->")
            self.assertTrue(result["isApproved"])
            self.assertEqual("https://community.ablecloud.io/d/901/89", result["postUrl"])
            self.assertEqual("PATCH", opened.call_args_list[2].args[0].method)
            self.assertEqual(
                "Token " + "a" * 40 + "; userId=1",
                opened.call_args_list[2].args[0].headers["Authorization"],
            )

    def test_knowledge_base_post_is_selected_and_verified_as_solution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "key"
            selector_file = Path(directory) / "solution-selector-user-id"
            key_file.write_text("a" * 40, encoding="utf-8")
            selector_file.write_text("1", encoding="utf-8")
            client = FlarumClient(
                "http://172.16.0.234", "https://community.ablecloud.io", str(key_file), True,
                solution_selector_user_id_file=str(selector_file),
            )
            responses = [
                FakeResponse({"data": {"relationships": {"bestAnswerPost": {"data": {"id": "200"}}}}}),
                FakeResponse({"data": {"id": "901"}}),
                FakeResponse({"data": {"relationships": {
                    "bestAnswerPost": {"data": {"id": "201"}},
                    "bestAnswerUser": {"data": {"id": "1"}},
                }}}),
            ]
            with patch("urllib.request.urlopen", side_effect=responses) as opened:
                result = client.select_solution("901", "201")
            self.assertEqual("201", result["postId"])
            self.assertEqual("1", result["selectedByUserId"])
            self.assertFalse(result["reused"])
            patched = opened.call_args_list[1].args[0]
            self.assertEqual("PATCH", patched.method)
            payload = json.loads(patched.data.decode("utf-8"))
            self.assertEqual(201, payload["data"]["attributes"]["bestAnswerPostId"])
            self.assertEqual("Token " + "a" * 40 + "; userId=1", patched.headers["Authorization"])

    def test_assistant_owned_knowledge_base_can_be_updated_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "key"
            assistant_file = Path(directory) / "assistant-user-id"
            key_file.write_text("a" * 40, encoding="utf-8")
            assistant_file.write_text("40", encoding="utf-8")
            client = FlarumClient(
                "http://172.16.0.234", "https://community.ablecloud.io", str(key_file), True,
                str(assistant_file), False,
            )
            responses = [
                FakeResponse({"data": {"id": "384", "relationships": {"user": {"data": {"id": "40"}}}}}),
                FakeResponse({"data": {"id": "384", "attributes": {"isApproved": True}}}),
            ]
            with patch("urllib.request.urlopen", side_effect=responses) as opened:
                result = client.update_assistant_reply(
                    "167", "384", "### 적용 버전\n- ABLESTACK Diplo", "<!-- techflow-kb -->",
                )
            self.assertTrue(result["reused"])
            self.assertTrue(result["isApproved"])
            updated = opened.call_args_list[1].args[0]
            self.assertEqual("PATCH", updated.method)
            payload = json.loads(updated.data.decode("utf-8"))
            self.assertIn("ABLESTACK Diplo", payload["data"]["attributes"]["content"])

    def test_solution_selection_reuses_already_selected_knowledge_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "key"
            selector_file = Path(directory) / "solution-selector-user-id"
            key_file.write_text("a" * 40, encoding="utf-8")
            selector_file.write_text("1", encoding="utf-8")
            client = FlarumClient(
                "http://172.16.0.234", "https://community.ablecloud.io", str(key_file), True,
                solution_selector_user_id_file=str(selector_file),
            )
            response = FakeResponse({"data": {"relationships": {
                "bestAnswerPost": {"data": {"id": "201"}},
                "bestAnswerUser": {"data": {"id": "1"}},
            }}})
            with patch("urllib.request.urlopen", return_value=response) as opened:
                result = client.select_solution("901", "201")
            self.assertTrue(result["reused"])
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
            lookup_request = opened.call_args_list[0].args[0]
            self.assertEqual("Token " + "a" * 40 + "; userId=40", lookup_request.headers["Authorization"])

    def test_review_approval_poll_uses_assistant_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "key"
            user_file = Path(directory) / "assistant-user-id"
            key_file.write_text("a" * 40, encoding="utf-8")
            user_file.write_text("40", encoding="utf-8")
            client = FlarumClient(
                "http://172.16.0.234", "https://community.ablecloud.io", str(key_file), False,
                str(user_file), True,
            )
            with patch("urllib.request.urlopen", return_value=FakeResponse({
                "data": {"id": "88", "attributes": {"isApproved": False}},
            })) as opened:
                self.assertFalse(client.review_post_is_approved("88"))
            request = opened.call_args.args[0]
            self.assertEqual("Token " + "a" * 40 + "; userId=40", request.headers["Authorization"])

    def test_removed_review_post_is_reported_without_breaking_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "key"
            user_file = Path(directory) / "assistant-user-id"
            key_file.write_text("a" * 40, encoding="utf-8")
            user_file.write_text("40", encoding="utf-8")
            client = FlarumClient(
                "http://172.16.0.234", "https://community.ablecloud.io", str(key_file), False,
                str(user_file), True,
            )
            with patch.object(client, "_request", side_effect=FlarumResourceNotFound("gone")):
                self.assertIsNone(client.review_post_is_approved("88"))

    def test_review_reply_ignores_matching_marker_from_a_different_author(self) -> None:
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
                FakeResponse({"data": [{
                    "id": "77", "attributes": {"contentHtml": "<!-- review -->", "isApproved": True},
                    "relationships": {"user": {"data": {"type": "users", "id": "32"}}},
                }]}),
                FakeResponse({"data": {"id": "88", "attributes": {"isApproved": False}}}),
            ]
            with patch("urllib.request.urlopen", side_effect=responses) as opened:
                result = client.publish_review_reply("901", "전체 검토 답변", "<!-- review -->")
            self.assertEqual("88", result["postId"])
            self.assertEqual(2, opened.call_count)

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
        self.assertEqual("WAITING_RESOLUTION", approved["conversationState"])
        self.assertEqual("flarum:moderator", approved["reviewer"])

    def test_missing_information_is_an_optional_section_without_document_title(self) -> None:
        draft = format_draft({
            "state": "NEEDS_INFORMATION",
            "userQuestion": "가상머신 콘솔이 연결중에서 멈춥니다.",
            "plan": {"questionsNeeded": ["문제가 발생한 시각과 libvirt 로그를 첨부해 주세요."]},
        })
        self.assertTrue(draft.startswith("확인을 도와드리겠습니다."))
        self.assertIn("아래 정보를 알려주시면", draft)
        self.assertIn("libvirt 로그", draft)
        self.assertNotIn("트러블슈팅 가이드", draft)

    def test_followup_turn_keeps_context_and_creates_a_new_review_version(self) -> None:
        store = MemoryStore()
        first = {**self.payload(), "postId": "100", "postNumber": 1, "postAuthorId": "42",
                 "turnRole": "REQUESTER", "responseRequested": True}
        case = store.create_community_case(
            first, {"draftAnswer": "로그를 첨부해 주세요.", "answerState": "ANSWERED", "citations": []},
            "conversation-first-post", "conversation-first-correlation",
        )
        store.attach_community_review(
            case["caseId"], {"postId": "200", "postUrl": "https://community.ablecloud.io/d/901/200"},
            "conversation-first-review",
        )
        published = store.mark_community_review_approved(case["caseId"], "conversation-first-approved")
        self.assertEqual("WAITING_RESOLUTION", published["conversationState"])

        followup = {**self.payload(), "question": "요청한 로그를 첨부했습니다.", "postId": "101",
                    "postNumber": 3, "postAuthorId": "42", "turnRole": "REQUESTER",
                    "responseRequested": True, "artifactIds": []}
        updated = store.create_community_case(
            followup, {"draftAnswer": "로그를 반영한 후속 답변", "answerState": "ANSWERED", "citations": []},
            "conversation-followup-post", "conversation-followup-correlation",
        )
        self.assertFalse(updated["created"])
        self.assertTrue(updated["turnCreated"])
        self.assertEqual(2, updated["draftVersion"])
        self.assertEqual(2, updated["contextVersion"])
        self.assertEqual("ANALYZING", updated["conversationState"])
        self.assertEqual(["100", "101"], [item["sourcePostId"] for item in store.list_community_turns("901")])

        duplicate = store.create_community_case(
            followup, {"draftAnswer": "중복", "answerState": "ANSWERED", "citations": []},
            "conversation-followup-duplicate", "conversation-followup-correlation",
        )
        self.assertFalse(duplicate["turnCreated"])
        self.assertEqual(2, duplicate["draftVersion"])

    def test_successful_requester_update_bypasses_rag_and_creates_resolution_acknowledgment(self) -> None:
        store = MemoryStore()
        first = {
            **self.payload(), "postId": "415", "postNumber": 1,
            "postAuthorId": "42", "turnRole": "REQUESTER", "responseRequested": True,
        }
        case = store.create_community_case(
            first,
            {"draftAnswer": "태그 값을 확인해 주세요.", "answerState": "ANSWERED", "citations": []},
            "resolution-progress-first", "resolution-progress-first-correlation",
        )
        store.mark_community_auto_published(
            case["caseId"], "태그 값을 확인해 주세요.",
            {"postId": "418", "postUrl": "https://community.ablecloud.io/d/901/418"},
            "resolution-progress-first-published",
        )
        client = TestClient(create_app(Settings(), store))

        response = client.post(
            "/v1/community/cases",
            headers={**HEADERS, "Idempotency-Key": "resolution-progress-followup"},
            json={
                **first,
                "question": (
                    "물리네트워크의 태그와 네트워크 오퍼링 태그를 맞춘 후 해당 문제가 더 이상 발생하지 않습니다."
                ),
                "postId": "419", "postNumber": 5,
            },
        )

        self.assertEqual(201, response.status_code, response.text)
        result = response.json()["data"]
        self.assertEqual("ANSWERED", result["answerState"])
        self.assertEqual("419", result["lastSeenPostId"])
        self.assertIn("태그를 일치시킨 뒤", result["draftAnswer"])
        self.assertEqual("419", store.list_community_turns("901")[-1]["sourcePostId"])

    def test_expired_conversation_artifact_does_not_block_final_kb_synthesis(self) -> None:
        retained = uuid4()
        expired = uuid4()

        class EvidenceStore:
            def evidence(self, artifact_id):
                if artifact_id == expired:
                    raise NotFoundError("artifact not found")
                return object()

        available, unavailable = _available_conversation_artifact_ids(
            [
                {"artifactIds": [str(expired), str(retained)]},
                {"artifactIds": [str(retained)]},
            ],
            EvidenceStore(),
        )

        self.assertEqual([retained], available)
        self.assertEqual(1, unavailable)

    def test_failed_followup_draft_can_be_retried_without_duplicate_turn(self) -> None:
        store = MemoryStore()
        first = {**self.payload(), "postId": "100", "postNumber": 1, "postAuthorId": "42",
                 "turnRole": "REQUESTER", "responseRequested": True}
        store.create_community_case(
            first, {"draftAnswer": "초기 답변", "answerState": "ANSWERED", "citations": []},
            "retry-first-post", "retry-first-correlation",
        )
        followup = {**self.payload(), "question": "보완 로그입니다.", "postId": "101",
                    "postNumber": 2, "postAuthorId": "42", "turnRole": "REQUESTER",
                    "responseRequested": True, "artifactIds": []}
        failed = store.create_community_case(
            followup, {"draftAnswer": None, "answerState": "FAILED", "citations": []},
            "retry-failed-post", "retry-failed-correlation",
        )
        self.assertEqual("FAILED", failed["answerState"])
        retried = store.retry_failed_community_case(
            followup, {"draftAnswer": "보완 로그를 반영한 답변", "answerState": "ANSWERED", "citations": []},
            "retry-success-post", "retry-success-correlation",
        )
        self.assertTrue(retried["turnCreated"])
        self.assertEqual(2, retried["draftVersion"])
        self.assertEqual("ANSWERED", retried["answerState"])
        self.assertEqual(2, len(store.list_community_turns("901")))
        events = store.list_community_case_events(retried["caseId"], 10)
        self.assertIn("FAILED_DRAFT_RETRIED", [item["eventType"] for item in events])

    def test_reused_assistant_post_correction_updates_case_response_and_turn(self) -> None:
        store = MemoryStore()
        case = store.create_community_case(
            {**self.payload(), "postId": "430", "postNumber": 9, "postAuthorId": "46", "turnRole": "REQUESTER"},
            {"draftAnswer": "이전 실행 안내", "answerState": "ANSWERED", "citations": []},
            "correction-create", "correction-create-correlation",
        )
        publication = {"postId": "431", "postUrl": "https://community.ablecloud.io/d/177/431"}
        store.mark_community_auto_published(case["caseId"], "이전 실행 안내", publication, "correction-publish")
        store.record_community_turn(
            {
                "discussionId": "901", "postId": "431", "postNumber": 10,
                "postAuthorId": "40", "authorId": "40", "turnRole": "ASSISTANT",
                "question": "이전 실행 안내", "artifactIds": [],
            },
            "correction-turn", "correction-turn-correlation",
        )

        updated = store.mark_community_auto_published(
            case["caseId"], "접속·로그 경로를 포함한 보완 답변", publication, "correction-update",
        )

        self.assertEqual("접속·로그 경로를 포함한 보완 답변", updated["draftAnswer"])
        assistant = next(item for item in store.list_community_turns("901") if item["sourcePostId"] == "431")
        self.assertEqual("접속·로그 경로를 포함한 보완 답변", assistant["content"])
        events = store.list_community_case_events(case["caseId"], 20)
        self.assertIn("AUTO_PUBLISHED_CORRECTED", [item["eventType"] for item in events])

    def test_requester_best_answer_resolves_and_unset_reopens_conversation(self) -> None:
        store = MemoryStore()
        first = {**self.payload(), "postId": "100", "postNumber": 1, "postAuthorId": "42"}
        case = store.create_community_case(
            first, {"draftAnswer": "답변", "answerState": "ANSWERED", "citations": []},
            "resolution-first-post", "resolution-first-correlation",
        )
        resolved = store.sync_community_resolution(
            {**first, "bestAnswerPostId": "200", "bestAnswerUserId": "42"},
            "resolution-selected", "resolution-selected-correlation",
        )
        self.assertEqual("RESOLVED", resolved["conversationState"])
        self.assertEqual("200", resolved["resolvedPostId"])

        reopened = store.sync_community_resolution(
            {**first, "bestAnswerPostId": None, "bestAnswerUserId": None},
            "resolution-unset", "resolution-unset-correlation",
        )
        self.assertEqual("ANALYZING", reopened["conversationState"])
        self.assertIsNotNone(reopened["reopenedAt"])
        events = store.list_community_case_events(case["caseId"], 10)
        self.assertIn("RESOLUTION_UNSET_REOPENED", [item["eventType"] for item in events])

    def test_configured_administrator_best_answer_resolves_conversation(self) -> None:
        store = MemoryStore()
        first = {**self.payload(), "postId": "100", "postNumber": 1, "postAuthorId": "42"}
        case = store.create_community_case(
            first, {"draftAnswer": "답변", "answerState": "ANSWERED", "citations": []},
            "administrator-resolution-first", "administrator-resolution-correlation",
        )
        result = store.sync_community_resolution(
            {
                **first, "bestAnswerPostId": "200", "bestAnswerUserId": "1",
                "bestAnswerSelectedByAdministrator": True,
            },
            "administrator-resolution-selected", "administrator-resolution-selected-correlation",
        )
        self.assertEqual("RESOLVED", result["conversationState"])
        self.assertEqual("200", result["resolvedPostId"])
        self.assertEqual("1", result["resolvedByUserId"])
        events = store.list_community_case_events(case["caseId"], 10)
        resolved_event = next(item for item in events if item["eventType"] == "RESOLVED_BY_ADMINISTRATOR")
        self.assertEqual("ADMINISTRATOR", resolved_event["details"]["resolutionActorRole"])

    def test_gateway_derives_administrator_role_from_operator_configuration(self) -> None:
        store = MemoryStore()
        client = TestClient(create_app(Settings(flarum_resolution_admin_user_ids=("1",)), store))
        first = {**self.payload(), "postId": "100", "postNumber": 1, "postAuthorId": "42"}
        created = client.post(
            "/v1/community/cases",
            headers={**HEADERS, "Idempotency-Key": "administrator-gateway-first"},
            json=first,
        )
        self.assertEqual(201, created.status_code)
        selected = client.post(
            "/v1/community/cases",
            headers={**HEADERS, "Idempotency-Key": "administrator-gateway-resolution"},
            json={
                **first, "question": "Community 해결 상태가 변경되었습니다.",
                "resolutionOnly": True, "responseRequested": False,
                "bestAnswerPostId": "200", "bestAnswerUserId": "1",
            },
        )
        self.assertEqual(201, selected.status_code)
        self.assertEqual("RESOLVED", selected.json()["data"]["conversationState"])

    def test_inbound_event_cannot_claim_administrator_role(self) -> None:
        client = TestClient(create_app(Settings(), MemoryStore()))
        attempted = client.post(
            "/v1/community/cases",
            headers={**HEADERS, "Idempotency-Key": "administrator-role-forgery"},
            json={
                **self.payload(), "postId": "200", "postNumber": 2, "postAuthorId": "1",
                "resolutionOnly": True, "responseRequested": False,
                "bestAnswerPostId": "200", "bestAnswerUserId": "1",
                "bestAnswerSelectedByAdministrator": True,
            },
        )
        self.assertEqual(422, attempted.status_code)

    def test_solution_selector_identity_is_an_implicit_administrator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            selector = Path(directory) / "selector-user-id"
            selector.write_text("1", encoding="utf-8")
            identities = _resolution_administrator_ids(Settings(
                flarum_solution_selector_user_id_file=str(selector),
                flarum_resolution_admin_user_ids=("7",),
            ))
        self.assertEqual({"1", "7"}, identities)

    def test_resolved_conversation_publishes_a_versioned_knowledge_base(self) -> None:
        store = MemoryStore()
        first = {**self.payload(), "postId": "100", "postNumber": 1, "postAuthorId": "42"}
        case = store.create_community_case(
            first, {"draftAnswer": "먼저 로그를 확인해 주세요.", "answerState": "ANSWERED", "citations": []},
            "kb-first-post", "kb-first-correlation",
        )
        store.mark_community_auto_published(
            case["caseId"], "먼저 로그를 확인해 주세요.",
            {"postId": "200", "postUrl": "https://community.ablecloud.io/d/901/200"},
            "kb-auto-published",
        )
        resolved = store.sync_community_resolution(
            {**first, "bestAnswerPostId": "200", "bestAnswerUserId": "42"},
            "kb-resolved", "kb-resolved-correlation",
        )
        knowledge = format_knowledge_base({
            "state": "ANSWERED",
            "report": {
                "summary": "가상머신 시작 오류가 발생했습니다.",
                "observedFacts": ["가상머신 시작 오류가 표시됩니다."],
                "diagnoses": [{"title": "호스트 자원이 부족했습니다."}],
                "recommendedActions": ["여유 자원이 있는 호스트에서 다시 시작합니다."],
                "unknowns": [], "artifactEvidence": [],
                "currentAssessment": "CURRENT_RUNTIME_ISSUE", "previewAssessment": "NOT_APPLICABLE",
            },
            "citations": [],
        })
        published = store.mark_community_knowledge_published(
            resolved["caseId"], knowledge,
            {"postId": "201", "postUrl": "https://community.ablecloud.io/d/901/201"},
            "kb-published",
        )
        self.assertEqual("201", published["knowledgeBasePostId"])
        self.assertEqual("200", published["knowledgeBaseSourcePostId"])
        self.assertEqual(1, published["knowledgeBaseVersion"])
        self.assertTrue(knowledge.startswith("### 증상"))
        self.assertNotIn("담당자 승인", knowledge)

        selected = store.mark_community_knowledge_solution_selected(
            published["caseId"],
            {"postId": "201", "postUrl": "https://community.ablecloud.io/d/901/201",
             "selectedByUserId": "1", "reused": False},
            "kb-solution-selected",
        )
        self.assertIsNotNone(selected["knowledgeBaseSolutionSelectedAt"])
        self.assertEqual("1", selected["knowledgeBaseSolutionSelectedByUserId"])
        events = store.list_community_case_events(selected["caseId"], 10)
        self.assertIn("KNOWLEDGE_BASE_SOLUTION_SELECTED", [item["eventType"] for item in events])

        confirmed = store.sync_community_resolution(
            {**first, "bestAnswerPostId": "201", "bestAnswerUserId": "1"},
            "kb-solution-confirmed", "kb-solution-confirmed-correlation",
        )
        self.assertEqual("RESOLVED", confirmed["conversationState"])
        self.assertEqual("200", confirmed["resolvedPostId"])
        self.assertEqual("201", confirmed["knowledgeBasePostId"])
        self.assertLessEqual(len(KB_SOLUTION_CONFIRMED_EVENT), 32)

    def test_knowledge_base_removes_unverified_attachment_download_claim(self) -> None:
        result = {
            "state": "ANSWERED",
            "attachmentFailureRecorded": False,
            "report": {
                "summary": "Windows 설치 중 디스크가 보이지 않습니다.",
                "observedFacts": ["Windows 설치 중 설치 대상 디스크가 보이지 않습니다."],
                "diagnoses": [{"title": "VirtIO SCSI 드라이버가 로드되지 않았습니다."}],
                "recommendedActions": ["VirtIO SCSI 드라이버를 불러온 뒤 디스크 목록을 새로 고칩니다."],
                "unknowns": ["첨부파일을 내려받지 못해 원래 화면은 확인할 수 없습니다."],
                "artifactEvidence": [],
            },
            "citations": [],
        }
        knowledge = format_knowledge_base(result)
        self.assertIsNotNone(knowledge)
        self.assertNotIn("첨부파일을 내려받지 못", knowledge)

        result["attachmentFailureRecorded"] = True
        knowledge_with_failure = format_knowledge_base(result)
        self.assertIn("첨부파일을 내려받지 못", knowledge_with_failure)

    def test_legacy_review_publication_can_be_migrated_once_to_auto_publish(self) -> None:
        store = MemoryStore()
        case = store.create_community_case(
            {**self.payload(), "postId": "100", "postNumber": 1, "postAuthorId": "42"},
            {"draftAnswer": "### 증상\n- 시작할 수 없습니다.", "answerState": "ANSWERED", "citations": []},
            "legacy-auto-first", "legacy-auto-correlation",
        )
        store.attach_community_review(
            case["caseId"],
            {"postId": "200", "postUrl": "https://community.ablecloud.io/d/901/200"},
            "legacy-review-attached",
        )
        legacy = store.mark_community_review_approved(case["caseId"], "legacy-review-approved")
        self.assertEqual("flarum:moderator", legacy["reviewer"])

        migrated = store.mark_community_auto_published(
            case["caseId"], "먼저 시작 실패 시각의 로그를 확인해 주세요.",
            {"postId": "201", "postUrl": "https://community.ablecloud.io/d/901/201"},
            "legacy-auto-migrated",
        )
        self.assertEqual("techflow:auto", migrated["reviewer"])
        self.assertEqual("201", migrated["publishedPostId"])
        self.assertEqual("먼저 시작 실패 시각의 로그를 확인해 주세요.", migrated["draftAnswer"])

    def test_abstained_case_can_publish_a_safe_information_request(self) -> None:
        store = MemoryStore()
        case = store.create_community_case(
            {**self.payload(), "postId": "100", "postNumber": 1, "postAuthorId": "42"},
            {"draftAnswer": None, "answerState": "ABSTAINED", "citations": []},
            "abstained-auto-first", "abstained-auto-correlation",
        )
        published = store.mark_community_auto_published(
            case["caseId"], "사용 중인 버전과 오류 시각을 알려주세요.",
            {"postId": "202", "postUrl": "https://community.ablecloud.io/d/901/202"},
            "abstained-auto-published",
        )
        self.assertEqual("PUBLISHED", published["state"])
        self.assertEqual("techflow:auto", published["reviewer"])
        self.assertEqual("사용 중인 버전과 오류 시각을 알려주세요.", published["draftAnswer"])

    def test_unconfigured_participant_best_answer_does_not_resolve_conversation(self) -> None:
        store = MemoryStore()
        first = {**self.payload(), "postId": "100", "postNumber": 1, "postAuthorId": "42"}
        store.create_community_case(
            first, {"draftAnswer": "답변", "answerState": "ANSWERED", "citations": []},
            "moderator-resolution-first", "moderator-resolution-correlation",
        )
        result = store.sync_community_resolution(
            {**first, "bestAnswerPostId": "200", "bestAnswerUserId": "1"},
            "moderator-resolution-selected", "moderator-resolution-selected-correlation",
        )
        self.assertEqual("WAITING_RESOLUTION", result["conversationState"])
        self.assertIsNone(result["resolvedAt"])

    def test_missing_review_post_is_failed_closed_and_audited(self) -> None:
        store = MemoryStore()
        case = store.create_community_case(
            {**self.payload(), "postId": "100", "postNumber": 1},
            {"draftAnswer": "답변", "answerState": "ANSWERED", "citations": []},
            "missing-review-first", "missing-review-correlation",
        )
        store.attach_community_review(
            case["caseId"], {"postId": "200", "postUrl": "https://community.ablecloud.io/d/901/200"},
            "missing-review-attached",
        )
        rejected = store.mark_community_review_missing(case["caseId"], "missing-review-reconciled")
        self.assertEqual("REJECTED", rejected["state"])
        self.assertEqual("ANALYZING", rejected["conversationState"])
        events = store.list_community_case_events(case["caseId"], 5)
        self.assertIn("REVIEW_POST_MISSING", [item["eventType"] for item in events])


if __name__ == "__main__":
    unittest.main()
