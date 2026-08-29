"""Synology Chat Bot boundary for Community publication observability."""

from __future__ import annotations

from dataclasses import dataclass
from email.message import Message
import hashlib
import hmac
import json
from pathlib import Path
import re
import urllib.parse
import urllib.error
import urllib.request
from typing import Any

from .store import InvalidBoundaryError


MAX_EVENT_BYTES = 64 * 1024
CASE_REFERENCE = re.compile(r"^[A-Fa-f0-9-]{6,36}$|^[0-9]{1,12}$")


@dataclass(frozen=True)
class ChatEvent:
    token: str
    user_id: str
    username: str
    post_id: str
    text: str
    action_name: str | None = None
    action_value: str | None = None
    callback_id: str | None = None

    @property
    def event_key(self) -> str:
        raw = f"{self.post_id}:{self.action_name or 'message'}:{self.action_value or self.text}"
        return "chat-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class ChatPostFile:
    filename: str
    media_type: str
    size_bytes: int


def parse_chat_event(content_type: str, body: bytes) -> ChatEvent:
    if len(body) > MAX_EVENT_BYTES:
        raise InvalidBoundaryError("Chat event is too large")
    if "application/json" in content_type:
        raw = json.loads(body.decode("utf-8"))
    else:
        values = urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True)
        raw = {key: rows[-1] for key, rows in values.items()}
    if "payload" in raw:
        payload = raw["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise InvalidBoundaryError("invalid Chat interactive payload")
        action = (payload.get("actions") or [{}])[0]
        user = payload.get("user") or {}
        raw = {
            "token": payload.get("token"), "user_id": user.get("user_id"),
            "username": user.get("username"), "post_id": payload.get("post_id"),
            "text": "", "action_name": action.get("name"), "action_value": action.get("value"),
            "callback_id": payload.get("callback_id"),
        }
    required = {name: str(raw.get(name) or "").strip() for name in ("token", "user_id", "username", "post_id")}
    if any(not value for value in required.values()):
        raise InvalidBoundaryError("required Chat identity fields are missing")
    return ChatEvent(
        **required, text=str(raw.get("text") or "").strip()[:12000],
        action_name=str(raw.get("action_name") or "").strip() or None,
        action_value=str(raw.get("action_value") or "").strip() or None,
        callback_id=str(raw.get("callback_id") or "").strip() or None,
    )


def parse_command(event: ChatEvent) -> tuple[str, list[str]]:
    if event.action_value:
        parts = event.action_value.split(":", 3)
        return parts[0].lower(), parts[1:]
    text = event.text.strip()
    for prefix in ("/techflow", "techflow", "테크플로우"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
            break
    if text.startswith("/"):
        text = text[1:]
    if not text:
        return "help", []
    parts = text.split(maxsplit=3)
    aliases = {
        "도움말": "help", "help": "help", "연결": "connect", "connect": "connect",
        "대기": "pending", "pending": "pending", "상세": "detail", "detail": "detail",
        "근거": "evidence", "evidence": "evidence",
        "승인": "approve", "approve": "approve", "반려": "reject", "reject": "reject",
        "수정": "edit", "edit": "edit", "이력": "history", "history": "history",
        "해결": "resolve", "resolve": "resolve", "종료": "resolve",
    }
    return aliases.get(parts[0].lower(), "unknown"), parts[1:]


def help_text() -> str:
    return (
        "TechFlow Community 확인 명령\n"
        "• 연결 - 현재 Chat 계정을 게시 알림 수신자로 연결\n"
        "• 대기 - 처리 중이거나 실패한 답변 확인\n"
        "• 상세 <Discussion ID 또는 Case 앞 8자>\n"
        "• 근거 <Discussion ID 또는 Case 앞 8자> - 내부 검토 근거 표시\n"
        "• 이력 [Case]\n\n"
        "일반 기술 질문을 바로 입력하면 즉시 접수하고, 분석 완료 답변을 이 대화에 다시 보냅니다. "
        "같은 맥락으로 계속 상담하며 해결되면 `해결`을 입력하세요.\n\n"
        "답변은 승인 없이 Community에 바로 게시됩니다. Chat은 게시 상태를 확인하는 용도로 사용합니다."
    )


def case_reference(value: dict[str, Any]) -> str:
    return str(value["caseId"])[:8]


def case_text(value: dict[str, Any], *, include_answer: bool = True) -> str:
    lines = [
        f"[Community 처리 상태] {value['title']}",
        f"Case {case_reference(value)} · Discussion #{value['discussionId']} · Version {value['draftVersion']}",
        f"게시 상태 {value['state']} · 대화 상태 {value.get('conversationState') or '-'} · AI 판정 {value.get('answerState') or '-'}",
        f"질문: {value['discussionUrl']}",
    ]
    if value.get("knowledgeBasePostUrl"):
        lines.extend(["", "최종 Knowledge Base:", value["knowledgeBasePostUrl"]])
    elif value.get("publishedPostUrl"):
        lines.extend(["", "게시된 답변:", value["publishedPostUrl"]])
    elif value.get("reviewPostUrl"):
        lines.extend(["", "이전 방식의 검토 글:", value["reviewPostUrl"]])
    elif include_answer:
        answer = (value.get("draftAnswer") or "근거 기준을 충족한 답변 초안이 없습니다.").strip()
        lines.extend(["", "초안:", answer[:3500]])
    return "\n".join(lines)[:7000]


def case_evidence_text(value: dict[str, Any]) -> str:
    """Render reviewer-only evidence only after an explicit Chat command."""
    citations = value.get("citations") or []
    lines = [
        f"[Community 내부 근거] {value['title']}",
        f"Case {case_reference(value)} · Discussion #{value['discussionId']} · Version {value['draftVersion']}",
    ]
    if citations:
        lines.extend(["", f"Citation {len(citations)}개:"])
        for item in citations[:5]:
            lines.append(
                f"- {item['repository']} · {item['path']}:{item['startLine']}-{item['endLine']} @ {item['commit'][:12]}"
            )
    else:
        lines.extend(["", "Citation이 없습니다."])
    ledger = value.get("evidenceLedger") or {}
    coverage = ledger.get("coverage") or []
    if coverage:
        lines.extend(["", "내부 전 Source 검토:"])
        for item in coverage:
            lines.append(
                f"- {item['sourceProfileId']} · {item['role']} · {item['state']} ({item['evidenceCount']})"
            )
    if ledger.get("currentAssessment") or ledger.get("previewAssessment"):
        lines.extend([
            "",
            f"현재판 판정: {ledger.get('currentAssessment') or '-'}",
            f"Europa 프리뷰 비교: {ledger.get('previewAssessment') or '-'}",
        ])
    return "\n".join(lines)[:7000]


def case_card(value: dict[str, Any], *, notification_type: str | None = None) -> dict[str, Any]:
    reference, version = case_reference(value), value["draftVersion"]
    actions = [
        {"type": "button", "name": "detail", "value": f"detail:{reference}", "text": "상태 확인", "style": "blue"},
        {"type": "button", "name": "evidence", "value": f"evidence:{reference}", "text": "내부 근거", "style": "default"},
    ]
    text = case_text(value, include_answer=False)
    notices = {
        "published": "Community에 AI 답변을 자동 게시했습니다. 링크에서 내용과 대화 흐름을 확인해 주세요.",
        "knowledge": "최종 Knowledge Base를 게시하고 Discussion의 솔루션으로 지정했습니다.",
        "review": "이전 승인 방식의 Community 검토 글이 생성됐습니다.",
    }
    if notification_type in notices:
        text = f"{notices[notification_type]}\n\n{text}"
    return {
        "text": text,
        "attachments": [{
            "callback_id": f"community:{value['caseId']}:{version}",
            "text": "Chat에는 상태만 표시합니다. 전체 답변은 Community 링크에서 확인하세요.",
            "actions": actions,
        }],
    }


class SynologyBotClient:
    def __init__(self, base_url: str, token_file: str | None, enabled: bool) -> None:
        self.base_url = base_url.rstrip("/")
        self.token_file = token_file
        self.enabled = enabled

    def _token(self) -> str:
        if not self.enabled or not self.token_file:
            raise InvalidBoundaryError("Chat Bot is disabled")
        token = Path(self.token_file).read_text(encoding="utf-8").strip()
        if len(token) < 20 or len(token) > 256:
            raise InvalidBoundaryError("invalid Chat Bot token boundary")
        return token

    def validate(self, supplied: str) -> None:
        if not hmac.compare_digest(self._token(), supplied):
            raise InvalidBoundaryError("invalid Chat Bot token")

    def send(self, user_ids: list[str], payload: dict[str, Any]) -> None:
        if not user_ids:
            return
        token = self._token()
        query = urllib.parse.urlencode({
            "api": "SYNO.Chat.External", "method": "chatbot", "version": "2", "token": json.dumps(token),
        })
        body = {**payload, "user_ids": [int(item) if item.isdigit() else item for item in user_ids]}
        request = urllib.request.Request(
            f"{self.base_url}/webapi/entry.cgi?{query}",
            data=urllib.parse.urlencode({"payload": json.dumps(body, ensure_ascii=False)}).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        if result.get("success") is not True:
            raise RuntimeError("Synology Chat Bot post failed")

    @staticmethod
    def _filename(disposition: str | None) -> str:
        if not disposition:
            raise InvalidBoundaryError("Chat file response has no filename")
        message = Message()
        message["Content-Disposition"] = disposition
        filename = str(message.get_filename() or "").strip()
        if not filename or Path(filename).name != filename or "/" in filename or "\\" in filename:
            raise InvalidBoundaryError("Chat file response has an unsafe filename")
        return filename

    def download_post_file(
        self, post_id: str, destination: Path, *, max_bytes: int, max_archive_bytes: int,
    ) -> ChatPostFile | None:
        """Stream one Bot-visible Chat post file to a private temporary path."""
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", post_id):
            raise InvalidBoundaryError("invalid Chat post id")
        token = self._token()
        query = urllib.parse.urlencode({
            "api": "SYNO.Chat.External", "method": "post_file_get", "version": "2",
            "post_id": post_id, "token": json.dumps(token),
        })
        request = urllib.request.Request(
            f"{self.base_url}/webapi/entry.cgi?{query}", method="GET",
            headers={"Accept": "image/*,text/plain,application/json,application/zip,application/gzip"},
        )
        try:
            response = urllib.request.urlopen(request, timeout=120)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise RuntimeError(f"Synology Chat file download failed with HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError("Synology Chat file download failed") from exc
        with response:
            filename = self._filename(response.headers.get("Content-Disposition"))
            media_type = str(response.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].strip().lower()
            archive = media_type in {"application/zip", "application/gzip", "application/x-gzip", "application/x-zip-compressed"}
            archive = archive or filename.casefold().endswith((".zip", ".gz", ".tgz", ".tar.gz"))
            permitted_bytes = max_archive_bytes if archive else max_bytes
            length_header = response.headers.get("Content-Length")
            try:
                expected = int(length_header) if length_header is not None else None
            except ValueError as exc:
                raise InvalidBoundaryError("Chat file Content-Length is invalid") from exc
            if expected is not None and (expected < 1 or expected > permitted_bytes):
                raise InvalidBoundaryError("Chat file size is outside the permitted boundary")
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            total = 0
            try:
                with destination.open("xb") as target:
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > permitted_bytes:
                            raise InvalidBoundaryError("Chat file size is outside the permitted boundary")
                        target.write(chunk)
            except Exception:
                destination.unlink(missing_ok=True)
                raise
            if total < 1 or (expected is not None and total != expected):
                destination.unlink(missing_ok=True)
                raise InvalidBoundaryError("Chat file download is incomplete")
            return ChatPostFile(filename, media_type, total)


class CommunityFlowClient:
    def __init__(self, approve_file: str | None, reject_file: str | None, enabled: bool) -> None:
        self.approve_file = approve_file
        self.reject_file = reject_file
        self.enabled = enabled

    @staticmethod
    def _read(path: str | None) -> str:
        if not path:
            raise InvalidBoundaryError("Community decision Flow is not configured")
        url = Path(path).read_text(encoding="utf-8").strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "http" or parsed.hostname not in {"activepieces-control", "app"}:
            raise InvalidBoundaryError("Community decision Flow must use the private Activepieces route")
        return url

    def decide(self, decision: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            raise InvalidBoundaryError("Chat Bot is disabled")
        url = self._read(self.approve_file if decision == "APPROVE" else self.reject_file)
        request = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status >= 300:
                raise RuntimeError("Activepieces Community decision Flow failed")
