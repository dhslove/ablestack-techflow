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
    {"priority": 3, "tier": "OFFICIAL_PLATFORM_DOCUMENTATION", "description": "공식 게스트 OS, libvirt, QEMU, KVM 자료"},
    {"priority": 4, "tier": "APPROVED_EXTERNAL_REFERENCE", "description": "별도 승인된 기타 외부 자료"},
)


def evidence_priority(source_profile_id: str, source_kind: str = "SOURCE_CODE") -> tuple[int, str]:
    """Return the stable product-first evidence precedence used by the provider and audit ledger."""
    if source_profile_id == "SHARED_DOCS" or source_kind == "OPERATOR_APPROVED_KNOWLEDGE":
        return 1, "ABLESTACK_DOCUMENTATION"
    if source_profile_id != CURATED_PLATFORM_PROFILE:
        return 2, "ABLESTACK_SOURCE_CODE"
    if source_kind in {"OFFICIAL_EXTERNAL_DOCUMENTATION", "OFFICIAL_LIVE_WEB_DOCUMENTATION"}:
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

FSFREEZE_MARKERS: tuple[str, ...] = (
    "guest-fsfreeze-freeze",
    "guest-fsfreeze-status",
    "guest-fsfreeze-thaw",
    "qemu-ga",
    "qemu guest agent",
    "qemu-guest-agent",
    "fsfreeze",
    "permission denied",
    "selinux",
    "ausearch",
    "findmnt",
    "matchpathcon",
    "restorecon",
    "스냅샷",
    "복제",
    "동결",
)

GUEST_AGENT_MARKERS: tuple[str, ...] = (
    "qemu guest agent", "qemu-guest-agent", "qemu-ga", "guest agent", "게스트 에이전트", "에이전트",
    "ubuntu", "apt", "rhel", "red hat", "rocky", "dnf", "windows", "virtio-win", "msiexec",
    "get-service", "start-service", "org.qemu.guest_agent.0", "could not be found", "service",
)

GLUE_MARKERS: tuple[str, ...] = (
    "glue", "ceph", "rados", "rbd", "cephfs", "osd", "mon", "mgr", "mds", "pool",
    "ceph status", "ceph health detail",
)

KORAL_MARKERS: tuple[str, ...] = (
    "koral", "kubernetes", "k8s", "kubectl", "pod", "deployment", "statefulset", "daemonset",
    "kubeconfig", "control plane", "cluster", "namespace", "event",
)

WALL_MARKERS: tuple[str, ...] = (
    "wall", "grafana", "dashboard", "panel", "data source", "datasource", "alert", "prometheus", "loki",
    "grafana-server", "grafana.log",
)

MOLD_MARKERS: tuple[str, ...] = (
    "mold", "cloudstack", "management server", "system vm", "console proxy", "secondary storage vm",
    "virtual router", "cloudstack api", "api command", "async job", "libvirt", "qemu", "kvm", "virsh",
)


