"""Community conversation context and lifecycle helpers."""

from __future__ import annotations

from typing import Any, Iterable


ROLE_LABELS = {
    "REQUESTER": "질문자",
    "STAFF": "담당자",
    "ASSISTANT": "TechFlow-Assistant",
}


def source_post_id(request: dict[str, Any]) -> str:
    """Return a stable identifier for legacy and Post-aware Community events."""
    return str(request.get("postId") or f"discussion-{request['discussionId']}-first")


def build_conversation_question(
    title: str,
    turns: Iterable[dict[str, Any]],
    incoming: dict[str, Any],
    *,
    limit: int = 4000,
) -> str:
    """Build a bounded prompt that preserves the original question and recent support turns."""
    rows = list(turns)
    incoming_id = source_post_id(incoming)
    if not any(str(item.get("sourcePostId")) == incoming_id for item in rows):
        rows.append({
            "sourcePostId": incoming_id,
            "postNumber": incoming.get("postNumber"),
            "authorUserId": incoming.get("postAuthorId") or incoming.get("authorId"),
            "role": incoming.get("turnRole") or "REQUESTER",
            "content": incoming.get("question") or "",
            "artifactIds": list(incoming.get("artifactIds") or []),
        })
    rows.sort(key=lambda item: (int(item.get("postNumber") or 0), str(item.get("sourcePostId") or "")))
    original = next((item for item in rows if item.get("role") == "REQUESTER"), rows[0] if rows else None)
    original_text = str((original or {}).get("content") or incoming.get("question") or "")[:1200]
    transcript: list[str] = []
    for item in rows[-12:]:
        label = ROLE_LABELS.get(str(item.get("role") or "STAFF"), "참여자")
        number = item.get("postNumber") or "-"
        content = str(item.get("content") or "").strip()[:900]
        suffix = " (첨부자료 포함)" if item.get("artifactIds") else ""
        transcript.append(f"- #{number} {label}{suffix}: {content}")
    prompt = (
        f"[Community 기술지원 제목]\n{title}\n\n"
        f"[최초 질문]\n{original_text}\n\n"
        "[지금까지의 대화]\n"
        + "\n".join(transcript)
        + "\n\n[응답 지침]\n"
        "최초 질문부터 현재 댓글까지 하나의 기술지원 맥락으로 종합하십시오. "
        "이미 수행한 조치와 결과를 반복해서 요청하지 마십시오. 정확한 판단에 필요한 정보가 부족하면 "
        "안전한 예비 판단과 함께 질문자가 제공할 자료를 구체적으로 요청하십시오."
    )
    if len(prompt) <= limit:
        return prompt
    return (
        f"[Community 기술지원 제목]\n{title[:200]}\n\n[최초 질문]\n{original_text[:800]}\n\n"
        f"[최근 대화]\n{'\n'.join(transcript[-6:])}\n\n[응답 지침]\n"
        "전체 대화의 연속선에서 답하고, 부족한 정보는 구체적으로 요청하십시오."
    )[:limit]


def build_knowledge_base_question(
    title: str,
    turns: Iterable[dict[str, Any]],
    resolved_post_id: str,
    *,
    limit: int = 6000,
) -> str:
    """Build a final synthesis prompt after the requester marks a solution."""
    rows = sorted(
        list(turns),
        key=lambda item: (int(item.get("postNumber") or 0), str(item.get("sourcePostId") or "")),
    )
    transcript: list[str] = []
    for item in rows[-20:]:
        label = ROLE_LABELS.get(str(item.get("role") or "STAFF"), "참여자")
        content = str(item.get("content") or "").strip()[:1200]
        selected = " [질문자가 선택한 해결 답변]" if str(item.get("sourcePostId")) == resolved_post_id else ""
        transcript.append(f"- #{item.get('postNumber') or '-'} {label}{selected}: {content}")
    prompt = (
        f"[Community 해결 완료 주제]\n{title}\n\n"
        "[전체 대화]\n"
        + "\n".join(transcript)
        + "\n\n[최종 Knowledge Base 작성 지침]\n"
        "질문자가 해결 답변으로 선택한 내용을 중심으로 전체 대화를 종합하십시오. "
        "확인되지 않은 추측이나 대화 중 폐기된 가설은 최종 해결책으로 쓰지 마십시오. "
        "증상에는 사용자가 겪은 현상만, 원인에는 확인된 원인만, 해결 방법에는 실제 해결에 기여한 조치만 배치하십시오. "
        "일반 사용자도 이해할 수 있는 짧고 쉬운 한국어를 사용하십시오. 제목은 만들지 마십시오."
    )
    return prompt[:limit]


def conversation_state_for_draft(draft: dict[str, Any]) -> str:
    """A generated reply moves directly to publication or waits for more requester data."""
    return "ANALYZING" if draft.get("draftAnswer") else "WAITING_REQUESTER"
