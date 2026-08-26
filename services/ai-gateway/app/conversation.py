"""Community conversation context and lifecycle helpers."""

from __future__ import annotations

import re
from typing import Any, Iterable


ROLE_LABELS = {
    "REQUESTER": "질문자",
    "STAFF": "담당자",
    "ASSISTANT": "TechFlow-Assistant",
}

PROGRESSION_RETRY_INSTRUCTION = (
    "[진행성 재작성 필수]\n"
    "직전 답변의 설명과 점검 목록을 반복하지 마십시오. "
    "관련 제품 기능과 Source 근거에서 확인한 기초 진단과 해결책을 맨 먼저 쓰십시오. 첨부 화면에서는 상태 코드, "
    "API 명령, 컴포넌트 이름과 오류 문구를 읽어 Source 동작과 연결하십시오. 근거가 있는 정확한 CLI 명령, "
    "실행 위치, 정상 판정 기준을 포함하십시오. 원인을 확정하지 못해도 확인된 실패 분기와 안전한 점검 순서를 "
    "먼저 설명한 뒤, 아직 제공되지 않은 자료 한정으로 구체적인 명령 결과나 응답 본문을 요청하십시오."
)


def _excerpt(value: object, limit: int) -> str:
    """Keep both ends of long support text so errors and final questions survive compaction."""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    marker = "\n... [긴 내용 자동 압축] ...\n"
    if limit <= len(marker):
        return text[:limit]
    body_limit = limit - len(marker)
    head = (body_limit * 2) // 3
    return text[:head] + marker + text[-(body_limit - head):]


def source_post_id(request: dict[str, Any]) -> str:
    """Return a stable identifier for legacy and Post-aware Community events."""
    return str(request.get("postId") or f"discussion-{request['discussionId']}-first")


def conversation_artifact_ids(
    turns: Iterable[dict[str, Any]],
    incoming: dict[str, Any],
    *,
    limit: int = 5,
) -> list[str]:
    """Keep the newest unique artifacts available throughout an unresolved conversation."""
    rows = [*list(turns), incoming]
    selected: list[str] = []
    for item in reversed(rows):
        for artifact_id in item.get("artifactIds") or []:
            value = str(artifact_id)
            if value and value not in selected:
                selected.append(value)
            if len(selected) == limit:
                return selected
    return selected


