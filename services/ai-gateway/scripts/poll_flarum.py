#!/usr/bin/env python3
"""Poll new unanswered Flarum discussions and send normalized D0 events to Activepieces."""

from __future__ import annotations

from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
from uuid import uuid4


class ContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.links: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text.append(data.strip())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        href = attributes.get("href") if tag == "a" else None
        source = attributes.get("src") if tag == "img" else None
        upload_uuid = attributes.get("data-fof-upload-download-uuid")
        candidates = [href, source]
        if upload_uuid:
            candidates.append(f"/api/fof/download/{urllib.parse.quote(upload_uuid, safe='')}")
        for candidate in candidates:
            if candidate and candidate not in self.links:
                self.links.append(candidate)


def read_secret(name: str) -> str:
    return Path(os.environ[name]).read_text(encoding="utf-8").strip()


def request_json(
    url: str, *, token: str | None = None, data: dict | None = None, extra_headers: dict[str, str] | None = None
) -> dict:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    headers = {"Accept": "application/vnd.api+json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    headers.update(extra_headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize(payload: dict, base_url: str) -> list[dict]:
    included = {(item["type"], item["id"]): item for item in payload.get("included") or []}
    events = []
    for discussion in payload.get("data") or []:
        attrs = discussion.get("attributes") or {}
        if int(attrs.get("commentCount") or 0) != 1:
            continue
        relationships = discussion.get("relationships") or {}
        post_ref = ((relationships.get("firstPost") or {}).get("data") or {})
        user_ref = ((relationships.get("user") or {}).get("data") or {})
        tag_refs = ((relationships.get("tags") or {}).get("data") or [])
        post = included.get((post_ref.get("type"), post_ref.get("id")), {})
        user = included.get((user_ref.get("type"), user_ref.get("id")), {})
        parser = ContentParser()
        parser.feed((post.get("attributes") or {}).get("contentHtml") or "")
        events.append({
            "discussionId": str(discussion["id"]),
            "discussionUrl": f"{base_url}/d/{discussion['id']}",
            "title": attrs.get("title") or "Community question",
            "question": "\n".join(parser.text)[:4000],
            "authorId": str(user_ref.get("id") or (user.get("attributes") or {}).get("username") or "unknown"),
            "tagSlugs": [
                (included.get((ref.get("type"), ref.get("id")), {}).get("attributes") or {}).get("slug")
                for ref in tag_refs
                if (included.get((ref.get("type"), ref.get("id")), {}).get("attributes") or {}).get("slug")
            ],
            "attachmentUrls": parser.links[:5],
        })
    return events


def upload_artifacts(
    event: dict, gateway_url: str, base_url: str, public_url: str, token: str, correlation: str
) -> list[str]:
    ids = []
    for raw_url in event.pop("attachmentUrls", []):
        public_attachment_url = urllib.parse.urljoin(public_url + "/", raw_url)
        parsed = urllib.parse.urlparse(public_attachment_url)
        if parsed.scheme != "https" or parsed.netloc != urllib.parse.urlparse(public_url).netloc:
            continue
        internal_url = urllib.parse.urljoin(base_url + "/", parsed.path.lstrip("/"))
        if parsed.query:
            internal_url = f"{internal_url}?{parsed.query}"
        req = urllib.request.Request(internal_url, headers={"Authorization": f"Token {token}"})
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read(10 * 1024 * 1024 + 1)
            media_type = response.headers.get_content_type()
            disposition = response.headers.get("Content-Disposition") or ""
        if len(content) > 10 * 1024 * 1024:
            continue
        filename = _attachment_filename(disposition, parsed.path)
        upload = urllib.request.Request(
            gateway_url.rstrip("/") + "/v1/artifacts", data=content, method="POST",
            headers={"Content-Type": media_type, "X-Artifact-Filename": filename,
                     "X-Artifact-Classification": "D0", "X-Correlation-Id": correlation},
        )
        with urllib.request.urlopen(upload, timeout=30) as response:
            ids.append(str(json.loads(response.read().decode("utf-8"))["data"]["artifactId"]))
    return ids


def _attachment_filename(content_disposition: str, path: str) -> str:
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, re.IGNORECASE)
    if encoded:
        return Path(urllib.parse.unquote(encoded.group(1))).name
    quoted = re.search(r'filename="([^"]+)"', content_disposition, re.IGNORECASE)
    if quoted:
        return Path(quoted.group(1)).name
    return Path(path).name or "community-artifact"


