"""Community conversation context and lifecycle helpers."""

from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any, Iterable

from .embedding import MAX_INPUT_BYTES


ROLE_LABELS = {
    "REQUESTER": "질문자",
    "STAFF": "담당자",
    "ASSISTANT": "TechFlow-Assistant",
}

_RESOLUTION_UPDATE_MARKERS = (
    "더 이상 발생하지", "더 이상 문제가", "문제가 해결", "해결되었습니다", "해결됐", "해결되었",
    "정상 동작", "정상적으로 동작", "조치 후 정상", "문제가 없어", "오류가 없어", "성공했습니다",
)

PROGRESSION_RETRY_INSTRUCTION = (
    "[진행성 재작성 필수]\n"
    "직전 답변의 설명과 점검 목록을 반복하지 마십시오. "
    "관련 제품 기능과 Source 근거에서 확인한 기초 진단과 해결책을 맨 먼저 쓰십시오. 첨부 화면에서는 상태 코드, "
    "API 명령, 컴포넌트 이름과 오류 문구를 읽어 Source 동작과 연결하십시오. 근거가 있는 정확한 CLI 명령, "
    "실행 위치, 정상 판정 기준을 포함하십시오. 원인을 확정하지 못해도 확인된 실패 분기와 안전한 점검 순서를 "
    "먼저 설명한 뒤, 아직 제공되지 않은 자료 한정으로 구체적인 명령 결과나 응답 본문을 요청하십시오."
)

ACTIONABILITY_RETRY_INSTRUCTION = (
    "[실행 안내 재작성 필수]\n"
    "Linux 운영 명령이나 로그 확인을 안내할 때는 실행 대상, SSH 또는 콘솔 접속 예시, 필요한 권한, "
    "정확한 systemd .service 이름, 복사 가능한 명령, 정상 판정 기준을 함께 쓰십시오. "
    "로그는 journalctl -u <service> 또는 /var/log/...의 정확한 경로와 상태 변경 전후 시간 범위를 제시하십시오. "
    "공개 Community에 올리기 전에 BMC 암호, API Key, Token, Cookie와 내부 인프라 식별자를 마스킹하도록 안내하십시오. "
    "근거 없이 DB 수정, 서비스 재시작, 호스트 전원 작업을 제안하지 마십시오."
)

_IDENTIFIER_TOKEN = re.compile(r"(?<![A-Za-z0-9_.:/-])[A-Za-z]{8,48}(?![A-Za-z0-9_.:/-])")
_LITERAL_EVIDENCE = re.compile(r"```.*?```|`[^`]*`|https?://\S+", re.DOTALL | re.IGNORECASE)
_TYPO_PROTECTED_TERMS = {
    "available", "suspect", "checking", "degraded", "recovering", "recovered", "fencing", "fenced",
    "disabled", "enabled", "ineligible", "systemctl", "journalctl", "libvirtd", "virtqemud", "powershell",
    "community", "techflow", "assistant", "localhost",
}
_LINUX_OPERATION = re.compile(r"\b(?:sudo\s+)?(?:systemctl|journalctl|virsh|grep|tail)\b", re.IGNORECASE)
_SSH_EXAMPLE = re.compile(r"\bssh(?:\s+-p\s+\S+)?\s+\S+@\S+", re.IGNORECASE)
_SERVICE_UNIT = re.compile(r"\b[a-zA-Z0-9_.@-]+\.service\b")


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


def _utf8_excerpt(value: object, limit: int) -> str:
    """Keep both ends of text within an exact UTF-8 byte budget."""
    text = str(value or "").strip()
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    marker = "\n... [긴 내용 자동 압축] ...\n"
    marker_bytes = marker.encode("utf-8")
    if limit <= len(marker_bytes):
        return encoded[:limit].decode("utf-8", errors="ignore")
    body_limit = limit - len(marker_bytes)
    head_limit = (body_limit * 2) // 3
    tail_limit = body_limit - head_limit
    head = encoded[:head_limit].decode("utf-8", errors="ignore")
    tail = encoded[-tail_limit:].decode("utf-8", errors="ignore") if tail_limit else ""
    return head + marker + tail


