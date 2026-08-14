from __future__ import annotations

import unittest

from app.conversation import build_conversation_question, community_result_advances


class ConversationProgressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.turns = [
            {
                "sourcePostId": "373",
                "postNumber": 1,
                "role": "REQUESTER",
                "content": "스냅샷 중 /mnt Permission denied가 발생합니다.",
            },
            {
                "sourcePostId": "374",
                "postNumber": 2,
                "role": "ASSISTANT",
                "content": "QEMU Guest Agent 상태와 마운트 정보, SELinux 로그를 확인해 주세요.",
            },
        ]

    def test_prompt_separates_latest_requester_delta_and_previous_assistant(self) -> None:
        incoming = {
            "discussionId": "166",
            "postId": "375",
            "postNumber": 3,
            "turnRole": "REQUESTER",
            "question": "새 디스크를 연결한 뒤부터입니다. SELinux가 원인일 수 있나요?",
        }
        prompt = build_conversation_question("스냅샷 생성 실패", self.turns, incoming)
        self.assertIn("[참여자의 최신 추가 정보 또는 질문]", prompt)
        self.assertIn("SELinux가 원인일 수 있나요?", prompt)
        self.assertIn("[직전 TechFlow 답변]", prompt)
        self.assertIn("QEMU Guest Agent 상태와 마운트 정보", prompt)
        self.assertIn("정확한 CLI 명령", prompt)
        self.assertIn("직전 TechFlow 답변의 원인 설명이나 점검 목록을 다시 말하지 마십시오", prompt)

    def test_new_concrete_cli_step_advances_follow_up(self) -> None:
        result = {
            "report": {
                "recommendedActions": [
                    "게스트에서 `sudo ausearch -m AVC,USER_AVC -ts recent`를 실행해 SELinux 거부 기록을 확인합니다."
                ],
                "unknowns": [],
            }
        }
        self.assertTrue(community_result_advances(result, self.turns))

    def test_staff_followup_becomes_latest_human_question(self) -> None:
        incoming = {
            "discussionId": "167",
            "postId": "380",
            "postNumber": 3,
            "turnRole": "STAFF",
            "question": "새 디스크를 마운트한 뒤 오류가 발생합니다. SELinux 문제일 가능성이 높은가요?",
        }
        prompt = build_conversation_question("가상머신 스냅샷 오류", self.turns, incoming)
        self.assertIn("[참여자의 최신 추가 정보 또는 질문]", prompt)
        self.assertIn("새 디스크를 마운트한 뒤 오류가 발생합니다", prompt)
        self.assertIn("독립된 ```bash 코드 블록", prompt)

    def test_repeated_generic_checklist_does_not_advance_follow_up(self) -> None:
        repeated = "QEMU Guest Agent 상태와 마운트 정보, SELinux 로그를 확인해 주세요."
        result = {"report": {"recommendedActions": [repeated], "unknowns": [repeated]}}
        self.assertFalse(community_result_advances(result, self.turns))

    def test_rephrased_generic_checklist_does_not_advance_follow_up(self) -> None:
        result = {
            "report": {
                "recommendedActions": ["게스트 에이전트 서비스 상태와 /mnt 마운트 상태를 확인해 주세요."],
                "unknowns": ["SELinux 관련 로그와 운영체제 버전을 알려주세요."],
            }
        }
        self.assertFalse(community_result_advances(result, self.turns))


if __name__ == "__main__":
    unittest.main()
