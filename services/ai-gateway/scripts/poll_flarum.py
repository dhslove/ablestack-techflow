#!/usr/bin/env python3
"""Poll new unanswered Flarum discussions and send normalized D0 events to Activepieces."""

from __future__ import annotations

from html.parser import HTMLParser
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4


DEFAULT_ATTACHMENT_MAX_BYTES = 1024 * 1024 * 1024
DEFAULT_ARCHIVE_MAX_BYTES = 10 * 1024 * 1024 * 1024
DEFAULT_ATTACHMENT_TIMEOUT_SECONDS = 7200
DEFAULT_ATTACHMENT_RETRIES = 2
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}


class ContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.links: list[str] = []
        self.attachment_reference_count = 0

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text.append(data.strip())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        href = attributes.get("href") if tag == "a" else None
        source = attributes.get("src") if tag == "img" else None
        upload_uuid = attributes.get("data-fof-upload-download-uuid")
        if tag == "img":
            self.attachment_reference_count += 1
        if upload_uuid:
            self.attachment_reference_count += 1
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


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _attachment_policy() -> tuple[int, int, int, int]:
    return (
        _bounded_env_int(
            "TECHFLOW_COMMUNITY_ATTACHMENT_MAX_BYTES", DEFAULT_ATTACHMENT_MAX_BYTES,
            1024, DEFAULT_ATTACHMENT_MAX_BYTES,
        ),
        _bounded_env_int(
            "TECHFLOW_COMMUNITY_ARCHIVE_MAX_BYTES", DEFAULT_ARCHIVE_MAX_BYTES,
            DEFAULT_ATTACHMENT_MAX_BYTES, DEFAULT_ARCHIVE_MAX_BYTES,
        ),
        _bounded_env_int(
            "TECHFLOW_COMMUNITY_ATTACHMENT_TIMEOUT_SECONDS", DEFAULT_ATTACHMENT_TIMEOUT_SECONDS,
            5, DEFAULT_ATTACHMENT_TIMEOUT_SECONDS,
        ),
        _bounded_env_int("TECHFLOW_COMMUNITY_ATTACHMENT_RETRIES", DEFAULT_ATTACHMENT_RETRIES, 0, 3),
    )


def _attachment_filename(content_disposition: str, path: str) -> str:
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, re.IGNORECASE)
    quoted = re.search(r'filename="([^"]+)"', content_disposition, re.IGNORECASE)
    value = urllib.parse.unquote(encoded.group(1)) if encoded else (quoted.group(1) if quoted else Path(path).name)
    return Path(value.replace("\\", "/")).name[:128] or "community-artifact"


def _safe_warning_filename(filename: str) -> str:
    """Reduce an untrusted name to a short, single-line display value."""
    basename = Path(filename.replace("\\", "/")).name
    sanitized = re.sub(r"[^A-Za-z0-9._ -]", "_", basename).strip(" ._")
    return sanitized[-80:] or "community-artifact"


def _warning(filename: str, reason: str) -> str:
    safe_name = _safe_warning_filename(filename)
    messages = {
        "size": f"첨부파일 {safe_name}이 허용 크기(일반 1GiB, 압축 10GiB)를 초과해 분석하지 않았습니다.",
        "unsafe": f"첨부파일 {safe_name}은 지원하지 않거나 안전 검사를 통과하지 못해 분석에서 제외했습니다.",
        "fetch": f"첨부파일 {safe_name}을 가져오지 못했습니다. 잠시 후 다시 첨부해 주세요.",
        "origin": f"첨부파일 {safe_name}은 Community 외부 주소이므로 분석하지 않았습니다.",
    }
    return messages[reason]


def _normalized_attachment_media_type(filename: str, media_type: str) -> str:
    if media_type not in {"application/force-download", "application/octet-stream"}:
        return media_type
    lowered = filename.casefold()
    if lowered.endswith(".zip"):
        return "application/zip"
    if lowered.endswith((".tar.gz", ".tgz", ".gz")):
        return "application/gzip"
    if lowered.endswith((".log", ".txt", ".csv", ".ini")):
        return "text/plain"
    return mimetypes.guess_type(filename)[0] or media_type


