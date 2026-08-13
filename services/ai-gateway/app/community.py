"""Flarum Community draft formatting and approved-only publishing boundary."""

from __future__ import annotations

import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .store import InvalidBoundaryError


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


class FlarumClient:
    def __init__(
        self,
        base_url: str,
        public_url: str,
        api_key_file: str | None,
        enabled: bool,
        assistant_user_id_file: str | None = None,
        review_post_enabled: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.public_url = public_url.rstrip("/")
        self.api_key_file = api_key_file
        self.enabled = enabled
        self.assistant_user_id_file = assistant_user_id_file
        self.review_post_enabled = review_post_enabled

    def _authorization(self, *, as_assistant: bool = False) -> str:
        if not self.api_key_file:
            raise InvalidBoundaryError("community publishing is disabled")
        key = Path(self.api_key_file).read_text(encoding="utf-8").strip()
        if len(key) != 40:
            raise InvalidBoundaryError("invalid Flarum API key boundary")
        if not as_assistant:
            return f"Token {key}"
        if not self.assistant_user_id_file:
            raise InvalidBoundaryError("Flarum assistant identity is not configured")
        user_id = Path(self.assistant_user_id_file).read_text(encoding="utf-8").strip()
        if not user_id.isdigit() or int(user_id) < 1:
            raise InvalidBoundaryError("invalid Flarum assistant identity boundary")
        return f"Token {key}; userId={user_id}"

    def _request(
        self, path: str, method: str = "GET", body: bytes | None = None, *, as_assistant: bool = False
    ) -> dict[str, Any]:
        if not self.enabled and not self.review_post_enabled:
            raise InvalidBoundaryError("community publishing is disabled")
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, method=method,
            headers={"Authorization": self._authorization(as_assistant=as_assistant), "Content-Type": "application/json", "Accept": "application/vnd.api+json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("Flarum request failed") from exc

    def publish_reply(self, discussion_id: str, answer: str, marker: str) -> dict[str, Any]:
        if not self.enabled:
            raise InvalidBoundaryError("community publishing is disabled")
        query = urllib.parse.urlencode({"filter[discussion]": discussion_id, "page[limit]": "50"})
        existing = self._request(f"/api/posts?{query}")
        for item in existing.get("data") or []:
            attributes = item.get("attributes") or {}
            if marker in (attributes.get("contentHtml") or "") or marker in (attributes.get("content") or ""):
                post_id = str(item["id"])
                return {"postId": post_id, "postUrl": f"{self.public_url}/d/{discussion_id}/{post_id}", "reused": True}
        body = json.dumps({
            "data": {
                "type": "posts",
                "attributes": {"content": f"{answer}\n\n{marker}"},
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
        existing = self._request(f"/api/posts?{query}")
        for item in existing.get("data") or []:
            attributes = item.get("attributes") or {}
            if marker in (attributes.get("contentHtml") or "") or marker in (attributes.get("content") or ""):
                if attributes.get("isApproved") is True:
                    raise InvalidBoundaryError("review reply is already public")
                post_id = str(item["id"])
                return {"postId": post_id, "postUrl": f"{self.public_url}/d/{discussion_id}/{post_id}", "isApproved": False, "reused": True}
        body = json.dumps({
            "data": {
                "type": "posts",
                "attributes": {"content": f"{answer}\n\n{marker}"},
                "relationships": {"discussion": {"data": {"type": "discussions", "id": discussion_id}}},
            }
        }, ensure_ascii=False).encode("utf-8")
        payload = self._request("/api/posts", "POST", body, as_assistant=True)
        attributes = payload["data"].get("attributes") or {}
        if attributes.get("isApproved") is not False:
            raise InvalidBoundaryError("Flarum did not hold the assistant reply for approval")
        post_id = str(payload["data"]["id"])
        return {"postId": post_id, "postUrl": f"{self.public_url}/d/{discussion_id}/{post_id}", "isApproved": False, "reused": False}

    def review_post_is_approved(self, post_id: str) -> bool:
        if not post_id.isdigit():
            raise InvalidBoundaryError("invalid review post id")
        payload = self._request(f"/api/posts/{post_id}")
        return (payload.get("data", {}).get("attributes") or {}).get("isApproved") is True
