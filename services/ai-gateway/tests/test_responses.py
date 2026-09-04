from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.provider import ProviderContractError, ResponsesRequest, ResponsesResult
from app.responses import (
    ANSWER_SCHEMA,
    CircuitBreaker,
    OpenAIResponsesAdapter,
    ResponsesProviderError,
    context_from_results,
    decide_generation,
    stable_safety_identifier,
    validate_grounded_result,
)
from app.versioned_assist import expand_retrieval_question


def result(
    chunk_id: str = "chunk-1",
    *,
    repository: str = "ablecloud-team/ablestack-genie",
    branch: str = "master",
    commit: str = "a" * 40,
    source_kind: str = "SOURCE_CODE",
) -> dict[str, object]:
    return {
        "chunkId": chunk_id,
        "sourceVersionId": "00000000-0000-0000-0000-000000000001",
        "sourceProfileId": "GENIE_MASTER",
        "repository": repository,
        "branch": branch,
        "commit": commit,
        "path": "src/main.py",
        "startLine": 1,
        "endLine": 4,
        "symbol": "main",
        "sourceKind": source_kind,
        "content": "def main(): return 'ok'",
    }


class _FakeResponse(SimpleNamespace):
    def model_dump(self) -> dict[str, object]:
        return getattr(self, "payload", {})