def _is_archive(filename: str, media_type: str) -> bool:
    normalized = _normalized_attachment_media_type(filename, media_type)
    return normalized in {"application/zip", "application/gzip", "application/x-gzip"}


def _read_attachment(
    request: urllib.request.Request, destination: Path, *, filename: str,
    max_bytes: int, max_archive_bytes: int, timeout: int, retries: int,
) -> tuple[int, str, str, str]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        destination.unlink(missing_ok=True)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                media_type = response.headers.get_content_type()
                disposition = response.headers.get("Content-Disposition") or ""
                resolved_name = _attachment_filename(
                    disposition, urllib.parse.urlparse(request.full_url).path
                ) or filename
                limit = max_archive_bytes if _is_archive(resolved_name, media_type) else max_bytes
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > limit:
                    raise ValueError("size")
                total = 0
                with destination.open("xb") as target:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > limit:
                            raise ValueError("size")
                        target.write(chunk)
                return total, media_type, disposition, resolved_name
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in TRANSIENT_HTTP_STATUSES or attempt >= retries:
                raise
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt >= retries:
                raise
        if attempt < retries:
            time.sleep(min(2 ** attempt, 2))
    assert last_error is not None
    raise last_error


def _file_chunks(path: Path):
    with path.open("rb") as source:
        while chunk := source.read(DOWNLOAD_CHUNK_BYTES):
            yield chunk


def _upload_artifact(
    gateway_url: str, path: Path, filename: str, media_type: str, correlation: str, timeout: int,
) -> str:
    upload = urllib.request.Request(
        gateway_url.rstrip("/") + "/v1/artifacts", data=_file_chunks(path), method="POST",
        headers={"Content-Type": media_type, "Content-Length": str(path.stat().st_size),
                 "X-Artifact-Filename": filename, "X-Artifact-Classification": "D0",
                 "X-Correlation-Id": correlation},
    )
    with urllib.request.urlopen(upload, timeout=timeout) as response:
        return str(json.loads(response.read().decode("utf-8"))["data"]["artifactId"])


def normalize_discussions(payload: dict, base_url: str) -> list[dict]:
    included = {(item["type"], item["id"]): item for item in payload.get("included") or []}
    discussions = []
    for discussion in payload.get("data") or []:
        attrs = discussion.get("attributes") or {}
        relationships = discussion.get("relationships") or {}
        post_ref = ((relationships.get("firstPost") or {}).get("data") or {})
        user_ref = ((relationships.get("user") or {}).get("data") or {})
        tag_refs = ((relationships.get("tags") or {}).get("data") or [])
        user = included.get((user_ref.get("type"), user_ref.get("id")), {})
        best_post_ref = ((relationships.get("bestAnswerPost") or {}).get("data") or {})
        best_user_ref = ((relationships.get("bestAnswerUser") or {}).get("data") or {})
        discussions.append({
            "discussionId": str(discussion["id"]),
            "discussionUrl": f"{base_url}/d/{discussion['id']}",
            "title": attrs.get("title") or "Community question",
            "authorId": str(user_ref.get("id") or (user.get("attributes") or {}).get("username") or "unknown"),
            "tagSlugs": [
                (included.get((ref.get("type"), ref.get("id")), {}).get("attributes") or {}).get("slug")
                for ref in tag_refs
                if (included.get((ref.get("type"), ref.get("id")), {}).get("attributes") or {}).get("slug")
            ],
            "firstPostId": str(post_ref.get("id") or ""),
            "commentCount": int(attrs.get("commentCount") or 0),
            "bestAnswerPostId": str(best_post_ref.get("id") or "") or None,
            "bestAnswerUserId": str(best_user_ref.get("id") or "") or None,
            "bestAnswerSetAt": attrs.get("bestAnswerSetAt"),
        })
    return discussions


