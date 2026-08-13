from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from app.chat_assist import (
    SynologyBotClient,
    case_card,
    case_evidence_text,
    case_text,
    parse_chat_event,
    parse_command,
)
from app.config import Settings
from app.main import _json_log, create_app
from app.store import MemoryStore


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[list[str], dict]] = []

    def validate(self, supplied: str) -> None:
        if supplied != "runtime-chat-token":
            from app.store import InvalidBoundaryError
            raise InvalidBoundaryError("bad token")

    def send(self, user_ids: list[str], payload: dict) -> None:
        self.sent.append((user_ids, payload))


class FakeFlows:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self.calls: list[tuple[str, dict]] = []

    def decide(self, decision: str, payload: dict) -> None:
        self.calls.append((decision, payload))
        case_id = self.store.resolve_community_case(payload["caseId"])["caseId"]
        result = self.store.decide_community_case(
            case_id,
            {
                "decision": decision, "reviewer": payload["reviewer"],
                "expectedDraftVersion": payload["expectedDraftVersion"],
                "editedAnswer": payload.get("editedAnswer"), "note": payload.get("note"),
            },
            payload["eventId"] + "-decision",
        )
        if decision == "APPROVE":
            self.store.mark_community_published(
                case_id, {"postId": "901", "postUrl": "https://community.ablecloud.io/d/901/901"},
                payload["eventId"] + "-publish",
            )


class FakeFlarumReview:
    def __init__(self) -> None:
        self.approved = False
        self.posts: list[tuple[str, str, str]] = []

    def publish_review_reply(self, discussion_id: str, answer: str, marker: str) -> dict:
        self.posts.append((discussion_id, answer, marker))
        return {"postId": "990", "postUrl": f"https://community.ablecloud.io/d/{discussion_id}/990", "isApproved": False}

    def review_post_is_approved(self, post_id: str) -> bool:
        return self.approved

    def publish_reply(self, discussion_id: str, answer: str, marker: str) -> dict:
        raise AssertionError("legacy publishing must not be used")


def settings() -> Settings:
    return Settings(
        chat_bot_enabled=True,
        chat_bot_token_file="/run/secrets/chat_bot_token",
        chat_reviewer_usernames=("ceo",),
        community_approve_webhook_file="/run/secrets/community_approve_webhook",
        community_reject_webhook_file="/run/secrets/community_reject_webhook",
    )


def form(text: str, *, username: str = "ceo", token: str = "runtime-chat-token", post_id: str = "100") -> bytes:
    return urlencode({
        "token": token, "user_id": "7", "username": username,
        "post_id": post_id, "timestamp": "1700000000", "text": text,
    }).encode()


