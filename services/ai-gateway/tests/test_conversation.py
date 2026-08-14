from __future__ import annotations

import unittest
from uuid import uuid4

from app.conversation import (
    PROGRESSION_RETRY_INSTRUCTION,
    build_conversation_question,
    build_knowledge_base_question,
    build_progression_retry_question,
    community_result_advances,
)
from app.models import CommunityCaseCreateRequest, ComprehensiveQueryRequest, ComprehensiveSynthesisRequest


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

    def test_progression_retry_reserves_instruction_space_at_question_limit(self) -> None:
        long_turns = [
            *self.turns,
            {
                "sourcePostId": "381",
                "postNumber": 4,
                "role": "ASSISTANT",
                "content": "직전의 긴 기술지원 답변입니다. " * 300,
            },
        ]
        incoming = {
            "discussionId": "167",
            "postId": "382",
            "postNumber": 5,
            "turnRole": "REQUESTER",
            "question": (
                "restorecon 명령으로 해결했습니다. /mnt에 디스크를 마운트한 것이 문제인가요? "
                "볼륨을 추가한 뒤 수동 복구를 반복하지 않으려면 어떻게 해야 하나요?"
            ),
        }

        prompt = build_progression_retry_question("가상머신 복제 및 스냅샷 생성 시 오류", long_turns, incoming)

        self.assertLessEqual(len(prompt), 4000)
        self.assertIn("restorecon 명령으로 해결했습니다", prompt)
        self.assertTrue(prompt.endswith(PROGRESSION_RETRY_INSTRUCTION))

    def test_knowledge_base_prompt_preserves_selected_solution_within_model_limit(self) -> None:
        turns = [
            {
                "sourcePostId": str(378 + index),
                "postNumber": index + 1,
                "role": "ASSISTANT" if index % 2 else "REQUESTER",
                "content": (f"{index + 1}번째 긴 대화 내용입니다. " * 120),
            }
            for index in range(6)
        ]

        prompt = build_knowledge_base_question("가상머신 복제 및 스냅샷 생성 시 오류", turns, "383")

        self.assertLessEqual(len(prompt), 16000)
        self.assertGreater(len(prompt), 4000)
        self.assertIn("[질문자가 선택한 해결 답변]", prompt)
        self.assertIn("#6 TechFlow-Assistant", prompt)
        self.assertIn("첨부 처리 실패가 명시적으로 기록되지 않았다면", prompt)
        self.assertTrue(prompt.endswith("제목은 만들지 마십시오."))
        ComprehensiveSynthesisRequest(
            queryId=uuid4(), question=prompt, actorId="community-kb:12",
            productVersion="diplo", artifactIds=[], locale="ko-KR", classification="D0",
        )

        with self.assertRaises(ValueError):
            ComprehensiveQueryRequest(
                queryId=uuid4(), question=prompt, actorId="community:12",
                productVersion="diplo", artifactIds=[], locale="ko-KR", classification="D0",
            )

    def test_long_community_post_is_stored_but_compacted_for_the_query_contract(self) -> None:
        long_question = "처음 오류 메시지입니다. " + ("상세 로그 한 줄입니다. " * 500) + "마지막 질문과 오류 코드 E-COMPLETE"
        artifact_id = uuid4()
        incoming = CommunityCaseCreateRequest(
            discussionId="167", discussionUrl="https://community.ablecloud.io/d/167",
            title="가상머신 복제 및 스냅샷 생성 시 오류", question=long_question,
            authorId="12", postId="384", postNumber=11, postAuthorId="12",
            turnRole="REQUESTER", responseRequested=True, artifactIds=[artifact_id],
        )
        prior_turns = [
            {
                "sourcePostId": str(300 + index), "postNumber": index + 1,
                "role": "ASSISTANT" if index % 2 else "REQUESTER",
                "content": f"이전 {index + 1}번 기술지원 내용 " * 100,
            }
            for index in range(10)
        ]

        prompt = build_conversation_question(incoming.title, prior_turns, incoming.model_dump(by_alias=True))

        self.assertEqual(long_question, incoming.question)
        self.assertEqual([artifact_id], incoming.artifact_ids)
        self.assertLessEqual(len(prompt), 4000)
        self.assertIn("처음 오류 메시지입니다", prompt)
        self.assertIn("마지막 질문과 오류 코드 E-COMPLETE", prompt)
        self.assertIn("[긴 내용 자동 압축]", prompt)
        self.assertIn("(첨부자료 포함)", prompt)
        self.assertTrue(prompt.endswith("직전 답변을 반복하지 마십시오."))
        ComprehensiveQueryRequest(
            queryId=uuid4(), question=prompt, actorId="community:12",
            productVersion="diplo", artifactIds=[], locale="ko-KR", classification="D0",
        )


if __name__ == "__main__":
    unittest.main()