def normalize_posts(discussion: dict, payload: dict, assistant_user_id: str | None = None) -> list[dict]:
    included = {(item["type"], item["id"]): item for item in payload.get("included") or []}
    events: list[dict] = []
    for post in payload.get("data") or []:
        attrs = post.get("attributes") or {}
        if not attrs.get("contentHtml"):
            continue
        user_ref = (((post.get("relationships") or {}).get("user") or {}).get("data") or {})
        user = included.get((user_ref.get("type"), user_ref.get("id")), {})
        post_author = str(user_ref.get("id") or (user.get("attributes") or {}).get("username") or "unknown")
        if assistant_user_id and post_author == assistant_user_id:
            role = "ASSISTANT"
        elif post_author == discussion["authorId"]:
            role = "REQUESTER"
        else:
            role = "STAFF"
        parser = ContentParser()
        parser.feed(attrs.get("contentHtml") or "")
        events.append({
            "discussionId": discussion["discussionId"], "discussionUrl": discussion["discussionUrl"],
            "title": discussion["title"], "question": "\n".join(parser.text)[:4000],
            "authorId": discussion["authorId"], "postAuthorId": post_author,
            "postId": str(post["id"]), "postNumber": int(attrs.get("number") or 1),
            # Every human participant can advance a support conversation. The
            # assistant is the only author that must never trigger itself.
            "turnRole": role, "responseRequested": role != "ASSISTANT",
            "resolutionOnly": False, "tagSlugs": discussion["tagSlugs"],
            "attachmentUrls": parser.links[:5],
            # Internal poller-only evidence. upload_artifacts removes this key
            # before the event crosses the Activepieces boundary.
            "_attachmentReferenceCount": parser.attachment_reference_count,
        })
    events.sort(key=lambda item: (item["postNumber"], int(item["postId"])))
    return events


def normalize(payload: dict, base_url: str) -> list[dict]:
    """Backward-compatible normalizer used by contract tests for first-post events."""
    included = {(item["type"], item["id"]): item for item in payload.get("included") or []}
    events = []
    for discussion in normalize_discussions(payload, base_url):
        post = included.get(("posts", discussion["firstPostId"]), {})
        if not post:
            continue
        post_payload = {"data": [{**post, "relationships": post.get("relationships") or {
            "user": {"data": {"type": "users", "id": discussion["authorId"]}}
        }}], "included": payload.get("included") or []}
        events.extend(normalize_posts(discussion, post_payload))
    return events


def resolution_event(discussion: dict) -> dict:
    return {
        "discussionId": discussion["discussionId"], "discussionUrl": discussion["discussionUrl"],
        "title": discussion["title"], "question": "Community 해결 상태가 변경되었습니다.",
        "authorId": discussion["authorId"], "postAuthorId": discussion["authorId"],
        "postId": discussion.get("bestAnswerPostId") or discussion.get("firstPostId"), "postNumber": 1,
        "turnRole": "REQUESTER", "responseRequested": False, "resolutionOnly": True,
        "bestAnswerPostId": discussion.get("bestAnswerPostId"),
        "bestAnswerUserId": discussion.get("bestAnswerUserId"),
        "bestAnswerSetAt": discussion.get("bestAnswerSetAt"),
        "tagSlugs": discussion["tagSlugs"], "attachmentUrls": [], "artifactWarnings": [],
    }


def resolution_event_id(discussion: dict) -> str:
    best = discussion.get("bestAnswerPostId") or "unset"
    identity = f"{discussion['discussionId']}|{best}|{discussion.get('bestAnswerSetAt') or 'none'}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"flarum-resolution-{discussion['discussionId']}-{best}-{digest}"