def versioned_plan(question: str) -> dict[str, object]:
    return {
        "state": "READY",
        "domains": ["ABLESTACK_PRODUCT"],
        "sourceProfileIds": list(VERSIONED_SOURCE_PROFILES),
        "subquestions": [
            "1순위: ABLESTACK 문서와 승인된 내부 운영 지식을 확인한다.",
            "2순위: Diplo와 연관 제품 Source Code를 확인하고 Europa는 개선 예정 정보로만 비교한다.",
            "3순위: 공식 게스트 OS, libvirt, QEMU, KVM 자료에서 설치·동작·안전한 확인 방법을 보완한다.",
            "로컬 공식 자료가 없거나 갱신 기한을 넘긴 경우에만 승인된 공식 도메인을 온라인 조회한다.",
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


def _is_fsfreeze_question(question: str) -> bool:
    normalized = question.casefold()
    return any(marker in normalized for marker in (
        "guest-fsfreeze", "fsfreeze", "qemu agent", "qemu-ga", "permission denied",
    )) or (
        any(marker in normalized for marker in ("스냅샷", "복제", "freeze", "동결"))
        and any(marker in normalized for marker in ("/mnt", "새 디스크", "볼륨", "qemu"))
    )


def _is_guest_agent_question(question: str) -> bool:
    normalized = question.casefold()
    agent = any(marker in normalized for marker in (
        "qemu guest agent", "qemu-guest-agent", "qemu-ga", "guest agent", "게스트 에이전트", "에이전트",
    ))
    procedure = any(marker in normalized for marker in (
        "설치", "install", "could not be found", "not found", "서비스", "service", "실행", "시작",
    ))
    return agent and procedure


def _is_glue_question(question: str) -> bool:
    normalized = question.casefold()
    return any(marker in normalized for marker in ("glue", "ceph", "rados", "rbd", "cephfs"))


def _is_koral_question(question: str) -> bool:
    normalized = question.casefold()
    return any(marker in normalized for marker in ("koral", "kubernetes", "k8s", "kubectl"))


def _is_wall_question(question: str) -> bool:
    normalized = question.casefold()
    return any(marker in normalized for marker in ("wall", "grafana"))


def _is_mold_question(question: str) -> bool:
    normalized = question.casefold()
    return any(marker in normalized for marker in ("mold", "cloudstack"))


def expand_retrieval_question(question: str, *, limit: int = 4000) -> str:
    """Add implementation vocabulary without changing the user's visible question."""
    anchors: list[str] = []
    if _is_console_connection_question(question):
        anchors.extend(CONSOLE_CONNECTION_MARKERS)
    if _is_fsfreeze_question(question):
        anchors.extend(FSFREEZE_MARKERS)
    if _is_guest_agent_question(question):
        anchors.extend(GUEST_AGENT_MARKERS)
    if _is_glue_question(question):
        anchors.extend(GLUE_MARKERS)
    if _is_koral_question(question):
        anchors.extend(KORAL_MARKERS)
    if _is_wall_question(question):
        anchors.extend(WALL_MARKERS)
    if _is_mold_question(question):
        anchors.extend(MOLD_MARKERS)
    if not anchors:
        return question[:limit]
    suffix = f"\n진단 검색어: {' '.join(dict.fromkeys(anchors))}"
    if len(suffix) >= limit:
        raise ValueError("retrieval anchors must be shorter than the question limit")
    return f"{question[:limit - len(suffix)].rstrip()}{suffix}"


def _relevance_score(question: str, item: dict[str, Any]) -> int:
    searchable = f"{item.get('symbol') or ''}\n{item.get('path') or ''}\n{item.get('content') or ''}".casefold()
    score = sum(1 for term in _query_terms(question) if term in searchable)
    if _is_console_connection_question(question):
        score += sum(6 for marker in CONSOLE_CONNECTION_MARKERS if marker in searchable)
        path = str(item.get("path") or "").casefold()
        if any(marker in path for marker in ("consoleproxy", "novnc", "console.vue", "systemvm")):
            score += 12
    if _is_fsfreeze_question(question):
        score += sum(6 for marker in FSFREEZE_MARKERS if marker in searchable)
        path = str(item.get("path") or "").casefold()
        if any(marker in path for marker in ("snapshot", "qemu", "agent", "freeze", "storage")):
            score += 8
    if _is_guest_agent_question(question):
        score += sum(6 for marker in GUEST_AGENT_MARKERS if marker in searchable)
        if str(item.get("sourceKind") or "") in {
            "OFFICIAL_EXTERNAL_DOCUMENTATION", "OFFICIAL_LIVE_WEB_DOCUMENTATION",
        }:
            score += 12
    if _is_glue_question(question):
        score += sum(6 for marker in GLUE_MARKERS if marker in searchable)
    if _is_koral_question(question):
        score += sum(6 for marker in KORAL_MARKERS if marker in searchable)
    if _is_wall_question(question):
        score += sum(6 for marker in WALL_MARKERS if marker in searchable)
    if _is_mold_question(question):
        score += sum(6 for marker in MOLD_MARKERS if marker in searchable)
    return score


def relevant_results(question: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = _query_terms(question)
    if not terms:
        return []
    if not (
        _is_console_connection_question(question) or _is_fsfreeze_question(question)
        or _is_guest_agent_question(question) or _is_glue_question(question) or _is_koral_question(question)
        or _is_wall_question(question)
        or _is_mold_question(question)
    ):
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
        if (
            _is_console_connection_question(question) or _is_fsfreeze_question(question)
            or _is_guest_agent_question(question) or _is_glue_question(question) or _is_koral_question(question)
            or _is_wall_question(question)
            or _is_mold_question(question)
        ):
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
    safe_system_paths = {
        "/dev/virtio-ports/org.qemu.guest_agent.0": "TECHFLOW_SAFE_QGA_CHANNEL_PATH",
    }
    for path, placeholder in safe_system_paths.items():
        text = text.replace(path, placeholder)
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
    for path, placeholder in safe_system_paths.items():
        text = text.replace(placeholder, path)
    return re.sub(r"[ \t]+", " ", text).strip()


_OPERATIONAL_PREFIX = re.compile(r"^\s*((?:\[[^\]\r\n]+\]\s*)+)(.*)$", re.DOTALL)
_PUBLIC_ROLE_LABELS = (
    ("호스트 관리자", "서버 관리자는"),
    ("서버 관리자", "서버 관리자는"),
    ("네트워크 관리자", "네트워크 관리자는"),
    ("관리자", "관리자는"),
)
_INTERNAL_OPERATIONAL_LABELS = {
    "읽기 전용", "읽기전용", "변경 없음", "변경없음", "변경", "호스트 관리자", "서버 관리자",
    "네트워크 관리자", "관리자", "read-only", "readonly", "no change", "non-mutating",
}


def naturalize_operational_prefix(value: str) -> str:
    """Convert internal action metadata into a sentence a product user can understand."""
    match = _OPERATIONAL_PREFIX.match(value)
    if not match:
        return value
    labels = [part.strip() for part in re.findall(r"\[([^\]]+)\]", match.group(1))]
    tokens = {
        token.strip().casefold()
        for label in labels
        for token in re.split(r"[·,/|+]", label)
        if token.strip()
    }
    allowed = {item.casefold() for item in _INTERNAL_OPERATIONAL_LABELS}
    if not tokens or not tokens.issubset(allowed):
        return value
    body = match.group(2).strip()
    for label, subject in _PUBLIC_ROLE_LABELS:
        if label.casefold() in tokens:
            if body.startswith(subject):
                return body
            return f"{subject} {body}"
    return body


def simplify_public_text(value: object, citations: Iterable[dict[str, Any]] = ()) -> str:
    """Prefer short user-facing Korean while preserving commands and essential product names."""
    text = naturalize_operational_prefix(sanitize_public_text(value, citations))
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
    text = re.sub(r"(?<=\d)\s*~\s*(?=\d)", "–", text)
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
        raw = row if isinstance(row, str) else (
            row.get("text") or row.get("title") or row.get("action") or row.get("finding") or ""
        )
        clean = simplify_public_text(raw, citations)
        if clean and clean not in values:
            values.append(clean)
    return values


def _is_causal_artifact_finding(value: str) -> bool:
    """Keep causal attachment observations in Cause without leaking evidence identifiers."""
    folded = value.casefold()
    subject = any(term in folded for term in ("vnc", "qemu", "libvirt", "세션", "소켓", "연결"))
    state = any(term in folded for term in (
        "still_open", "waiting", "interrupted", "남아", "해제되지", "대기", "중단", "실패", "error", "오류",
    ))
    return subject and state


_INLINE_CODE = re.compile(r"`([^`\r\n]+)`")
_CLI_PREFIXES = (
    "sudo ", "systemctl ", "journalctl ", "ausearch ", "findmnt ", "namei ",
    "getfacl ", "matchpathcon ", "restorecon ", "virsh ", "qemu-ga ", "ls ",
    "grep ", "curl ", "ip ", "ss ", "getenforce", "sestatus", "mount ", "cat ",
    "apt ", "apt-get ", "dnf ", "rpm ", "dpkg ", "msiexec.exe ", "get-service ", "start-service ",
)

_POWERSHELL_PREFIXES = ("msiexec.exe ", "get-service ", "start-service ", "restart-service ", "stop-service ")


def _looks_like_cli(value: str) -> bool:
    candidate = value.strip().removeprefix("$ ").casefold()
    return any(candidate == prefix.strip() or candidate.startswith(prefix) for prefix in _CLI_PREFIXES)


def _format_copyable_cli(value: str) -> str:
    """Move inline shell commands below their explanation as copy-ready blocks."""
    if "```" in value:
        return value
    commands: list[str] = []

    def replace(match: re.Match[str]) -> str:
        candidate = match.group(1).strip()
        if not _looks_like_cli(candidate):
            return match.group(0)
        commands.append(candidate.removeprefix("$ "))
        return "다음 명령"

    explanation = _INLINE_CODE.sub(replace, value).strip().replace("다음 명령를", "다음 명령을")
    if not commands:
        return value
    unique_commands = list(dict.fromkeys(commands))
    language = "powershell" if all(
        command.casefold().startswith(_POWERSHELL_PREFIXES) for command in unique_commands
    ) else "bash"
    return f"{explanation}\n\n```{language}\n" + "\n".join(unique_commands) + "\n```"


def format_public_answer(result: dict[str, Any]) -> str | None:
    """Render an ongoing Community reply in a friendly engineer-to-user voice.

    Ongoing support replies intentionally avoid the fixed Knowledge Base section
    template. They explain the current assessment, offer the safest next steps,
    and ask only for information that is still needed.
    """
    citations = result.get("citations") or []
    if result.get("state") == "NEEDS_INFORMATION":
        needed = result.get("questionsNeeded") or (result.get("plan") or {}).get("questionsNeeded") or []
        lines = [
            "확인을 도와드리겠습니다. 다만 지금 알려주신 내용만으로는 원인을 단정하기 어렵습니다.",
            "아래 정보를 알려주시면 앞서 주신 내용과 함께 확인해서 다음 조치를 안내하겠습니다.",
            "",
        ]
        lines.extend(f"- {simplify_public_text(item, citations)}" for item in needed)
        return "\n".join(line for line in lines if line is not None).strip()
    if result.get("state") == "ABSTAINED":
        needed = result.get("questionsNeeded") or (result.get("plan") or {}).get("questionsNeeded") or []
        lines = [
            "확인을 도와드리겠습니다. 현재 자료만으로는 원인을 안전하게 하나로 좁히기 어려워 몇 가지 확인이 더 필요합니다.",
            "우선 사용 중인 ABLESTACK Diplo 버전과 문제가 발생한 시각을 알려주세요. 가능하면 같은 시각의 관리 서버·호스트 로그나 화면 캡처도 함께 올려주세요.",
        ]
        if needed:
            lines.extend(["", "특히 아래 내용을 확인해 주시면 좋습니다."])
            lines.extend(f"- {simplify_public_text(item, citations)}" for item in needed[:6])
        lines.extend(["", "자료를 댓글로 남겨주시면 지금 질문의 맥락을 유지해서 다음 확인 순서를 이어서 안내하겠습니다."])
        return "\n".join(lines).strip()
    if result.get("state") != "ANSWERED" or not result.get("report"):
        return None

    report = result["report"]
    summary = simplify_public_text(report.get("summary"), citations)
    diagnoses = _section_values(report.get("diagnoses") or [], citations)
    actions = _section_values(report.get("recommendedActions") or [], citations)
    unknowns = _section_values(report.get("unknowns") or [], citations)
    artifact_findings = _section_values(report.get("artifactEvidence") or [], citations)
    lines: list[str] = []

    if summary:
        lines.append(summary)
    elif diagnoses:
        lines.append(f"확인해 보니 {diagnoses[0]}")
        diagnoses = diagnoses[1:]
    else:
        lines.append("말씀해 주신 현상을 기준으로 확인해 보겠습니다.")

    if actions:
        lines.extend(["", "먼저 다음 해결 방법을 적용해 보세요."])
        lines.extend(f"{index}. {_format_copyable_cli(value)}" for index, value in enumerate(actions[:6], 1))
    if artifact_findings:
        lines.extend(["", "첨부해 주신 자료에서는 다음 내용을 확인했습니다."])
        lines.extend(f"- {value}" for value in artifact_findings[:3])
    if report.get("currentAssessment") == "CURRENT_RUNTIME_ISSUE":
        lines.extend([
            "",
            "현재 자료로는 ABLESTACK 제품 코드의 오류라기보다 가상화 프로그램이 일시적으로 정상 상태를 잃은 문제에 가깝습니다.",
        ])
    if diagnoses:
        lines.extend(["", "이 방법을 먼저 권장하는 이유는 다음과 같습니다."])
        lines.extend(f"- {value}" for value in diagnoses[:3])
    if unknowns:
        lines.extend([
            "",
            "위 조치로 해결되지 않으면 아래 결과를 알려주세요. 이미 제공한 내용은 다시 보내지 않으셔도 됩니다.",
        ])
        lines.extend(f"- {_format_copyable_cli(value)}" for value in unknowns[:6])
    if not actions and not unknowns:
        lines.extend(["", "진행 결과를 알려주시면 같은 맥락에서 다음 확인을 이어가겠습니다."])
    return "\n".join(lines).strip()


def format_knowledge_base(result: dict[str, Any]) -> str | None:
    """Render the resolved conversation as a stable Knowledge Base article body."""
    if result.get("state") in {"NEEDS_INFORMATION", "ABSTAINED"}:
        needed = result.get("questionsNeeded") or (result.get("plan") or {}).get("questionsNeeded") or []
        question = simplify_public_text(result.get("userQuestion"), [])
        lines = [
            "### 증상",
            f"- {question}" if question else "- 질문에 대한 추가 확인이 필요합니다.",
            "",
            "### 원인",
            "- 현재 정보만으로는 원인을 확정할 수 없습니다.",
        ]
        if needed:
            lines.extend(["", "### 추가로 필요한 정보", *(f"- {item}" for item in needed)])
        lines.extend([
            "",
            "### 해결 방법",
            "- 요청한 정보를 확인한 뒤 안전한 확인 순서와 해결 방법을 안내하겠습니다.",
            "",
            "### 추가 고려사항",
            "- 현재까지 확인한 내용과 이후 제공되는 자료를 같은 기술지원 맥락으로 계속 검토합니다.",
            "",
            "### 적용 버전",
            "- ABLESTACK Diplo",
        ])
        return "\n".join(lines).strip()
    if result.get("state") != "ANSWERED" or not result.get("report"):
        return None
    report = result["report"]
    citations = result.get("citations") or []
    lines: list[str] = []

    symptom_candidates = _section_values(report.get("observedFacts") or [], citations)
    symptom_values = [value for value in symptom_candidates if _is_user_observed_symptom(value)]
    if not symptom_values:
        summary = simplify_public_text(report.get("summary"), citations)
        if summary and _is_user_observed_symptom(summary):
            symptom_values.append(summary)
    cause_values = _section_values(report.get("diagnoses") or [], citations)
    artifact_findings = _section_values(report.get("artifactEvidence") or [], citations)
    causal_artifact_findings = [value for value in artifact_findings if _is_causal_artifact_finding(value)]
    contextual_artifact_findings = [value for value in artifact_findings if value not in causal_artifact_findings]
    action_values = _section_values(report.get("recommendedActions") or [], citations)
    if report.get("currentAssessment") == "CURRENT_RUNTIME_ISSUE" and any(
        term in " ".join(cause_values).casefold() for term in ("qemu", "vnc", "콘솔 연결")
    ):
        cause_values = [
            *causal_artifact_findings,
            "가상머신 실행 프로그램(QEMU)에서 이전 콘솔 연결(VNC)이 정상적으로 끝나지 않아 새 연결을 받지 못하는 상태일 수 있습니다.",
        ]
    else:
        cause_values = [*causal_artifact_findings, *cause_values]
    for heading, values, empty_message in (
        ("증상", symptom_values, "확인된 증상 정보가 없습니다."),
        ("원인", cause_values, "현재 근거에서 확인된 원인은 없습니다."),
        ("해결 방법", action_values, "추가 정보를 확인한 뒤 해결 방법을 결정해야 합니다."),
    ):
        lines.extend(["", f"### {heading}"])
        lines.extend(f"- {value}" for value in values or [empty_message])
    information_requests: list[str] = []
    considerations: list[str] = list(contextual_artifact_findings)
    attachment_failure_recorded = bool(result.get("attachmentFailureRecorded"))
    for row in report.get("unknowns") or []:
        clean = simplify_public_text(row, citations)
        if not clean:
            continue
        if not attachment_failure_recorded and _is_unverified_attachment_failure(clean):
            continue
        if any(marker in clean for marker in ("필요", "확인", "제공", "알려", "첨부", "로그", "화면")):
            if clean not in information_requests:
                information_requests.append(clean)
        elif clean not in considerations:
            considerations.append(clean)
    if information_requests:
        insertion = lines.index("### 해결 방법")
        lines[insertion:insertion] = [
            "### 추가로 필요한 정보",
            *(f"- {value}" for value in information_requests),
            "",
        ]
    lines.extend(["", "### 추가 고려사항"])
    lines.extend(f"- {value}" for value in considerations or ["별도의 추가 고려사항은 확인되지 않았습니다."])

    lines.extend(["", "### 적용 버전"])
    lines.append("- ABLESTACK Diplo")
    lines.extend(["", "> 이 문서는 질문자가 해결 답변으로 선택한 내용을 중심으로 TechFlow가 대화를 정리한 Knowledge Base입니다."])
    return "\n".join(line for line in lines if line is not None).strip()


def _is_unverified_attachment_failure(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value).casefold()
    attachment = any(marker in normalized for marker in ("첨부파일", "첨부 파일", "첨부자료", "첨부 자료"))
    unavailable = any(
        marker in normalized
        for marker in ("내려받지 못", "다운로드하지 못", "확인할 수 없", "읽지 못", "분석하지 못")
    )
    return attachment and unavailable


def projection_is_safe(text: str) -> bool:
    forbidden = (
        r"https?://", r"github\.com/", r"\b[0-9a-f]{40}\b", r"CLOUD_(?:DIPLO|EUROPA|MAIN)",
        r"ablecloud-team/", r"#L\d+", r"(?:\.java|\.py|\.ts|\.md):\d+",
    )
    return not any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in forbidden)
