"""Flarum Community answer publishing boundary."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .store import InvalidBoundaryError


class FlarumResourceNotFound(RuntimeError):
    """A Flarum object was permanently removed or is no longer visible to the configured identity."""


def _marker_url(marker: str) -> str:
    digest = sha256(marker.encode("utf-8")).hexdigest()
    return f"https://community.ablecloud.io/_techflow/{digest}"


def _marked_content(answer: str, marker: str) -> str:
    """Keep idempotency searchable without showing an implementation marker to readers."""
    return f"{answer}\n\n[\u200b]({_marker_url(marker)})"


def _has_marker(attributes: dict[str, Any], marker: str) -> bool:
    content = f"{attributes.get('contentHtml') or ''}\n{attributes.get('content') or ''}"
    return marker in content or _marker_url(marker) in content


TAG_PROFILE_MAP = {
    "mold": "CLOUD_DIPLO",
    "ablestack-vm": "CLOUD_DIPLO",
    "vm-manage": "CLOUD_DIPLO",
    "cube": "SHARED_DOCS",
    "ablestack": "SHARED_DOCS",
    "ablestack-hci": "SHARED_DOCS",
    "ablestack-error": "SHARED_DOCS",
    "ablestack-v4-x-diplo": "SHARED_DOCS",
}


def profiles_for_tags(tag_slugs: list[str]) -> list[str]:
    profiles = []
    for slug in tag_slugs:
        profile = TAG_PROFILE_MAP.get(slug)
        if profile and profile not in profiles:
            profiles.append(profile)
    return profiles or ["SHARED_DOCS"]


def citation_url(citation: dict[str, Any]) -> str:
    repository = citation["repository"]
    commit = citation["commit"]
    path = citation["path"]
    start = citation["startLine"]
    end = citation["endLine"]
    return f"https://github.com/{repository}/blob/{commit}/{path}#L{start}-L{end}"


def format_draft(result: dict[str, Any]) -> str | None:
    """Compatibility alias; Community always receives the safe public projection."""
    from .versioned_assist import format_public_answer

    return format_public_answer(result)


def conversationalize_answer(answer: str) -> str:
    """Convert a legacy sectioned draft to a friendly ongoing reply.

    New drafts are already conversational. This adapter exists for pending
    answers created before the automatic-publication policy was enabled.
    """
    value = answer.strip()
    if "### " not in value:
        return value
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in value.splitlines():
        line = raw.strip()
        if line.startswith("### "):
            current = line[4:].strip()
            sections[current] = []
        elif current and line and not line.startswith("<!--") and not line.startswith(">"):
            sections[current].append(re.sub(r"^(?:[-*]|\d+[.)])\s*", "", line))
    causes = sections.get("원인") or []
    actions = sections.get("해결 방법") or []
    needed = sections.get("추가로 필요한 정보") or []
    considerations = sections.get("추가 고려사항") or []
    lines = ["말씀해 주신 현상을 확인해 보겠습니다."]
    if actions:
        lines.extend(["", "먼저 다음 해결 방법을 적용해 보세요."])
        lines.extend(f"{index}. {item}" for index, item in enumerate(actions[:6], 1))
    if causes:
        lines.extend(["", "이 방법을 먼저 권장하는 이유는 다음과 같습니다."])
        lines.extend(f"- {item}" for item in causes[:3])
    if needed:
        lines.extend(["", "위 조치로 해결되지 않으면 아래 결과를 알려주세요."])
        lines.extend(f"- {item}" for item in needed[:6])
    useful_considerations = [item for item in considerations if "별도의 추가" not in item]
    if useful_considerations:
        lines.extend(["", "확인하실 때 다음 내용도 참고해 주세요."])
        lines.extend(f"- {item}" for item in useful_considerations[:3])
    lines.extend(["", "확인 결과를 댓글로 알려주시면 같은 맥락에서 다음 조치를 이어서 안내하겠습니다."])
    return "\n".join(lines).strip()


class FlarumClient:
    def __init__(
        self,
        base_url: str,
        public_url: str,
        api_key_file: str | None,
        enabled: bool,
        assistant_user_id_file: str | None = None,
        review_post_enabled: bool = False,
        solution_selector_user_id_file: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.public_url = public_url.rstrip("/")
        self.api_key_file = api_key_file
        self.enabled = enabled
        self.assistant_user_id_file = assistant_user_id_file
        self.review_post_enabled = review_post_enabled
        self.solution_selector_user_id_file = solution_selector_user_id_file

    def _authorization(self, *, as_assistant: bool = False, as_solution_selector: bool = False) -> str:
        if not self.api_key_file:
            raise InvalidBoundaryError("community publishing is disabled")
        key = Path(self.api_key_file).read_text(encoding="utf-8").strip()
        if len(key) != 40:
            raise InvalidBoundaryError("invalid Flarum API key boundary")
        if as_assistant and as_solution_selector:
            raise InvalidBoundaryError("ambiguous Flarum actor identity")
        if not as_assistant and not as_solution_selector:
            return f"Token {key}"
        user_id = self._assistant_user_id() if as_assistant else self._solution_selector_user_id()
        return f"Token {key}; userId={user_id}"

    def _assistant_user_id(self) -> str:
        if not self.assistant_user_id_file:
            raise InvalidBoundaryError("Flarum assistant identity is not configured")
        user_id = Path(self.assistant_user_id_file).read_text(encoding="utf-8").strip()
        if not user_id.isdigit() or int(user_id) < 1:
            raise InvalidBoundaryError("invalid Flarum assistant identity boundary")
        return user_id

    def _solution_selector_user_id(self) -> str:
        if not self.solution_selector_user_id_file:
            raise InvalidBoundaryError("Flarum solution selector identity is not configured")
        user_id = Path(self.solution_selector_user_id_file).read_text(encoding="utf-8").strip()
        if not user_id.isdigit() or int(user_id) < 1:
            raise InvalidBoundaryError("invalid Flarum solution selector identity boundary")
        return user_id

    def _request(
        self, path: str, method: str = "GET", body: bytes | None = None, *,
        as_assistant: bool = False, as_solution_selector: bool = False,
    ) -> dict[str, Any]:
        if not self.enabled and not self.review_post_enabled:
            raise InvalidBoundaryError("community publishing is disabled")
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, method=method,
            headers={
                "Authorization": self._authorization(
                    as_assistant=as_assistant, as_solution_selector=as_solution_selector,
                ),
                "Content-Type": "application/json", "Accept": "application/vnd.api+json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FlarumResourceNotFound("Flarum resource not found") from exc
            raise RuntimeError("Flarum request failed") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("Flarum request failed") from exc

    def publish_reply(self, discussion_id: str, answer: str, marker: str) -> dict[str, Any]:
        if not self.enabled:
            raise InvalidBoundaryError("community publishing is disabled")
        query = urllib.parse.urlencode({"filter[discussion]": discussion_id, "page[limit]": "50"})
        existing = self._request(f"/api/posts?{query}")
        for item in existing.get("data") or []:
            attributes = item.get("attributes") or {}
            if _has_marker(attributes, marker):
                post_id = str(item["id"])
                return {"postId": post_id, "postUrl": f"{self.public_url}/d/{discussion_id}/{post_id}", "reused": True}
        body = json.dumps({
            "data": {
                "type": "posts",
                "attributes": {"content": _marked_content(answer, marker)},
                "relationships": {"discussion": {"data": {"type": "discussions", "id": discussion_id}}},
            }
        }, ensure_ascii=False).encode("utf-8")
        payload = self._request("/api/posts", "POST", body)
        post_id = str(payload["data"]["id"])
        return {"postId": post_id, "postUrl": f"{self.public_url}/d/{discussion_id}/{post_id}", "reused": False}

    def publish_review_reply(self, discussion_id: str, answer: str, marker: str) -> dict[str, Any]:
        """Create a full answer as the restricted assistant; Flarum Approval must keep it private."""
        if not self.review_post_enabled:
            raise InvalidBoundaryError("community review posting is disabled")
        query = urllib.parse.urlencode({"filter[discussion]": discussion_id, "page[limit]": "50"})
        # Use the assistant identity for both idempotency lookup and approval polling.
        # Anonymous/unbound API-key reads cannot see Flarum's private unapproved posts.
        existing = self._request(f"/api/posts?{query}", as_assistant=True)
        assistant_user_id = self._assistant_user_id()
        for item in existing.get("data") or []:
            attributes = item.get("attributes") or {}
            if _has_marker(attributes, marker):
                author_id = str((((item.get("relationships") or {}).get("user") or {}).get("data") or {}).get("id") or "")
                if author_id != assistant_user_id:
                    continue
                if attributes.get("isApproved") is True:
                    raise InvalidBoundaryError("review reply is already public")
                post_id = str(item["id"])
                return {"postId": post_id, "postUrl": f"{self.public_url}/d/{discussion_id}/{post_id}", "isApproved": False, "reused": True}
        body = json.dumps({
            "data": {
                "type": "posts",
                "attributes": {"content": _marked_content(answer, marker)},
                "relationships": {"discussion": {"data": {"type": "discussions", "id": discussion_id}}},
            }
        }, ensure_ascii=False).encode("utf-8")
        payload = self._request("/api/posts", "POST", body, as_assistant=True)
        attributes = payload["data"].get("attributes") or {}
        if attributes.get("isApproved") is not False:
            raise InvalidBoundaryError("Flarum did not hold the assistant reply for approval")
        post_id = str(payload["data"]["id"])
        return {"postId": post_id, "postUrl": f"{self.public_url}/d/{discussion_id}/{post_id}", "isApproved": False, "reused": False}

    def publish_assistant_reply(self, discussion_id: str, answer: str, marker: str) -> dict[str, Any]:
        """Publish as the assistant and make the post public without a human approval step.

        The Flarum Approval extension can still hold posts created by the restricted
        assistant account. In that case the privileged integration identity approves
        only the exact post it just created. This preserves the assistant author while
        removing the former moderator workflow.
        """
        if not self.enabled:
            raise InvalidBoundaryError("community publishing is disabled")
        query = urllib.parse.urlencode({"filter[discussion]": discussion_id, "page[limit]": "50"})
        existing = self._request(f"/api/posts?{query}", as_assistant=True)
        assistant_user_id = self._assistant_user_id()
        for item in existing.get("data") or []:
            attributes = item.get("attributes") or {}
            if not _has_marker(attributes, marker):
                continue
            author_id = str((((item.get("relationships") or {}).get("user") or {}).get("data") or {}).get("id") or "")
            if author_id != assistant_user_id:
                continue
            return self._ensure_public(discussion_id, item, reused=True)
        body = json.dumps({
            "data": {
                "type": "posts",
                "attributes": {"content": _marked_content(answer, marker)},
                "relationships": {"discussion": {"data": {"type": "discussions", "id": discussion_id}}},
            }
        }, ensure_ascii=False).encode("utf-8")
        payload = self._request("/api/posts", "POST", body, as_assistant=True)
        return self._ensure_public(discussion_id, payload["data"], reused=False)

    def select_solution(self, discussion_id: str, post_id: str) -> dict[str, Any]:
        """Select and verify the published Knowledge Base post as Flarum's final solution."""
        if not self.enabled:
            raise InvalidBoundaryError("community publishing is disabled")
        if not discussion_id.isdigit() or not post_id.isdigit():
            raise InvalidBoundaryError("invalid Flarum discussion or post identifier")
        path = f"/api/discussions/{discussion_id}?include=bestAnswerPost,bestAnswerUser"
        current = self._request(path, as_solution_selector=True)
        current_relationships = ((current.get("data") or {}).get("relationships") or {})
        current_best = str(
            ((((current_relationships.get("bestAnswerPost") or {}).get("data") or {}).get("id")) or "")
        )
        reused = current_best == post_id
        if not reused:
            body = json.dumps({
                "data": {
                    "type": "discussions", "id": discussion_id,
                    "attributes": {"bestAnswerPostId": int(post_id)},
                }
            }).encode("utf-8")
            self._request(
                f"/api/discussions/{discussion_id}", "PATCH", body, as_solution_selector=True,
            )
            current = self._request(path, as_solution_selector=True)
        relationships = ((current.get("data") or {}).get("relationships") or {})
        selected_post = str((((relationships.get("bestAnswerPost") or {}).get("data") or {}).get("id") or ""))
        selected_user = str((((relationships.get("bestAnswerUser") or {}).get("data") or {}).get("id") or "")) or None
        if selected_post != post_id:
            raise RuntimeError("Flarum did not select the Knowledge Base post as the final solution")
        return {
            "postId": selected_post,
            "postUrl": f"{self.public_url}/d/{discussion_id}/{selected_post}",
            "selectedByUserId": selected_user,
            "reused": reused,
        }

    def _ensure_public(self, discussion_id: str, item: dict[str, Any], *, reused: bool) -> dict[str, Any]:
        post_id = str(item["id"])
        attributes = item.get("attributes") or {}
        if attributes.get("isApproved") is False:
            body = json.dumps({
                "data": {"type": "posts", "id": post_id, "attributes": {"isApproved": True}}
            }).encode("utf-8")
            payload = self._request(f"/api/posts/{post_id}", "PATCH", body)
            attributes = payload.get("data", {}).get("attributes") or {}
        if attributes.get("isApproved") is False:
            raise RuntimeError("Flarum assistant reply remained unapproved")
        return {
            "postId": post_id,
            "postUrl": f"{self.public_url}/d/{discussion_id}/{post_id}",
            "isApproved": True,
            "reused": reused,
        }

    def review_post_is_approved(self, post_id: str) -> bool | None:
        if not post_id.isdigit():
            raise InvalidBoundaryError("invalid review post id")
        try:
            payload = self._request(f"/api/posts/{post_id}", as_assistant=True)
        except FlarumResourceNotFound:
            return None
        return (payload.get("data", {}).get("attributes") or {}).get("isApproved") is True