def _plain_identifier_tokens(value: object) -> list[str]:
    text = _LITERAL_EVIDENCE.sub(" ", str(value or ""))
    return _IDENTIFIER_TOKEN.findall(text)


def probable_identifier_typos(
    prior_turns: Iterable[dict[str, Any]], current_text: object, *, limit: int = 3,
) -> tuple[tuple[str, str], ...]:
    """Find unique, low-risk identifier typos without changing the user's original text."""
    canonical: dict[str, str] = {}
    for item in prior_turns:
        if str(item.get("role") or "") != "ASSISTANT":
            continue
        for token in _plain_identifier_tokens(item.get("content")):
            canonical.setdefault(token.casefold(), token)
    if not canonical:
        return ()

    found: list[tuple[str, str]] = []
    for token in _plain_identifier_tokens(current_text):
        normalized = token.casefold()
        if normalized in canonical or normalized in _TYPO_PROTECTED_TERMS:
            continue
        candidates: list[tuple[float, str, str]] = []
        for expected, display in canonical.items():
            if expected in _TYPO_PROTECTED_TERMS or expected[:3] != normalized[:3]:
                continue
            if abs(len(expected) - len(normalized)) > 2:
                continue
            score = SequenceMatcher(None, normalized, expected).ratio()
            if score >= 0.90:
                candidates.append((score, expected, display))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        if not candidates or (len(candidates) > 1 and candidates[0][0] == candidates[1][0]):
            continue
        found.append((token, candidates[0][2]))
        if len(found) == limit:
            break
    return tuple(found)