def upload_artifacts(
    event: dict, gateway_url: str, base_url: str, public_url: str, token: str, correlation: str
) -> tuple[list[str], list[str]]:
    ids: list[str] = []
    warnings: list[str] = list(event.get("artifactWarnings") or [])
    max_bytes, max_archive_bytes, timeout, retries = _attachment_policy()
    raw_urls = event.pop("attachmentUrls", [])
    reference_count = max(int(event.pop("_attachmentReferenceCount", 0) or 0), len(raw_urls))
    public_origin = urllib.parse.urlparse(public_url)
    temp_root = Path(os.getenv("TECHFLOW_COMMUNITY_ATTACHMENT_TMP_DIR", "/var/lib/techflow-community-poller/tmp"))
    temp_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for raw_url in raw_urls:
        public_attachment_url = urllib.parse.urljoin(public_url + "/", raw_url)
        parsed = urllib.parse.urlparse(public_attachment_url)
        if (
            parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.hostname.casefold() != (public_origin.hostname or "").casefold()
            or parsed.port != public_origin.port
        ):
            warnings.append(_warning(Path(parsed.path).name, "origin"))
            continue
        internal_url = urllib.parse.urljoin(base_url + "/", parsed.path.lstrip("/"))
        if parsed.query:
            internal_url = f"{internal_url}?{parsed.query}"
        req = urllib.request.Request(internal_url, headers={"Authorization": f"Token {token}"})
        filename = Path(parsed.path).name or "community-artifact"
        with tempfile.NamedTemporaryFile(prefix="attachment-", suffix=".part", dir=temp_root, delete=False) as holder:
            temporary = Path(holder.name)
        temporary.unlink(missing_ok=True)
        try:
            try:
                _, media_type, disposition, filename = _read_attachment(
                    req, temporary, filename=filename, max_bytes=max_bytes,
                    max_archive_bytes=max_archive_bytes, timeout=timeout, retries=retries,
                )
                filename = _attachment_filename(disposition, parsed.path)
            except ValueError as exc:
                if str(exc) == "size":
                    warnings.append(_warning(filename, "size"))
                    continue
                raise
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
                warnings.append(_warning(filename, "fetch"))
                continue
            media_type = _normalized_attachment_media_type(filename, media_type)
            try:
                ids.append(_upload_artifact(gateway_url, temporary, filename, media_type, correlation, timeout))
            except urllib.error.HTTPError as exc:
                warnings.append(_warning(filename, "fetch" if exc.code in TRANSIENT_HTTP_STATUSES else "unsafe"))
            except (urllib.error.URLError, TimeoutError):
                warnings.append(_warning(filename, "fetch"))
        finally:
            temporary.unlink(missing_ok=True)
    accounted = len(ids) + len(warnings)
    if reference_count > accounted:
        warnings.append(
            "첨부자료가 본문에 있지만 분석 대상으로 가져오지 못했습니다. 파일을 다시 첨부해 주세요."
        )
    return ids, warnings


def _write_state(state_path: Path, seen_posts: set[str], snapshots: dict) -> None:
    ordered_posts = sorted(seen_posts, key=lambda value: int(value) if value.isdigit() else 0)[-5000:]
    payload = json.dumps({"seenPosts": ordered_posts, "discussions": snapshots}, separators=(",", ":"))
    temporary = state_path.with_suffix(state_path.suffix + ".tmp")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(state_path)