def build_chat_question(
    prior_turns: Iterable[dict[str, Any]],
    current_question: str,
    *,
    limit: int = 16000,
) -> str:
    """Build the Chat support prompt with a guest-OS official-evidence boundary."""
    transcript = "\n".join(
        f"{'사용자' if item.get('role') == 'USER' else '전문 엔지니어'}: {item.get('content') or ''}"
        for item in list(prior_turns)[-12:]
    )
    prompt = (
        "같은 사용자의 기술지원 대화입니다. 이전 맥락을 유지하되 현재 질문을 우선하고, "
        "DOC, ABLESTACK Diplo 현재 코드, 관련 제품 코드 전체, ABLESTACK Europa 프리뷰를 순서대로 "
        "검토해 친절하고 쉬운 말로 답하세요. 일반 가상머신 운영체제의 설정·운영 질문은 해당 운영체제의 "
        "승인된 공식 문서나 도메인 제한 공식 검색 결과를 사용해 실행 가능한 명령과 확인 기준을 먼저 답하세요. "
        "게스트 운영체제 절차를 답할 수 있는데 ABLESTACK 버전이나 관리 서버·호스트 로그를 먼저 요구하지 마세요. "
        "정보가 부족하면 기초 답변 뒤에 다음 분기를 판단하는 자료만 구체적으로 요청하세요.\n\n"
        + (f"이전 대화:\n{transcript}\n\n" if transcript else "")
        + f"현재 질문:\n{current_question}"
    )
    return prompt[:limit]


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
    original_text = _excerpt((original or {}).get("content") or incoming.get("question") or "", 1200)
    transcript: list[str] = []
    for item in rows[-12:]:
        label = ROLE_LABELS.get(str(item.get("role") or "STAFF"), "참여자")
        number = item.get("postNumber") or "-"
        content = _excerpt(item.get("content"), 900)
        suffix = " (첨부자료 포함)" if item.get("artifactIds") else ""
        transcript.append(f"- #{number} {label}{suffix}: {content}")
    human_turns = [item for item in rows if item.get("role") != "ASSISTANT"]
    assistant_turns = [item for item in rows if item.get("role") == "ASSISTANT"]
    latest_human = _excerpt(
        (human_turns[-1] if human_turns else {}).get("content") or incoming.get("question") or "",
        1200,
    )
    previous_assistant = _excerpt((assistant_turns[-1] if assistant_turns else {}).get("content"), 1200)
    prompt = (
        f"[Community 기술지원 제목]\n{title}\n\n"
        f"[최초 질문]\n{original_text}\n\n"
        f"[참여자의 최신 추가 정보 또는 질문]\n{latest_human}\n\n"
        f"[직전 TechFlow 답변]\n{previous_assistant or '없음'}\n\n"
        "[지금까지의 대화]\n"
        + "\n".join(transcript)
        + "\n\n[응답 지침]\n"
        "최초 질문부터 현재 댓글까지 하나의 기술지원 맥락으로 종합하되, 최신 질문에 먼저 직접 답하십시오. "
        "반드시 질문과 관련된 제품 기능, API 명령, UI 컴포넌트와 Source 근거를 분석한 뒤 답하십시오. "
        "첨부 화면이나 파일이 있으면 보이는 상태 코드, API 명령, 컴포넌트 이름, 오류 문구를 빠짐없이 읽고 Source 동작과 연결하십시오. "
        "배경에서 실패한 API 호출과 사용자가 실행한 작업의 실패를 구분하고, 둘이 같다고 단정하지 마십시오. "
        "가장 가능성이 높고 안전한 해결 방법을 맨 먼저 제시하십시오. 근거가 있는 경우 실행 위치, 정확한 CLI 명령, "
        "정상 판정 기준을 함께 적으십시오. 그 방법으로 해결되지 않을 때 적용할 대안과 다음 진단 단계를 이어서 제시하십시오. "
        "정확한 원인을 아직 확정하지 못해도 Source에서 확인한 실패 조건과 현재 자료로 가능한 기초 진단을 먼저 설명하십시오. "
        "추가 자료 요청으로 답변을 시작하지 마십시오. 추가 자료는 기초 답변과 우선 점검을 제공한 뒤에만, "
        "사용자가 아직 제공하지 않은 정확한 API 응답 본문, 명령 결과 또는 로그 이름으로 구체적으로 요청하십시오. "
        "이미 제공된 제품 버전, 첨부 화면, 시각 또는 로그를 다시 요청하지 마십시오. "
        "설명 문장과 CLI 명령을 섞지 마십시오. CLI는 설명 다음 줄의 독립된 ```bash 코드 블록에 넣고, 블록 안에는 바로 복사해 실행할 명령만 쓰십시오. "
        "직전 TechFlow 답변의 원인 설명이나 점검 목록을 다시 말하지 마십시오. 후속 답변은 반드시 진단을 한 단계 더 진행해야 합니다. "
        "SELinux 전체 비활성화, chmod 777, 근거 없는 audit2allow처럼 위험하거나 과도한 우회 조치는 제안하지 마십시오."
    )
    if len(prompt) <= limit:
        return prompt
    compact_instruction = (
        "[응답 지침]\n"
        "관련 기능과 Source를 분석하고 첨부의 상태 코드·API·오류를 Source 동작과 연결하십시오. "
        "최신 질문에 기초 진단, 해결 방법, 근거 있는 CLI 명령, 정상 판정 기준을 먼저 제시하십시오. "
        "CLI는 설명과 분리한 ```bash 코드 블록으로 작성하십시오. 해결되지 않을 때만 대안과 구체적인 결과·로그를 요청하고 "
        "이미 받은 자료를 다시 요청하거나 직전 답변을 반복하지 마십시오."
    )
    compact_prefix = (
        f"[Community 기술지원 제목]\n{title[:200]}\n\n"
        f"[최초 질문]\n{_excerpt(original_text, 650)}\n\n"
        f"[참여자의 최신 추가 정보 또는 질문]\n{_excerpt(latest_human, 900)}\n\n"
        f"[직전 TechFlow 답변]\n{_excerpt(previous_assistant, 650) or '없음'}\n\n"
        "[최근 대화]\n"
    )
    compact_suffix = f"\n\n{compact_instruction}"
    if len(compact_prefix) + len(compact_suffix) > limit:
        raise ValueError("conversation essentials exceed the question limit")
    available = limit - len(compact_prefix) - len(compact_suffix)
    compact_transcript: list[str] = []
    used = 0
    for row in reversed(transcript):
        row = _excerpt(row, 500)
        separator = 1 if compact_transcript else 0
        remaining = available - used - separator
        if remaining <= 0:
            break
        compact_transcript.append(row[:remaining])
        used += min(len(row), remaining) + separator
    compact_transcript.reverse()
    return compact_prefix + "\n".join(compact_transcript) + compact_suffix


def build_progression_retry_question(
    title: str,
    turns: Iterable[dict[str, Any]],
    incoming: dict[str, Any],
    *,
    limit: int = 4000,
) -> str:
    """Build a retry prompt while reserving space for the mandatory rewrite instruction."""
    suffix = f"\n\n{PROGRESSION_RETRY_INSTRUCTION}"
    if len(suffix) >= limit:
        raise ValueError("progression retry instruction must be shorter than the question limit")
    base = build_conversation_question(title, turns, incoming, limit=limit - len(suffix))
    return base + suffix


COMMAND_MARKERS = (
    "`", "sudo ", "systemctl ", "journalctl ", "ausearch ", "findmnt ", "namei ", "getfacl ",
    "matchpathcon ", "restorecon ", "virsh ", "grep ", "ls -",
)
ACTION_MARKERS = (
    "재시작", "마이그레이션", "복구", "수정", "변경", "적용", "재시도", "해제", "활성화", "비활성화",
    "설치", "업데이트", "교체", "삭제", "추가", "선택", "재연결", "초기화",
)


