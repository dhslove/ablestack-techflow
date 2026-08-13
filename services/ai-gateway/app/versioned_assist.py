"""ABLESTACK Diplo-current and Europa-preview evidence policy."""

from __future__ import annotations

import re
from typing import Any, Iterable


CURRENT_SOURCE_PROFILES: tuple[str, ...] = (
    "SHARED_DOCS",
    "CLOUD_DIPLO",
    "WALL_MAIN",
    "COCKPIT_DIPLO",
    "GENIE_MASTER",
    "KICKSTART_MASTER",
    "QEMU_EXEC_TOOLS_MAIN",
)
PREVIEW_SOURCE_PROFILE = "CLOUD_EUROPA"
INTERNAL_REFERENCE_ONLY_PROFILE = "CLOUD_MAIN"
CURATED_PLATFORM_PROFILE = "CURATED_PLATFORM_REFERENCE"
VERSIONED_SOURCE_PROFILES = CURRENT_SOURCE_PROFILES + (PREVIEW_SOURCE_PROFILE, CURATED_PLATFORM_PROFILE)

SOURCE_ROLES = {
    "SHARED_DOCS": "CURRENT_DOCUMENTATION",
    "CLOUD_DIPLO": "CURRENT_RELEASED_CLOUD",
    "WALL_MAIN": "CURRENT_RELATED_PRODUCT",
    "COCKPIT_DIPLO": "CURRENT_RELATED_PRODUCT",
    "GENIE_MASTER": "CURRENT_RELATED_PRODUCT",
    "KICKSTART_MASTER": "CURRENT_RELATED_PRODUCT",
    "QEMU_EXEC_TOOLS_MAIN": "CURRENT_RELATED_PRODUCT",
    "CURATED_PLATFORM_REFERENCE": "CURRENT_PLATFORM_REFERENCE",
    "CLOUD_EUROPA": "UNRELEASED_PREVIEW_CLOUD",
}

EVIDENCE_PRIORITY_POLICY: tuple[dict[str, object], ...] = (
    {"priority": 1, "tier": "ABLESTACK_DOCUMENTATION", "description": "ABLESTACK 문서와 승인된 내부 운영 지식"},
    {"priority": 2, "tier": "ABLESTACK_SOURCE_CODE", "description": "Diplo와 연관 제품 코드, Europa Preview 코드"},
    {"priority": 3, "tier": "OFFICIAL_PLATFORM_DOCUMENTATION", "description": "공식 libvirt, QEMU, KVM 자료"},
    {"priority": 4, "tier": "APPROVED_EXTERNAL_REFERENCE", "description": "별도 승인된 기타 외부 자료"},
)


def evidence_priority(source_profile_id: str, source_kind: str = "SOURCE_CODE") -> tuple[int, str]:
    """Return the stable product-first evidence precedence used by the provider and audit ledger."""
    if source_profile_id == "SHARED_DOCS" or source_kind == "OPERATOR_APPROVED_KNOWLEDGE":
        return 1, "ABLESTACK_DOCUMENTATION"
    if source_profile_id != CURATED_PLATFORM_PROFILE:
        return 2, "ABLESTACK_SOURCE_CODE"
    if source_kind == "OFFICIAL_EXTERNAL_DOCUMENTATION":
        return 3, "OFFICIAL_PLATFORM_DOCUMENTATION"
    return 4, "APPROVED_EXTERNAL_REFERENCE"

CONSOLE_CONNECTION_MARKERS: tuple[str, ...] = (
    "console",
    "console proxy",
    "consoleproxy",
    "novnc",
    "websocket",
    "websockify",
    "vnc",
    "query-vnc",
    "libvirt",
    "qemu",
    "live migration",
    "라이브 마이그레이션",
    "정지 후 시작",
    "createconsoleendpoint",
    "콘솔 프록시",
)


def versioned_plan(question: str) -> dict[str, object]:
    return {
        "state": "READY",
        "domains": ["ABLESTACK_PRODUCT"],
        "sourceProfileIds": list(VERSIONED_SOURCE_PROFILES),
        "subquestions": [
            "1순위: ABLESTACK 문서와 승인된 내부 운영 지식을 확인한다.",
            "2순위: Diplo와 연관 제품 Source Code를 확인하고 Europa는 개선 예정 정보로만 비교한다.",
            "3순위: 공식 libvirt, QEMU, KVM 자료에서 플랫폼 동작과 안전한 확인 방법을 보완한다.",
            "4순위: 앞선 근거가 부족할 때만 별도 승인된 외부 자료를 보조로 사용한다.",
        ],
        "evidencePriority": list(EVIDENCE_PRIORITY_POLICY),
        "questionsNeeded": [],
        "question": question,
    }