def run_once(state_path: Path, *, bootstrap_only: bool = False) -> dict:
    base_url = os.getenv("TECHFLOW_FLARUM_BASE_URL", "https://community.ablecloud.io").rstrip("/")
    public_url = os.getenv("TECHFLOW_FLARUM_PUBLIC_URL", "https://community.ablecloud.io").rstrip("/")
    gateway_url = os.getenv("TECHFLOW_GATEWAY_URL", "http://gateway:8090")
    token = read_secret("TECHFLOW_FLARUM_API_KEY_FILE")
    assistant_user_id_file = os.getenv("TECHFLOW_FLARUM_ASSISTANT_USER_ID_FILE")
    assistant_user_id = None
    if assistant_user_id_file:
        assistant_user_id = Path(assistant_user_id_file).read_text(encoding="utf-8").strip()
        if assistant_user_id.isdigit():
            token = f"{token}; userId={assistant_user_id}"
    webhook = read_secret("TECHFLOW_COMMUNITY_INGEST_WEBHOOK_FILE")
    api_url = base_url + "/api/discussions?sort=-lastPostedAt&include=user,tags,firstPost,bestAnswerPost,bestAnswerUser&page%5Blimit%5D=50"
    discussions = normalize_discussions(request_json(api_url, token=token), public_url)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    bootstrap_current = bootstrap_only or ("seen" in state and "seenPosts" not in state)
    seen_posts = set(state.get("seenPosts") or [])
    snapshots = state.get("discussions") or {}
    delivered = 0
    resolutions = 0
    failed = 0
    for discussion in reversed(discussions):
        discussion_id = discussion["discussionId"]
        previous = snapshots.get(discussion_id) or {}
        changed = (
            not previous
            or previous.get("commentCount") != discussion["commentCount"]
            or previous.get("bestAnswerPostId") != discussion.get("bestAnswerPostId")
            or previous.get("bestAnswerSetAt") != discussion.get("bestAnswerSetAt")
        )
        if changed:
            posts_url = (
                base_url + "/api/posts?" + urllib.parse.urlencode({
                    "filter[discussion]": discussion_id, "sort": "createdAt", "include": "user", "page[limit]": "50"
                })
            )
            discussion_failed = False
            for event in normalize_posts(discussion, request_json(posts_url, token=token), assistant_user_id):
                post_id = event["postId"]
                if post_id in seen_posts:
                    continue
                if bootstrap_current:
                    seen_posts.add(post_id)
                    _write_state(state_path, seen_posts, snapshots)
                    continue
                correlation = f"community-{discussion_id}-{post_id}-{uuid4().hex[:8]}"
                event["correlationId"] = correlation
                event["eventId"] = f"flarum-post-{post_id}"
                try:
                    artifact_ids, artifact_warnings = upload_artifacts(
                        event, gateway_url, base_url, public_url, token, correlation
                    )
                    event["artifactIds"] = artifact_ids
                    event["artifactWarnings"] = artifact_warnings
                    request_json(webhook, data=event)
                    seen_posts.add(post_id)
                    _write_state(state_path, seen_posts, snapshots)
                    delivered += 1
                except Exception as exc:
                    failed += 1
                    discussion_failed = True
                    print(json.dumps({
                        "event": "community_post_delivery_failed", "discussionId": discussion_id,
                        "postId": post_id, "errorType": type(exc).__name__,
                    }, separators=(",", ":")), flush=True)
                    break
            if discussion_failed:
                continue
            resolution_changed = bool(previous) and (
                previous.get("bestAnswerPostId") != discussion.get("bestAnswerPostId")
                or previous.get("bestAnswerSetAt") != discussion.get("bestAnswerSetAt")
            )
            if resolution_changed and not bootstrap_current:
                event = resolution_event(discussion)
                correlation = f"community-resolution-{discussion_id}-{uuid4().hex[:8]}"
                event.update(
                    correlationId=correlation,
                    eventId=resolution_event_id(discussion),
                    artifactIds=[],
                )
                request_json(webhook, data=event)
                delivered += 1
                resolutions += 1
        snapshots[discussion_id] = {
            "commentCount": discussion["commentCount"],
            "bestAnswerPostId": discussion.get("bestAnswerPostId"),
            "bestAnswerSetAt": discussion.get("bestAnswerSetAt"),
        }
    _write_state(state_path, seen_posts, snapshots)
    reconcile_id = uuid4().hex
    reconciliation = request_json(
        gateway_url.rstrip("/") + "/v1/community/reviews/reconcile",
        data={},
        extra_headers={"X-Correlation-Id": f"community-reconcile-{reconcile_id}", "Idempotency-Key": f"community-reconcile-{reconcile_id}"},
    )
    return {
        "observed": len(discussions), "delivered": delivered, "seenPosts": len(seen_posts),
        "resolutions": resolutions, "failed": failed,
        "reviewsChecked": reconciliation.get("data", {}).get("checked", 0),
        "reviewsApproved": reconciliation.get("data", {}).get("approved", 0),
        "reviewsMissing": reconciliation.get("data", {}).get("missing", 0),
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