def _typo_guidance(candidates: Iterable[tuple[str, str]]) -> str:
    rows = list(candidates)
    if not rows:
        return ""
    mappings = "\n".join(f"- `{actual}` → `{expected}`" for actual, expected in rows)
    return (
        "[문맥상 오타 후보]\n"
        f"{mappings}\n"
        "원문을 변경하지 마십시오. 앞선 대화와 제공된 Source 근거가 정식 표기를 뒷받침하면 "
        "오타로 보고 진행한다고 한 문장으로 알린 뒤 핵심 증상 분석을 계속하십시오. "
        "오타 확인을 unknowns로 반복 요청하지 마십시오. 실제 화면·로그의 값일 가능성은 기초 답변 뒤에만 짧게 덧붙이십시오."
    )


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
    limit: int = MAX_INPUT_BYTES,
) -> str:
    """Build a Chat prompt bounded by the downstream embedding UTF-8 limit."""
    instruction = (
        "같은 사용자의 기술지원 대화입니다. 이전 맥락을 유지하되 현재 질문을 우선하고, "
        "DOC, ABLESTACK Diplo 현재 코드, 관련 제품 코드 전체, ABLESTACK Europa 프리뷰를 순서대로 "
        "검토해 친절하고 쉬운 말로 답하세요. 일반 가상머신 운영체제의 설정·운영 질문은 해당 운영체제의 "
        "승인된 공식 문서나 도메인 제한 공식 검색 결과를 사용해 실행 가능한 명령과 확인 기준을 먼저 답하세요. "
        "게스트 운영체제 절차를 답할 수 있는데 ABLESTACK 버전이나 관리 서버·호스트 로그를 먼저 요구하지 마세요. "
        "정보가 부족하면 기초 답변 뒤에 다음 분기를 판단하는 자료만 구체적으로 요청하세요."
    )
    current_prefix = "\n\n현재 질문:\n"
    history_prefix = "\n\n이전 대화:\n"
    fixed_bytes = len((instruction + current_prefix + history_prefix).encode("utf-8"))
    current_budget = max(0, min(limit // 2, limit - fixed_bytes))
    current = current_prefix + _utf8_excerpt(current_question, current_budget)
    remaining = max(0, limit - len((instruction + current + history_prefix).encode("utf-8")))
    rows = [
        f"{'사용자' if item.get('role') == 'USER' else '전문 엔지니어'}: "
        f"{_utf8_excerpt(item.get('content'), 2000)}"
        for item in list(prior_turns)[-12:]
    ]
    while rows and len("\n".join(rows).encode("utf-8")) > remaining:
        rows.pop(0)
    joined = "\n".join(rows)
    transcript = history_prefix + joined if rows else ""
    prompt = instruction + transcript + current
    if len(prompt.encode("utf-8")) > limit:
        raise ValueError("Chat prompt exceeds the UTF-8 byte boundary")
    return prompt


def is_resolution_progress_update(value: object) -> bool:
    """Recognize a requester's successful outcome without requiring RAG evidence for an acknowledgment."""
    normalized = str(value or "").casefold()
    return any(marker in normalized for marker in _RESOLUTION_UPDATE_MARKERS)


def resolution_progress_result(value: object) -> dict[str, Any] | None:
    """Return a deterministic, source-safe follow-up for a confirmed successful outcome."""
    if not is_resolution_progress_update(value):
        return None
    normalized = str(value or "").casefold()
    tag_resolution = (
        "물리네트워크" in normalized
        and "오퍼링" in normalized
        and "태그" in normalized
    )
    summary = "조치 후 문제가 더 이상 발생하지 않는다는 결과를 확인했습니다."
    diagnoses = []
    actions = [
        "현재 정상 동작하는 설정값을 운영 기록에 남겨 같은 유형의 네트워크를 만들 때 재사용하세요.",
        "문제 해결에 기여한 답변을 해결 답변으로 선택하면 전체 대화를 Knowledge Base 문서로 정리할 수 있습니다.",
    ]
    if tag_resolution:
        summary = (
            "물리 네트워크 태그와 네트워크 오퍼링 태그를 일치시킨 뒤 요청 실패가 더 이상 발생하지 않는다는 "
            "결과를 확인했습니다."
        )
        diagnoses.append({
            "title": "태그 불일치로 대상 물리 네트워크에 사용할 네트워크 오퍼링을 찾지 못한 설정 문제",
            "likelihood": "HIGH",
            "evidenceIds": [],
        })
        actions.insert(
            0,
            "재발을 막으려면 물리 네트워크와 네트워크 오퍼링의 태그를 동일한 값으로 관리하고 생성 전 두 값을 대조하세요.",
        )
    return {
        "state": "ANSWERED",
        "report": {
            "state": "ANSWERED",
            "summary": summary,
            "observedFacts": ["질문자가 조치 후 동일한 문제가 더 이상 발생하지 않는다고 확인했습니다."],
            "diagnoses": diagnoses,
            "recommendedActions": actions,
            "unknowns": [],
            "confidence": "HIGH" if tag_resolution else "MEDIUM",
            "citationsUsed": [],
            "artifactEvidence": [],
            "currentAssessment": "CURRENT_CONFIG_ERROR" if tag_resolution else "CURRENT_NORMAL",
            "previewAssessment": "NOT_APPLICABLE",
            "previewGuidance": None,
            "abstainReason": None,
        },
        "citations": [],
        "generationProviderCalled": False,
        "providerProfileId": None,
    }


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
    typo_guidance = _typo_guidance(probable_identifier_typos(rows, latest_human))
    typo_section = f"[오타 처리 안내]\n{typo_guidance}\n\n" if typo_guidance else ""
    prompt = (
        f"[Community 기술지원 제목]\n{title}\n\n"
        f"[최초 질문]\n{original_text}\n\n"
        f"[참여자의 최신 추가 정보 또는 질문]\n{latest_human}\n\n"
        f"{typo_section}"
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
        "문맥상 명백한 오타 후보는 짧게 가정하고 핵심 분석을 계속하십시오. 오타 확인만을 위해 답변을 중단하지 마십시오. "
        "Linux 운영 명령과 로그를 요청할 때는 실행 대상, SSH 또는 콘솔 접속 예시, 필요한 권한, 정확한 서비스명과 로그 경로, 시간 범위, 정상 기준을 포함하십시오. "
        "공개 답변에는 BMC 암호, API Key, Token, Cookie와 내부 인프라 식별자 마스킹 방법을 포함하십시오. "
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
        "명백한 오타는 짧게 알리고 분석을 계속하십시오. Linux 운영 명령·로그에는 실행 대상, SSH/콘솔 접속, 권한, "
        "정확한 .service 이름, 로그 경로, 시간 범위와 마스킹 안내를 포함하십시오. "
        "CLI는 설명과 분리한 ```bash 코드 블록으로 작성하십시오. 해결되지 않을 때만 대안과 구체적인 결과·로그를 요청하고 "
        "이미 받은 자료를 다시 요청하거나 직전 답변을 반복하지 마십시오."
    )
    compact_prefix = (
        f"[Community 기술지원 제목]\n{title[:200]}\n\n"
        f"[최초 질문]\n{_excerpt(original_text, 650)}\n\n"
        f"[참여자의 최신 추가 정보 또는 질문]\n{_excerpt(latest_human, 900)}\n\n"
        f"{_excerpt(typo_section, 500)}"
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
    actionability_issues: Iterable[str] = (),
) -> str:
    """Build a retry prompt while reserving space for the mandatory rewrite instruction."""
    issues = tuple(actionability_issues)
    actionability = (
        f"\n\n{ACTIONABILITY_RETRY_INSTRUCTION}\n누락 항목: {', '.join(issues)}" if issues else ""
    )
    suffix = f"\n\n{PROGRESSION_RETRY_INSTRUCTION}{actionability}"
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


def community_actionability_issues(result: dict[str, Any]) -> tuple[str, ...]:
    """Return missing operational context for Linux commands and log collection requests."""
    if str(result.get("state") or "").upper() != "ANSWERED":
        return ()
    report = result.get("report") or {}
    rows = [
        _row_text(item)
        for item in (*list(report.get("recommendedActions") or []), *list(report.get("unknowns") or []))
    ]
    text = "\n".join(item for item in rows if item)
    operation_rows = [item for item in rows if _LINUX_OPERATION.search(item)]
    has_linux_operation = bool(operation_rows)
    has_log_request = "로그" in text or "/var/log/" in text or "journalctl" in text.casefold()
    if not has_linux_operation and not has_log_request:
        return ()

    issues: list[str] = []
    lowered = text.casefold()
    if not _SSH_EXAMPLE.search(text) and not any(
        marker in text for marker in ("콘솔로 접속", "콘솔 또는 SSH", "터미널에 접속")
    ):
        issues.append("missing-access-example")
    target_markers = ("관리 서버", "KVM 호스트", "호스트에서", "가상머신 안", "게스트에서")
    if has_linux_operation and any(not any(marker in row for marker in target_markers) for row in operation_rows):
        issues.append("missing-execution-target")
    if not any(marker in lowered for marker in ("sudo", "root", "관리자 권한")):
        issues.append("missing-required-role")
    if ("systemctl" in lowered or "journalctl" in lowered) and not _SERVICE_UNIT.search(text):
        issues.append("missing-service-unit")
    if not any(marker in text for marker in ("정상 기준", "성공 기준", "이면 정상", "오류 없이", "Active: active")):
        issues.append("missing-success-criteria")
    if has_log_request and "/var/log/" not in text and not re.search(
        r"journalctl\s+-u\s+\S+", text, re.IGNORECASE,
    ):
        issues.append("missing-log-source")
    if has_log_request and not (
        ("--since" in lowered and "--until" in lowered)
        or any(marker in text for marker in ("상태 변경 전후", "발생 시각 전후", "오류 시각 전후"))
    ):
        issues.append("missing-time-window")
    if has_log_request and not any(
        marker in lowered
        for marker in ("암호", "비밀번호", "api key", "token", "토큰", "cookie", "마스킹", "제거")
    ):
        issues.append("missing-redaction-guidance")
    return tuple(issues)


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