class ChatParsingTest(unittest.TestCase):
    def test_notification_log_is_structured_stdout(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            _json_log("community_chat_notification_sent", caseId="safe-case", reviewerCount=1)
        self.assertEqual({
            "event": "community_chat_notification_sent",
            "caseId": "safe-case",
            "reviewerCount": 1,
        }, json.loads(output.getvalue()))

    def test_proactive_message_uses_chatbot_method(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory, "token")
            token_file.write_text("runtime-chat-token-value-123456", encoding="utf-8")
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'{"success":true}'
            with patch("app.chat_assist.urllib.request.urlopen", return_value=response) as send:
                SynologyBotClient("https://chat.ablecloud.io", str(token_file), True).send(
                    ["19"], {"text": "new Community review"}
                )
            request = send.call_args.args[0]
            self.assertIn("method=chatbot", request.full_url)
            self.assertNotIn("method=incoming", request.full_url)

    def test_form_event_and_korean_command(self) -> None:
        event = parse_chat_event("application/x-www-form-urlencoded", form("수정 abcdef12 1 최종 답변입니다"))
        self.assertEqual(("edit", ["abcdef12", "1", "최종 답변입니다"]), parse_command(event))

    def test_evidence_command_is_explicit(self) -> None:
        event = parse_chat_event("application/x-www-form-urlencoded", form("근거 abcdef12"))
        self.assertEqual(("evidence", ["abcdef12"]), parse_command(event))

    def test_interactive_action(self) -> None:
        payload = {
            "payload": json.dumps({
                "token": "runtime-chat-token", "post_id": "200", "callback_id": "community:x:1",
                "user": {"user_id": "7", "username": "ceo"},
                "actions": [{"name": "approve", "value": "approve:abcdef12:1"}],
            })
        }
        event = parse_chat_event("application/x-www-form-urlencoded", urlencode(payload).encode())
        self.assertEqual(("approve", ["abcdef12", "1"]), parse_command(event))

    def test_card_contains_observability_actions_only(self) -> None:
        store = MemoryStore()
        case = store.create_community_case(
            {"discussionId": "901", "discussionUrl": "https://community.ablecloud.io/d/901",
             "title": "Cube 질문", "authorId": "1", "tagSlugs": []},
            {"draftAnswer": "검토할 답변", "answerState": "ANSWERED", "citations": []},
            "chat-card-idempotency-0001", "chat-card-correlation",
        )
        card = case_card(case)
        names = [item["name"] for item in card["attachments"][0]["actions"]]
        self.assertEqual(["detail", "evidence"], names)

    def test_detail_hides_evidence_and_explicit_evidence_renders_it(self) -> None:
        store = MemoryStore()
        case = store.create_community_case(
            {"discussionId": "903", "discussionUrl": "https://community.ablecloud.io/d/903",
             "title": "콘솔 질문", "authorId": "1", "tagSlugs": []},
            {"draftAnswer": "QEMU VNC 상태를 확인합니다.", "answerState": "ANSWERED",
             "citations": [{"repository": "qemu-project/qemu", "path": "qemu-qmp-ref.html",
                            "startLine": 1, "endLine": 1, "commit": "a" * 64}],
             "evidenceLedger": {"coverage": [{"sourceProfileId": "CURATED_PLATFORM_REFERENCE",
                                                "role": "CURRENT_PLATFORM_REFERENCE",
                                                "state": "EVIDENCE_FOUND", "evidenceCount": 1}],
                                "currentAssessment": "CURRENT_RUNTIME_ISSUE",
                                "previewAssessment": "NOT_APPLICABLE"}},
            "chat-evidence-idempotency-0001", "chat-evidence-correlation",
        )
        detail = case_text(case)
        self.assertIn("QEMU VNC 상태", detail)
        self.assertNotIn("Citation", detail)
        self.assertNotIn("CURATED_PLATFORM_REFERENCE", detail)
        evidence = case_evidence_text(case)
        self.assertIn("Citation 1개", evidence)
        self.assertIn("CURATED_PLATFORM_REFERENCE", evidence)


class ChatEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()
        self.case = self.store.create_community_case(
            {"discussionId": "901", "discussionUrl": "https://community.ablecloud.io/d/901",
             "title": "Cube 질문", "authorId": "1", "tagSlugs": []},
            {"draftAnswer": "검토할 답변", "answerState": "ANSWERED", "citations": []},
            "chat-endpoint-idempotency-0001", "chat-endpoint-correlation",
        )
        self.bot = FakeBot()
        self.flows = FakeFlows(self.store)
        self.client = TestClient(create_app(
            settings(), store=self.store, chat_bot_client=self.bot, community_flow_client=self.flows,
        ))

    def post(self, body: bytes):
        return self.client.post(
            "/v1/chat/synology/events", content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def test_connect_registers_identity_and_lists_pending(self) -> None:
        response = self.post(form("연결"))
        self.assertEqual(200, response.status_code)
        self.assertIn("게시 알림 수신자로 연결", response.json()["text"])
        self.assertEqual("ceo", self.store.list_chat_reviewers()[0]["username"])

    def test_new_case_notifies_connected_reviewer(self) -> None:
        self.post(form("연결"))
        response = self.client.post(
            "/v1/community/cases",
            headers={
                "X-Correlation-Id": "chat-notification-correlation",
                "Idempotency-Key": "chat-notification-idempotency-0001",
            },
            json={
                "discussionId": "902",
                "discussionUrl": "https://community.ablecloud.io/d/902",
                "title": "새 Community 질문",
                "question": "Cube 상태를 어디에서 확인하나요?",
                "authorId": "42",
                "tagSlugs": ["cube"],
                "artifactIds": [],
            },
        )
        self.assertEqual(201, response.status_code)
        self.assertEqual(["7"], self.bot.sent[0][0])
        self.assertIn("이전 승인 방식", self.bot.sent[0][1]["text"])
        self.assertIn("새 Community 질문", self.bot.sent[0][1]["text"])
        self.assertNotIn("Citation", json.dumps(self.bot.sent[0][1], ensure_ascii=False))
        self.assertEqual(["detail", "evidence"], [
            action["name"] for action in self.bot.sent[0][1]["attachments"][0]["actions"]
        ])

    def test_review_post_notification_links_full_answer_without_chat_truncation(self) -> None:
        flarum = FakeFlarumReview()
        review_settings = Settings(
            flarum_api_key_file="/run/secrets/flarum_api_key",
            flarum_assistant_user_id_file="/run/secrets/flarum_assistant_user_id",
            community_review_post_enabled=True,
            chat_bot_enabled=True,
            chat_bot_token_file="/run/secrets/chat_bot_token",
            chat_reviewer_usernames=("ceo",),
            community_approve_webhook_file="/run/secrets/community_approve_webhook",
            community_reject_webhook_file="/run/secrets/community_reject_webhook",
        )
        store = MemoryStore()
        bot = FakeBot()
        client = TestClient(create_app(
            review_settings, store=store, chat_bot_client=bot,
            community_flow_client=FakeFlows(store), flarum_client_instance=flarum,
        ))
        case = store.create_community_case(
            {"discussionId": "990", "discussionUrl": "https://community.ablecloud.io/d/990",
             "title": "첨부파일 질문", "question": "로그 압축을 확인해 주세요.", "authorId": "42",
             "tagSlugs": ["mold"], "artifactIds": []},
            {"draftAnswer": "전체 답변은 Community 원문에만 표시됩니다.", "answerState": "ANSWERED", "citations": []},
            "review-link-create", "review-link-correlation",
        )
        attached = store.attach_community_review(
            case["caseId"], {"postId": "990", "postUrl": "https://community.ablecloud.io/d/990/990"},
            "review-link-attach",
        )
        message = case_card(attached, notification_type="review")
        rendered = json.dumps(message, ensure_ascii=False)
        self.assertIn("https://community.ablecloud.io/d/990/990", rendered)
        self.assertNotIn(case["draftAnswer"], message["attachments"][0]["text"])
        self.assertEqual(["detail", "evidence"], [item["name"] for item in message["attachments"][0]["actions"]])
        flarum.approved = True
        reconciled = client.post(
            "/v1/community/reviews/reconcile",
            headers={"X-Correlation-Id": "review-reconcile-correlation", "Idempotency-Key": "review-reconcile-run"},
            json={},
        )
        self.assertEqual(1, reconciled.json()["data"]["approved"])
        self.assertEqual("PUBLISHED", store.get_community_case(case["caseId"])["state"])

    def test_reconcile_recovers_missing_review_post_and_notifies_chat(self) -> None:
        flarum = FakeFlarumReview()
        review_settings = Settings(
            flarum_api_key_file="/run/secrets/flarum_api_key",
            flarum_assistant_user_id_file="/run/secrets/flarum_assistant_user_id",
            community_review_post_enabled=True,
            chat_bot_enabled=True,
            chat_bot_token_file="/run/secrets/chat_bot_token",
            chat_reviewer_usernames=("ceo",),
            community_approve_webhook_file="/run/secrets/community_approve_webhook",
            community_reject_webhook_file="/run/secrets/community_reject_webhook",
        )
        store = MemoryStore()
        store.upsert_chat_reviewer("7", "ceo")
        case = store.create_community_case(
            {"discussionId": "990", "discussionUrl": "https://community.ablecloud.io/d/990",
             "title": "복구 질문", "question": "전체 답변 링크를 알려주세요.", "authorId": "42",
             "tagSlugs": ["mold"], "artifactIds": []},
            {"draftAnswer": "복구된 전체 답변", "answerState": "ANSWERED", "citations": []},
            "review-retry-create", "review-retry-correlation",
        )
        bot = FakeBot()
        client = TestClient(create_app(
            review_settings, store=store, chat_bot_client=bot,
            community_flow_client=FakeFlows(store), flarum_client_instance=flarum,
        ))
        reconciled = client.post(
            "/v1/community/reviews/reconcile",
            headers={"X-Correlation-Id": "review-retry-run", "Idempotency-Key": "review-retry-run"},
            json={},
        )
        data = reconciled.json()["data"]
        self.assertEqual(1, data["retried"])
        self.assertEqual(0, data["retryFailed"])
        recovered = store.get_community_case(case["caseId"])
        self.assertEqual("990", recovered["reviewPostId"])
        self.assertIn(recovered["reviewPostUrl"], json.dumps(bot.sent[0][1], ensure_ascii=False))

    def test_legacy_approval_command_explains_automatic_publication(self) -> None:
        reference = str(self.case["caseId"])[:8]
        response = self.post(form(f"승인 {reference} 1", post_id="approve-100"))
        self.assertEqual(200, response.status_code)
        self.assertIn("승인 없이 자동 게시", response.json()["text"])
        self.assertEqual("DRAFT_PENDING", self.store.get_community_case(self.case["caseId"])["state"])

    def test_detail_hides_evidence_and_evidence_command_requires_reviewer(self) -> None:
        reference = str(self.case["caseId"])[:8]
        detail = self.post(form(f"상세 {reference}"))
        self.assertEqual(200, detail.status_code)
        self.assertNotIn("Citation", json.dumps(detail.json(), ensure_ascii=False))
        evidence = self.post(form(f"근거 {reference}"))
        self.assertEqual(200, evidence.status_code)
        self.assertIn("Community 내부 근거", evidence.json()["text"])
        denied = self.post(form(f"근거 {reference}", username="other"))
        self.assertEqual(403, denied.status_code)

    def test_unauthorized_username_is_denied(self) -> None:
        response = self.post(form("대기", username="other"))
        self.assertEqual(403, response.status_code)

    def test_general_user_can_submit_technical_question_without_reviewer_rights(self) -> None:
        response = self.post(form("VM 배포 오류의 원인을 알려줘", username="other"))
        self.assertEqual(200, response.status_code)
        self.assertIn("확인을 도와드리겠습니다", response.json()["text"])
        self.assertIn("ABLESTACK Diplo 버전", response.json()["text"])

    def test_bad_token_is_denied_without_detail(self) -> None:
        response = self.post(form("대기", token="wrong"))
        self.assertEqual(403, response.status_code)
        self.assertNotIn("token", response.json()["text"].lower())


if __name__ == "__main__":
    unittest.main()