def _plain_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_./:-]{3,}|[가-힣]{2,}", value.casefold()))


def _similarity(left: str, right: str) -> float:
    left_tokens = _plain_tokens(left)
    right_tokens = _plain_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _row_text(row: object) -> str:
    if isinstance(row, str):
        return row.strip()
    if isinstance(row, dict):
        return str(row.get("action") or row.get("text") or row.get("title") or row.get("finding") or "").strip()
    return ""


def community_result_advances(result: dict[str, Any], turns: Iterable[dict[str, Any]]) -> bool:
    """Return whether a follow-up adds a concrete step instead of repeating the last reply."""
    previous = [str(item.get("content") or "") for item in turns if item.get("role") == "ASSISTANT"]
    if not previous:
        return True
    if str(result.get("state") or "").upper() == "ABSTAINED":
        return False
    report = result.get("report") or {}
    candidates = [
        _row_text(item)
        for item in (*list(report.get("recommendedActions") or []), *list(report.get("unknowns") or []))
    ]
    candidates = [item for item in candidates if item]
    if not candidates:
        return False
    previous_text = previous[-1]
    for candidate in candidates:
        has_command = any(marker in candidate.casefold() for marker in COMMAND_MARKERS)
        if has_command and candidate.casefold() not in previous_text.casefold():
            return True
        has_action = any(marker in candidate.casefold() for marker in ACTION_MARKERS)
        if has_action and _similarity(candidate, previous_text) < 0.70:
            return True
    return False


def build_knowledge_base_question(
    title: str,
    turns: Iterable[dict[str, Any]],
    resolved_post_id: str,
    *,
    limit: int = 16000,
) -> str:
    """Build a bounded final synthesis prompt that always preserves the selected solution."""
    rows = sorted(
        list(turns),
        key=lambda item: (int(item.get("postNumber") or 0), str(item.get("sourcePostId") or "")),
    )

    selected_row = next(
        (item for item in rows if str(item.get("sourcePostId")) == resolved_post_id),
        None,
    )
    selected_label = ROLE_LABELS.get(str((selected_row or {}).get("role") or "STAFF"), "참여자")
    selected_number = (selected_row or {}).get("postNumber") or "-"
    selected_content = str((selected_row or {}).get("content") or "선택된 답변 본문을 찾을 수 없음").strip()[:1600]
    selected_section = (
        "[질문자가 선택한 해결 답변]\n"
        f"- #{selected_number} {selected_label}: {selected_content}"
    )
    instruction = (
        "[최종 Knowledge Base 작성 지침]\n"
        "질문자가 해결 답변으로 선택한 내용을 중심으로 전체 대화를 종합하십시오. "
        "확인되지 않은 추측이나 대화 중 폐기된 가설은 최종 해결책으로 쓰지 마십시오. "
        "증상에는 사용자가 겪은 현상만, 원인에는 확인된 원인만, 해결 방법에는 실제 해결에 기여한 조치만 배치하십시오. "
        "적용 버전에는 이 해결 방법을 실제 적용해도 되는 ABLESTACK 제품 버전만 적으십시오. "
        "대화에 첨부 처리 실패가 명시적으로 기록되지 않았다면 첨부파일을 내려받지 못했거나 화면을 확인하지 못했다는 문장을 만들지 마십시오. "
        "미출시 코드 비교, 개선 미확인, 제품 보완 검토 같은 내부 판단은 사용자 문서에 쓰지 마십시오. "
        "일반 사용자도 이해할 수 있는 짧고 쉬운 한국어를 사용하십시오. 제목은 만들지 마십시오."
    )
    prefix = f"[Community 해결 완료 주제]\n{title[:200]}\n\n{selected_section}\n\n[전체 대화]\n"
    suffix = f"\n\n{instruction}"
    if len(prefix) + len(suffix) > limit:
        raise ValueError("knowledge base selected solution and instruction exceed the question limit")

    transcript: list[str] = []
    for item in rows:
        if str(item.get("sourcePostId")) == resolved_post_id:
            continue
        label = ROLE_LABELS.get(str(item.get("role") or "STAFF"), "참여자")
        content = str(item.get("content") or "").strip()[:900]
        transcript.append(f"- #{item.get('postNumber') or '-'} {label}: {content}")

    available = limit - len(prefix) - len(suffix)
    selected_transcript: list[str] = []
    used = 0
    for row in reversed(transcript):
        separator = 1 if selected_transcript else 0
        remaining = available - used - separator
        if remaining <= 0:
            break
        selected_transcript.append(row[:remaining])
        used += min(len(row), remaining) + separator
    selected_transcript.reverse()
    return prefix + "\n".join(selected_transcript) + suffix


def conversation_state_for_draft(draft: dict[str, Any]) -> str:
    """A generated reply moves directly to publication or waits for more requester data."""
    return "ANALYZING" if draft.get("draftAnswer") else "WAITING_REQUESTER"