def run_once(state_path: Path, *, bootstrap_only: bool = False) -> dict:
    base_url = os.getenv("TECHFLOW_FLARUM_BASE_URL", "https://community.ablecloud.io").rstrip("/")
    public_url = os.getenv("TECHFLOW_FLARUM_PUBLIC_URL", "https://community.ablecloud.io").rstrip("/")
    gateway_url = os.getenv("TECHFLOW_GATEWAY_URL", "http://gateway:8090")
    token = read_secret("TECHFLOW_FLARUM_API_KEY_FILE")
    assistant_user_id_file = os.getenv("TECHFLOW_FLARUM_ASSISTANT_USER_ID_FILE")
    if assistant_user_id_file:
        assistant_user_id = Path(assistant_user_id_file).read_text(encoding="utf-8").strip()
        if assistant_user_id.isdigit():
            token = f"{token}; userId={assistant_user_id}"
    webhook = read_secret("TECHFLOW_COMMUNITY_INGEST_WEBHOOK_FILE")
    api_url = base_url + "/api/discussions?sort=-createdAt&include=user,tags,firstPost&page%5Blimit%5D=50"
    events = normalize(request_json(api_url, token=token), public_url)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"seen": []}
    seen = set(state.get("seen") or [])
    delivered = 0
    for event in reversed(events):
        discussion_id = event["discussionId"]
        if discussion_id in seen:
            continue
        seen.add(discussion_id)
        if bootstrap_only:
            continue
        correlation = f"community-{discussion_id}-{uuid4().hex[:12]}"
        event["correlationId"] = correlation
        event["eventId"] = f"flarum-discussion-{discussion_id}"
        event["artifactIds"] = upload_artifacts(event, gateway_url, base_url, public_url, token, correlation)
        request_json(webhook, data=event)
        delivered += 1
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"seen": sorted(seen, key=int)[-1000:]}, separators=(",", ":")), encoding="utf-8")
    reconcile_id = uuid4().hex
    reconciliation = request_json(
        gateway_url.rstrip("/") + "/v1/community/reviews/reconcile",
        data={},
        extra_headers={"X-Correlation-Id": f"community-reconcile-{reconcile_id}", "Idempotency-Key": f"community-reconcile-{reconcile_id}"},
    )
    return {
        "observed": len(events), "delivered": delivered, "seen": len(seen),
        "reviewsChecked": reconciliation.get("data", {}).get("checked", 0),
        "reviewsApproved": reconciliation.get("data", {}).get("approved", 0),
        "reviewsRetried": reconciliation.get("data", {}).get("retried", 0),
        "reviewRetryFailed": reconciliation.get("data", {}).get("retryFailed", 0),
    }


def main() -> int:
    state_path = Path(os.getenv("TECHFLOW_COMMUNITY_POLLER_STATE", "/var/lib/techflow-community-poller/state.json"))
    first = not state_path.exists()
    interval = max(10, int(os.getenv("TECHFLOW_COMMUNITY_POLL_INTERVAL_SECONDS", "10")))
    once = os.getenv("TECHFLOW_COMMUNITY_POLL_ONCE", "false").lower() == "true"
    while True:
        try:
            result = run_once(state_path, bootstrap_only=first)
            print(json.dumps({"event": "community_poll_completed", **result}, separators=(",", ":")), flush=True)
            first = False
        except Exception as exc:
            print(json.dumps({"event": "community_poll_failed", "errorType": type(exc).__name__}), flush=True)
        if once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