STOP_WORDS = {
    "ablestack", "diplo", "europa", "관련", "변경", "진행", "주요", "필드", "무엇", "알려줘", "알려주세요",
    "현재", "제품", "기준", "코드", "검토", "원인", "조치",
}


def _query_terms(question: str) -> set[str]:
    identifiers = {
        item.casefold() for item in re.findall(r"[A-Za-z][A-Za-z0-9_]{5,}", question)
        if item.casefold() not in {"ablestack", "diplo", "europa"}
    }
    if identifiers:
        return identifiers
    terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_]{3,}|[가-힣]{2,}", question.casefold()))
    return {item for item in terms if item not in STOP_WORDS}


def _is_console_connection_question(question: str) -> bool:
    normalized = question.casefold()
    return "콘솔" in normalized and any(marker in normalized for marker in ("연결", "화면", "보이지", "표시"))


def expand_retrieval_question(question: str) -> str:
    """Add implementation vocabulary without changing the user's visible question."""
    if not _is_console_connection_question(question):
        return question
    anchors = " ".join(CONSOLE_CONNECTION_MARKERS)
    return f"{question}\n진단 검색어: {anchors}"


def _relevance_score(question: str, item: dict[str, Any]) -> int:
    searchable = f"{item.get('symbol') or ''}\n{item.get('path') or ''}\n{item.get('content') or ''}".casefold()
    score = sum(1 for term in _query_terms(question) if term in searchable)
    if _is_console_connection_question(question):
        score += sum(6 for marker in CONSOLE_CONNECTION_MARKERS if marker in searchable)
        path = str(item.get("path") or "").casefold()
        if any(marker in path for marker in ("consoleproxy", "novnc", "console.vue", "systemvm")):
            score += 12
    return score