class _FakeResponses:
    def __init__(self, output_text: str, payload: dict[str, object] | None = None) -> None:
        self.output_text = output_text
        self.payload = payload or {}
        self.kwargs: dict[str, object] | None = None

    def create(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        return _FakeResponse(
            output_text=self.output_text,
            model="gpt-5.6-terra-2026-07-01",
            id="resp-safe",
            _request_id="req-safe",
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
            payload=self.payload,
        )


class _FakeClient:
    def __init__(self, output_text: str, payload: dict[str, object] | None = None) -> None:
        self.responses = _FakeResponses(output_text, payload)


class _SequenceResponses:
    def __init__(self, rows: list[tuple[str, dict[str, object]]]) -> None:
        self.rows = list(rows)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        output_text, payload = self.rows.pop(0)
        return _FakeResponse(
            output_text=output_text, model="gpt-5.6-terra-2026-07-01", id="resp-sequence",
            _request_id="req-sequence", usage=SimpleNamespace(input_tokens=100, output_tokens=20),
            payload=payload,
        )


class _SequenceClient:
    def __init__(self, rows: list[tuple[str, dict[str, object]]]) -> None:
        self.responses = _SequenceResponses(rows)


class ResponsesPolicyTest(unittest.TestCase):
    def test_routing_default_and_escalation(self) -> None:
        default = decide_generation([result()], compatibility_set_id=None, source_profile_ids=["GENIE_MASTER"])
        self.assertEqual("OPENAI_RAG_DEFAULT_V1", default.profile_id)
        escalation = decide_generation(
            [result(), result("chunk-2", commit="b" * 40)],
            compatibility_set_id=None,
            source_profile_ids=["GENIE_MASTER"],
        )
        self.assertEqual("OPENAI_RAG_ESCALATION_V1", escalation.profile_id)

    def test_document_and_code_from_same_version_stays_on_default(self) -> None:
        mixed = decide_generation(
            [result(), result("chunk-2", source_kind="DOCUMENTATION")],
            compatibility_set_id=None,
            source_profile_ids=["GENIE_MASTER"],
        )
        self.assertEqual("OPENAI_RAG_DEFAULT_V1", mixed.profile_id)

    def test_conflicting_branches_abstain_before_generation(self) -> None:
        decision = decide_generation(
            [result(), result("chunk-2", branch="develop")],
            compatibility_set_id=None,
            source_profile_ids=["GENIE_MASTER"],
        )
        self.assertEqual(("ABSTAINED", "branch-conflict"), (decision.state, decision.abstain_reason))

    def test_test_only_evidence_abstains(self) -> None:
        decision = decide_generation(
            [result(source_kind="TEST_CODE")], compatibility_set_id=None, source_profile_ids=["GENIE_MASTER"]
        )
        self.assertEqual("test-only-evidence", decision.abstain_reason)

    def test_cross_repository_requires_compatibility_set(self) -> None:
        decision = decide_generation(
            [result(), result("chunk-2", repository="ablecloud-team/ablestack-wall")],
            compatibility_set_id=None,
            source_profile_ids=["GENIE_MASTER", "WALL_MAIN"],
        )
        self.assertEqual("compatibility-conflict", decision.abstain_reason)

    def test_safety_identifier_is_stable_and_pseudonymous(self) -> None:
        salt = b"a" * 32
        first = stable_safety_identifier("operator@example.com", salt)
        self.assertEqual(first, stable_safety_identifier("operator@example.com", salt))
        self.assertNotEqual(first, stable_safety_identifier("other@example.com", salt))
        self.assertNotIn("operator", first)
        self.assertLessEqual(len(first), 64)

    def test_postvalidation_rejects_unknown_citation(self) -> None:
        context = context_from_results([result()])
        generated = ResponsesResult(
            "ANSWERED", "answer", ("unknown",), "gpt-5.6-terra", "gpt-5.6-terra",
            "req", "resp", 1, 1,
        )
        state, answer, reason, cited = validate_grounded_result(generated, context)
        self.assertEqual(("ABSTAINED", None, "citation-validation-failed", ()), (state, answer, reason, cited))

    def test_openai_adapter_disables_storage_background_and_tools(self) -> None:
        fake = _FakeClient(
            '{"state":"ANSWERED","answer":"근거 답변","citationsUsed":["chunk-1"],"abstainReason":null}'
        )
        adapter = OpenAIResponsesAdapter("unused", "unused", client=fake)
        request = ResponsesRequest(
            query_id="query-1",
            question="질문",
            profile_id="OPENAI_RAG_DEFAULT_V1",
            context=context_from_results([result()]),
            safety_identifier="tf-" + "a" * 61,
        )
        generated = adapter.generate(request)
        kwargs = fake.responses.kwargs or {}
        self.assertEqual("ANSWERED", generated.state)
        self.assertFalse(kwargs["store"])
        self.assertFalse(kwargs["background"])
        self.assertEqual([], kwargs["tools"])
        self.assertTrue(kwargs["text"]["format"]["strict"])
        self.assertEqual(ANSWER_SCHEMA, kwargs["text"]["format"]["schema"])

    def test_invalid_provider_json_is_terminal_and_sanitized(self) -> None:
        adapter = OpenAIResponsesAdapter("unused", "unused", client=_FakeClient("not-json SECRET-CONTENT"))
        request = ResponsesRequest(
            "query-1", "question", "OPENAI_RAG_DEFAULT_V1", context_from_results([result()]),
            safety_identifier="tf-" + "a" * 61,
        )
        with self.assertRaises(ResponsesProviderError) as raised:
            adapter.generate(request)
        self.assertEqual("PROVIDER_INVALID_RESPONSE", raised.exception.code)
        self.assertNotIn("SECRET-CONTENT", str(raised.exception))

    def test_official_web_search_is_required_domain_restricted_and_source_verified(self) -> None:
        url = "https://kubernetes.io/docs/tasks/debug/debug-cluster/"
        fake = _FakeClient(
            '{"facts":[{"statement":"Inspect cluster debugging information.","title":"Debug cluster","url":"' + url + '"}]}',
            {"output": [{"type": "web_search_call", "action": {"sources": [{"url": url}]}}]},
        )
        adapter = OpenAIResponsesAdapter("unused", "unused", client=fake)
        results = adapter.search_official_references("Koral Pod가 시작되지 않습니다.")
        kwargs = fake.responses.kwargs or {}
        self.assertEqual(1, len(results))
        self.assertEqual("required", kwargs["tool_choice"])
        tool = kwargs["tools"][0]
        self.assertEqual("web_search", tool["type"])
        self.assertIn("kubernetes.io", tool["filters"]["allowed_domains"])
        self.assertIn("official Kubernetes", kwargs["input"][1]["content"])
        self.assertFalse(kwargs["store"])
        self.assertFalse(kwargs["background"])

    def test_official_web_search_retries_invalid_contract_once(self) -> None:
        url = "https://manpages.debian.org/bookworm/cifs-utils/mount.cifs.8.en.html"
        client = _SequenceClient([
            (
                '{"facts":[{"statement":"Install packages.","title":"apt-get(8)","url":"'
                'https://manpages.debian.org/bookworm/apt/apt-get.8.en.html"}]}',
                {"output": [{"type": "web_search_call", "action": {"sources": [{
                    "url": "https://manpages.debian.org/bookworm/apt/apt-get.8.en.html"
                }]}}]},
            ),
            (
                '{"facts":[{"statement":"mount.cifs mounts an SMB share.","title":"mount.cifs(8)","url":"'
                + url + '"}]}',
                {"output": [{"type": "web_search_call", "action": {"sources": [{"url": url}]}}]},
            ),
        ])
        adapter = OpenAIResponsesAdapter("unused", "unused", client=client)

        results = adapter.search_official_references(
            "Debian 12 가상머신에서 SMB 공유를 마운트하는 명령을 알려주세요."
        )

        self.assertEqual(1, len(results))
        self.assertEqual(2, len(client.responses.calls))
        self.assertIn("RETRY:", client.responses.calls[1]["input"][0]["content"])

    def test_long_kb_question_must_use_bounded_official_search_text(self) -> None:
        url = "https://kubernetes.io/docs/tasks/debug/debug-cluster/"
        fake = _FakeClient(
            '{"facts":[{"statement":"Inspect cluster debugging information.","title":"Debug cluster","url":"'
            + url
            + '"}]}',
            {"output": [{"type": "web_search_call", "action": {"sources": [{"url": url}]}}]},
        )
        adapter = OpenAIResponsesAdapter("unused", "unused", client=fake)
        long_question = "Koral Pod가 시작되지 않습니다. " + ("긴 해결 대화 " * 1200)

        with self.assertRaises(ProviderContractError):
            adapter.search_official_references(long_question)

        bounded = expand_retrieval_question(long_question)
        results = adapter.search_official_references(bounded)

        self.assertLessEqual(len(bounded.encode("utf-8")), 4000)
        self.assertEqual(1, len(results))

    def test_circuit_breaker_opens_after_failure_threshold(self) -> None:
        breaker = CircuitBreaker(minimum_calls=10, failure_rate=0.5)
        for _ in range(10):
            self.assertTrue(breaker.before_call())
            breaker.record(False)
        self.assertFalse(breaker.before_call())


if __name__ == "__main__":
    unittest.main()
