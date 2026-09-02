from __future__ import annotations

import hashlib
from pathlib import Path
import unittest
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.store import MemoryStore


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[list[str], dict]] = []

    def validate(self, supplied: str) -> None:
        if supplied != "runtime-chat-token":
            raise AssertionError("unexpected token")

    def send(self, user_ids: list[str], payload: dict) -> None:
        self.sent.append((user_ids, payload))

    def download_post_file(
        self, post_id: str, destination: Path, *, max_bytes: int, max_archive_bytes: int,
    ):
        del post_id, destination, max_bytes, max_archive_bytes
        return None


class FlakyBot(FakeBot):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def send(self, user_ids: list[str], payload: dict) -> None:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("temporary Chat delivery failure")
        super().send(user_ids, payload)


def settings() -> Settings:
    return Settings(
        chat_bot_enabled=True, chat_bot_token_file="/run/secrets/chat_bot_token",
        chat_reviewer_usernames=("ceo",),
    )


def chat_form(text: str, post_id: str) -> bytes:
    return urlencode({
        "token": "runtime-chat-token", "user_id": "7", "username": "engineer",
        "post_id": post_id, "text": text,
    }).encode()


class Epic4OperationsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()
        self.bot = FakeBot()
        self.client = TestClient(create_app(settings(), store=self.store, chat_bot_client=self.bot))

    @staticmethod
    def headers(run: str) -> dict[str, str]:
        return {"X-Correlation-Id": f"epic4-{run}-correlation", "Idempotency-Key": f"epic4-{run}-idempotency"}

    def test_chat_context_is_idempotent_and_kept_until_resolved(self) -> None:
        for index, text in enumerate(("VM 시작 오류를 확인해 줘", "앞 질문과 같은 VM의 로그는 어디서 봐?"), 1):
            response = self.client.post(
                "/v1/chat/synology/events", content=chat_form(text, str(index)),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            self.assertEqual(200, response.status_code)
            self.assertIn("질문을 접수", response.json()["text"])
        self.assertEqual(4, len(self.store.list_chat_turns("7")))
        self.assertEqual(2, len(self.bot.sent))
        repeated = self.client.post(
            "/v1/chat/synology/events", content=chat_form("중복 이벤트", "2"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(200, repeated.status_code)
        self.assertIn("이미 처리", repeated.json()["text"])
        self.assertEqual(4, len(self.store.list_chat_turns("7")))
        self.assertEqual(2, len(self.bot.sent))
        resolved = self.client.post(
            "/v1/chat/synology/events", content=chat_form("해결", "3"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertIn("해결된 상태", resolved.json()["text"])
        self.assertEqual([], self.store.list_chat_turns("7"))
        reopened = self.store.open_chat_conversation("7", "engineer")
        self.assertEqual(2, reopened["contextVersion"])

    def test_chat_job_is_durable_idempotent_and_cancellable(self) -> None:
        conversation = self.store.open_chat_conversation("9", "operator")
        self.store.record_chat_turn("9", "post-1", "USER", "질문")
        first = self.store.enqueue_chat_job("9", "post-1", "chat-job-correlation")
        repeated = self.store.enqueue_chat_job("9", "post-1", "chat-job-correlation-repeat")
        self.assertTrue(first["created"])
        self.assertFalse(repeated["created"])
        self.assertEqual(first["jobId"], repeated["jobId"])
        running = self.store.claim_chat_job(first["jobId"])
        self.assertEqual("RUNNING", running["state"])
        self.assertEqual(1, running["attemptCount"])
        recovered = self.store.recover_chat_jobs()
        self.assertEqual("RETRYING", recovered[0]["state"])
        self.assertEqual(1, self.store.cancel_chat_jobs("9"))
        self.assertEqual("CANCELLED", self.store.get_chat_job(first["jobId"])["state"])
        self.assertEqual(conversation["contextVersion"], first["contextVersion"])

    def test_chat_delivery_retry_reuses_generated_answer(self) -> None:
        store = MemoryStore()
        bot = FlakyBot()
        client = TestClient(create_app(settings(), store=store, chat_bot_client=bot))
        response = client.post(
            "/v1/chat/synology/events", content=chat_form("스토리지 오류를 확인해 줘", "retry-1"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(200, response.status_code)
        self.assertIn("질문을 접수", response.json()["text"])
        self.assertEqual(2, bot.attempts)
        self.assertEqual(1, len(bot.sent))
        turns = store.list_chat_turns("7")
        self.assertEqual(["USER", "ASSISTANT"], [item["role"] for item in turns])
        job = next(iter(store._chat_jobs.values()))
        self.assertEqual("COMPLETED", job["state"])
        self.assertEqual(2, job["attemptCount"])

    def test_long_korean_chat_context_completes_without_dead_letter(self) -> None:
        self.store.open_chat_conversation("7", "engineer")
        for index in range(10):
            self.store.record_chat_turn(
                "7", f"history-{index}", "USER" if index % 2 == 0 else "ASSISTANT",
                f"이전 대화 {index}: " + "가상머신 시간 동기화와 네트워크 오류 확인 " * 18,
            )

        response = self.client.post(
            "/v1/chat/synology/events",
            content=chat_form("같은 환경에서 Mold 네트워크 생성 오류의 확인 순서를 알려줘.", "utf8-budget"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("질문을 접수", response.json()["text"])
        job = next(item for item in self.store._chat_jobs.values() if item["postId"] == "utf8-budget")
        self.assertEqual("COMPLETED", job["state"])
        self.assertEqual(1, job["attemptCount"])
        self.assertNotIn("AI 분석을 완료하지 못했습니다", self.bot.sent[-1][1]["text"])

    def test_failure_notified_once_and_recovery_notified_once(self) -> None:
        self.store.upsert_chat_reviewer("19", "ceo")
        fingerprint = hashlib.sha256(b"community-poller:poll").hexdigest()
        payload = {
            "subsystem": "community-poller", "operation": "poll", "fingerprint": fingerprint,
            "errorType": "TimeoutError", "maxAttempts": 3,
        }
        first = self.client.post("/v1/operations/failures", headers=self.headers("failure-one"), json=payload)
        second = self.client.post("/v1/operations/failures", headers=self.headers("failure-two"), json=payload)
        third = self.client.post("/v1/operations/failures", headers=self.headers("failure-three"), json=payload)
        self.assertTrue(first.json()["data"]["notifyFailure"])
        self.assertFalse(second.json()["data"]["notifyFailure"])
        self.assertEqual("DEAD_LETTER", third.json()["data"]["failure"]["state"])
        self.assertEqual(1, len(self.bot.sent))
        retry = self.client.post(
            f"/v1/operations/failures/{third.json()['data']['failure']['failureId']}/retry",
            headers=self.headers("manual-retry"), json={},
        )
        self.assertEqual("RETRYING", retry.json()["data"]["state"])
        recovered = self.client.post(
            "/v1/operations/recoveries", headers=self.headers("recovery-one"), json={"fingerprint": fingerprint},
        )
        repeated = self.client.post(
            "/v1/operations/recoveries", headers=self.headers("recovery-two"), json={"fingerprint": fingerprint},
        )
        self.assertTrue(recovered.json()["data"]["notifyRecovery"])
        self.assertFalse(repeated.json()["data"]["notifyRecovery"])
        self.assertEqual(2, len(self.bot.sent))

    def test_kpis_are_aggregate_only(self) -> None:
        response = self.client.get(
            "/v1/operations/kpis?windowHours=24", headers={"X-Correlation-Id": "epic4-kpi-correlation"},
        )
        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertFalse(data["privacy"]["rawContentIncluded"])
        self.assertNotIn("question", str(data).lower())
        self.assertNotIn("answer", str(data).lower())


if __name__ == "__main__":
    unittest.main()