def relevant_results(question: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = _query_terms(question)
    if not terms:
        return []
    if not _is_console_connection_question(question):
        relevant = []
        for item in rows:
            searchable = f"{item.get('symbol') or ''}\n{item.get('path') or ''}\n{item.get('content') or ''}".casefold()
            if any(term in searchable for term in terms):
                relevant.append(item)
        return relevant
    ranked = [(_relevance_score(question, item), index, item) for index, item in enumerate(rows)]
    return [item for score, _, item in sorted(ranked, key=lambda value: (-value[0], value[1])) if score > 0]


def coverage_payload(question: str, results_by_profile: dict[str, list[dict[str, Any]]]) -> list[dict[str, object]]:
    relevant_by_profile = {key: relevant_results(question, value) for key, value in results_by_profile.items()}
    return [
        {
            "sourceProfileId": profile_id,
            "role": SOURCE_ROLES[profile_id],
            "state": "EVIDENCE_FOUND" if relevant_by_profile.get(profile_id) else "NO_RELEVANT_EVIDENCE",
            "evidenceCount": len(relevant_by_profile.get(profile_id) or ()),
        }
        for profile_id in VERSIONED_SOURCE_PROFILES
    ]


def select_context_results(question: str, results_by_profile: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Keep every source reviewed while bounding a provider request to twenty chunks."""
    selected: list[dict[str, Any]] = []
    for profile_id in VERSIONED_SOURCE_PROFILES:
        if _is_console_connection_question(question):
            limit = {
                "SHARED_DOCS": 3,
                "CLOUD_DIPLO": 3,
                CURATED_PLATFORM_PROFILE: 4,
                "CLOUD_EUROPA": 3,
            }.get(profile_id, 1)
        else:
            limit = 4 if profile_id in {"SHARED_DOCS", "CLOUD_DIPLO", "CLOUD_EUROPA"} else 1
        for item in relevant_results(question, results_by_profile.get(profile_id) or [])[:limit]:
            value = dict(item)
            value.setdefault("sourceProfileId", profile_id)
            priority, tier = evidence_priority(profile_id, str(item.get("sourceKind") or "SOURCE_CODE"))
            value.update(evidencePriority=priority, evidenceTier=tier)
            selected.append(value)
    return sorted(
        selected,
        key=lambda item: (int(item["evidencePriority"]), VERSIONED_SOURCE_PROFILES.index(str(item["sourceProfileId"]))),
    )[:20]


def evidence_ledger(result: dict[str, Any]) -> dict[str, object]:
    report = result.get("report") or {}
    return {
        "policy": "PRODUCT_FIRST_EVIDENCE_V2",
        "evidencePriority": list(EVIDENCE_PRIORITY_POLICY),
        "coverage": result.get("coverage") or [],
        "currentAssessment": report.get("currentAssessment"),
        "previewAssessment": report.get("previewAssessment"),
        "previewGuidance": report.get("previewGuidance"),
        "citations": result.get("citations") or [],
    }


def _projection_replacements(citations: Iterable[dict[str, Any]]) -> set[str]:
    values: set[str] = set()
    for item in citations:
        for key in ("repository", "branch", "commit", "path", "citationId", "chunkId", "sourceProfileId"):
            value = str(item.get(key) or "").strip()
            if value:
                values.add(value)
    values.update(VERSIONED_SOURCE_PROFILES)
    values.update({"CLOUD_MAIN", "ablecloud-team"})
    return values


def sanitize_public_text(value: object, citations: Iterable[dict[str, Any]] = ()) -> str:
    text = str(value or "").strip()
    citation_tokens: set[str] = set()
    for item in citations:
        for key in ("citationId", "chunkId", "sourceVersionId"):
            token = str(item.get(key) or "").strip()
            if token:
                citation_tokens.add(token)
    for token in sorted(citation_tokens, key=len, reverse=True):
        text = re.sub(rf"\s*\[{re.escape(token)}\]", "", text)
        text = text.replace(token, "")
    for secret in sorted(_projection_replacements(citations), key=len, reverse=True):
        if re.fullmatch(r"[A-Za-z0-9_.-]+", secret):
            text = re.sub(
                rf"(?<![A-Za-z0-9_.-]){re.escape(secret)}(?![A-Za-z0-9_.-])",
                "제품 내부 구현",
                text,
            )
        else:
            text = text.replace(secret, "제품 내부 구현")
    text = re.sub(r"(?:https?://)?(?:www\.)?github\.com/\S+", "제품 내부 근거", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", "내부 검토 자료", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[0-9a-f]{40}\b", "제품 버전", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:[\w.-]+/){2,}[\w.@-]+(?::\d+(?:-\d+)?)?", "제품 내부 경로", text)
    text = re.sub(r"\b(?:citation|chunk|evidence)[-_]?[A-Za-z0-9-]+\b", "내부 근거", text, flags=re.IGNORECASE)
    return re.sub(r"[ \t]+", " ", text).strip()


def simplify_public_text(value: object, citations: Iterable[dict[str, Any]] = ()) -> str:
    """Prefer short user-facing Korean while preserving commands and essential product names."""
    text = sanitize_public_text(value, citations)
    replacements = (
        ("QEMU 프로세스 내부의 VNC 통신 소켓", "가상머신 실행 프로그램(QEMU)의 콘솔 연결(VNC)"),
        ("QEMU 프로세스", "가상머신 실행 프로그램(QEMU)"),
        ("VNC 통신 소켓", "콘솔 연결 통로(VNC)"),
        ("VNC 세션", "콘솔 연결(VNC)"),
        ("게스트 운영체제", "가상머신 안의 운영체제"),
        ("Console Proxy VM", "콘솔 연결을 중계하는 시스템 가상머신"),
        ("noVNC WebSocket", "브라우저 콘솔 연결"),
        ("WebSocket", "브라우저 실시간 연결"),
        ("엔드포인트", "연결 정보"),
        ("런타임", "실행 환경"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


_SYMPTOM_ANALYSIS_MARKERS = (
    "가능성", "확정할", "확인해야", "점검해야", "근거", "로그는 제공", "자료는 제공",
    "현재 릴리스", "중계합니다", "처리하며", "세션을 끊", "브라우저→", "console proxy",
    "websocket", "novnc", "vnc 포트", "네트워크 경로", "구현",
)
_SYMPTOM_OBSERVATION_MARKERS = (
    "표시", "멈", "열리", "보이지", "진행되지", "연결중", "접근", "실패", "오류", "응답하지", "동작하지",
)


def _is_user_observed_symptom(text: str) -> bool:
    normalized = text.casefold()
    return (
        any(marker in normalized for marker in _SYMPTOM_OBSERVATION_MARKERS)
        and not any(marker in normalized for marker in _SYMPTOM_ANALYSIS_MARKERS)
    )


def _section_values(rows: Iterable[object], citations: Iterable[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for row in rows:
        raw = row if isinstance(row, str) else row.get("text") or row.get("title") or row.get("action") or ""
        clean = simplify_public_text(raw, citations)
        if clean and clean not in values:
            values.append(clean)
    return values


def format_public_answer(result: dict[str, Any]) -> str | None:
    if result.get("state") != "ANSWERED" or not result.get("report"):
        return None
    report = result["report"]
    citations = result.get("citations") or []
    lines = ["## ABLESTACK 트러블슈팅 가이드"]

    symptom_candidates = _section_values(report.get("observedFacts") or [], citations)
    symptom_values = [value for value in symptom_candidates if _is_user_observed_symptom(value)]
    if not symptom_values:
        summary = simplify_public_text(report.get("summary"), citations)
        if summary and _is_user_observed_symptom(summary):
            symptom_values.append(summary)
    cause_values = _section_values(report.get("diagnoses") or [], citations)
    action_values = _section_values(report.get("recommendedActions") or [], citations)
    if report.get("currentAssessment") == "CURRENT_RUNTIME_ISSUE" and any(
        term in " ".join(cause_values).casefold() for term in ("qemu", "vnc", "콘솔 연결")
    ):
        cause_values = ["가상머신 실행 프로그램(QEMU)에서 이전 콘솔 연결(VNC)이 정상적으로 끝나지 않아 새 연결을 받지 못하는 상태일 수 있습니다."]
    for heading, values, empty_message in (
        ("증상", symptom_values, "확인된 증상 정보가 없습니다."),
        ("원인", cause_values, "현재 근거에서 확인된 원인은 없습니다."),
        ("해결 방법", action_values, "추가 정보를 확인한 뒤 해결 방법을 결정해야 합니다."),
    ):
        lines.extend(["", f"### {heading}"])
        lines.extend(f"- {value}" for value in values or [empty_message])
    current = report.get("currentAssessment")
    if current:
        labels = {
            "CURRENT_NORMAL": "현재 출시 버전에서 정상 동작으로 판단됩니다.",
            "CURRENT_CONFIG_ERROR": "현재 출시 버전의 설정 또는 환경 문제 가능성이 높습니다.",
            "CURRENT_DEFECT": "현재 출시 버전의 제품 결함 가능성이 확인됩니다.",
            "CURRENT_RUNTIME_ISSUE": "현재 출시판 코드 결함이 아니라 가상화 프로그램의 일시적인 상태 문제로 판단됩니다.",
            "INSUFFICIENT_EVIDENCE": "현재 정보만으로는 출시 버전의 상태를 확정하기 어렵습니다.",
        }
        current_label = labels.get(current, simplify_public_text(current, citations))
    preview = report.get("previewAssessment")
    guidance = simplify_public_text(report.get("previewGuidance"), citations)
    preview_label = "이번 사례에서 차기 버전 비교는 적용 대상이 아닙니다."
    if preview and preview != "NOT_APPLICABLE":
        labels = {
            "PREVIEW_IMPROVED": "차기 버전 코드에서 관련 개선이 진행 중인 정황이 확인됩니다.",
            "PREVIEW_PARTIAL": "차기 버전 코드에 일부 관련 개선이 있으나 완전한 해결 여부는 추가 검증이 필요합니다.",
            "PREVIEW_NOT_FOUND": "차기 버전 코드에서 직접 대응하는 개선을 확인하지 못해 제품 보완 검토가 필요합니다.",
            "PREVIEW_INSUFFICIENT": "차기 버전 개선 여부를 판단할 근거가 충분하지 않습니다.",
        }
        preview_label = labels.get(preview, simplify_public_text(preview, citations))

    considerations: list[str] = []
    for row in report.get("unknowns") or []:
        clean = simplify_public_text(row, citations)
        if clean and clean not in considerations:
            considerations.append(clean)
    if guidance and guidance not in considerations:
        considerations.append(guidance)
    lines.extend(["", "### 추가 고려사항"])
    lines.extend(f"- {value}" for value in considerations or ["별도의 추가 고려사항은 확인되지 않았습니다."])

    lines.extend(["", "### 적용 버전"])
    if current:
        lines.append(f"- 현재 적용 기준: ABLESTACK Cloud Diplo(현재 출시판) - {current_label}")
    else:
        lines.append("- 현재 적용 기준: ABLESTACK Cloud Diplo(현재 출시판) - 판정 정보가 없습니다.")
    lines.append(f"- 차기 참고 기준: ABLESTACK Cloud Europa(미출시 Preview) - {preview_label}")
    lines.extend(["", "> 이 답변은 ABLESTACK TechFlow가 제품 자료와 구현을 종합 검토한 뒤 담당자 승인을 거쳐 제공합니다."])
    return "\n".join(line for line in lines if line is not None).strip()


def projection_is_safe(text: str) -> bool:
    forbidden = (
        r"https?://", r"github\.com/", r"\b[0-9a-f]{40}\b", r"CLOUD_(?:DIPLO|EUROPA|MAIN)",
        r"ablecloud-team/", r"#L\d+", r"(?:\.java|\.py|\.ts|\.md):\d+",
    )
    return not any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in forbidden)
