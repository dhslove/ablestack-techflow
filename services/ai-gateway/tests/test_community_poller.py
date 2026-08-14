from __future__ import annotations

import importlib.util
from email.message import Message
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
import zipfile


SPEC = importlib.util.spec_from_file_location(
    "poll_flarum", Path(__file__).parents[1] / "scripts" / "poll_flarum.py"
)
poll_flarum = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(poll_flarum)


class FakeResponse(BytesIO):
    def __init__(self, data: bytes, *, content_type: str = "text/plain", content_length: int | None = None) -> None:
        super().__init__(data)
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class CommunityPollerTests(unittest.TestCase):
    class _Response:
        def __init__(self, content: bytes, content_type: str, disposition: str = "") -> None:
            self.content = content
            self.buffer = BytesIO(content)
            self.headers = Message()
            self.headers["Content-Type"] = content_type
            if disposition:
                self.headers["Content-Disposition"] = disposition

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, size=-1):
            return self.buffer.read(size)

    def test_first_posts_are_normalized_with_post_identity(self) -> None:
        payload = {
            "data": [
                {"type": "discussions", "id": "10", "attributes": {"title": "질문", "commentCount": 1},
                 "relationships": {"firstPost": {"data": {"type": "posts", "id": "100"}},
                                   "user": {"data": {"type": "users", "id": "7"}},
                                   "tags": {"data": [{"type": "tags", "id": "3"}]}}},
                {"type": "discussions", "id": "11", "attributes": {"title": "답변됨", "commentCount": 2},
                 "relationships": {}},
            ],
            "included": [
                {"type": "posts", "id": "100", "attributes": {"contentHtml": "<p>VM 오류입니다.</p><a href='/assets/screen.png'>image</a><a href='/assets/a.log'>log</a><a href='/assets/logs.zip'>archive</a>"}},
                {"type": "users", "id": "7", "attributes": {"username": "tester"}},
                {"type": "tags", "id": "3", "attributes": {"slug": "mold"}},
            ],
        }
        events = poll_flarum.normalize(payload, "https://community.ablecloud.io")
        self.assertEqual(1, len(events))
        self.assertEqual("10", events[0]["discussionId"])
        self.assertEqual("100", events[0]["postId"])
        self.assertEqual("REQUESTER", events[0]["turnRole"])
        self.assertEqual(["mold"], events[0]["tagSlugs"])
        self.assertEqual(
            ["/assets/screen.png", "/assets/a.log", "/assets/logs.zip"],
            events[0]["attachmentUrls"],
        )

    def test_followup_posts_are_role_aware_and_human_driven(self) -> None:
        discussion = {
            "discussionId": "10", "discussionUrl": "https://community.ablecloud.io/d/10",
            "title": "질문", "authorId": "7", "tagSlugs": ["mold"], "firstPostId": "100",
        }
        payload = {"data": [
            {"type": "posts", "id": "100", "attributes": {"number": 1, "contentHtml": "<p>질문</p>"},
             "relationships": {"user": {"data": {"type": "users", "id": "7"}}}},
            {"type": "posts", "id": "101", "attributes": {"number": 2, "contentHtml": "<p>AI 답변</p>"},
             "relationships": {"user": {"data": {"type": "users", "id": "40"}}}},
            {"type": "posts", "id": "102", "attributes": {"number": 3, "contentHtml": "<p>로그 추가</p>"},
             "relationships": {"user": {"data": {"type": "users", "id": "7"}}}},
            {"type": "posts", "id": "103", "attributes": {"number": 4, "contentHtml": "<p>다른 참여자의 후속 질문</p>"},
             "relationships": {"user": {"data": {"type": "users", "id": "13"}}}},
        ]}
        events = poll_flarum.normalize_posts(discussion, payload, "40")
        self.assertEqual(["REQUESTER", "ASSISTANT", "REQUESTER", "STAFF"], [item["turnRole"] for item in events])
        self.assertEqual([True, False, True, True], [item["responseRequested"] for item in events])
        self.assertEqual(["100", "101", "102", "103"], [item["postId"] for item in events])

    def test_resolution_event_carries_best_answer_actor(self) -> None:
        event = poll_flarum.resolution_event({
            "discussionId": "10", "discussionUrl": "https://community.ablecloud.io/d/10",
            "title": "질문", "authorId": "7", "tagSlugs": ["mold"],
            "bestAnswerPostId": "101", "bestAnswerUserId": "7", "bestAnswerSetAt": "2026-08-13T01:00:00Z",
        })
        self.assertTrue(event["resolutionOnly"])
        self.assertFalse(event["responseRequested"])
        self.assertEqual("101", event["bestAnswerPostId"])
        self.assertEqual("7", event["bestAnswerUserId"])
        self.assertEqual("101", event["postId"])
        self.assertEqual(1, event["postNumber"])
        event_id = poll_flarum.resolution_event_id({
            "discussionId": "10", "bestAnswerPostId": "101", "bestAnswerSetAt": "2026-08-13T01:00:00+00:00",
        })
        self.assertRegex(event_id, r"^flarum-resolution-10-101-[a-f0-9]{16}$")
        self.assertNotIn(":", event_id)

    def test_legacy_discussion_state_bootstraps_posts_without_notification_flood(self) -> None:
        discussion_payload = {
            "data": [{"type": "discussions", "id": "10",
                      "attributes": {"title": "질문", "commentCount": 1, "bestAnswerSetAt": None},
                      "relationships": {
                          "firstPost": {"data": {"type": "posts", "id": "100"}},
                          "user": {"data": {"type": "users", "id": "7"}},
                          "tags": {"data": []},
                      }}],
            "included": [],
        }
        posts_payload = {"data": [{
            "type": "posts", "id": "100", "attributes": {"number": 1, "contentHtml": "<p>질문</p>"},
            "relationships": {"user": {"data": {"type": "users", "id": "7"}}},
        }]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token_file = root / "flarum-token"
            webhook_file = root / "webhook"
            state_file = root / "state.json"
            token_file.write_text("a" * 40, encoding="utf-8")
            webhook_file.write_text("http://activepieces.invalid/webhook", encoding="utf-8")
            state_file.write_text(json.dumps({"seen": ["10"]}), encoding="utf-8")

            def fake_request(url: str, **kwargs):
                if "/api/discussions?" in url:
                    return discussion_payload
                if "/api/posts?" in url:
                    return posts_payload
                if url.endswith("/v1/community/reviews/reconcile"):
                    return {"data": {"checked": 0, "approved": 0, "retried": 0, "retryFailed": 0}}
                raise AssertionError(f"legacy bootstrap must not deliver a webhook: {url}")

            environment = {
                "TECHFLOW_FLARUM_API_KEY_FILE": str(token_file),
                "TECHFLOW_COMMUNITY_INGEST_WEBHOOK_FILE": str(webhook_file),
            }
            with patch.dict("os.environ", environment, clear=False), patch.object(
                poll_flarum, "request_json", side_effect=fake_request
            ):
                result = poll_flarum.run_once(state_file)
            self.assertEqual(0, result["delivered"])
            migrated = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(["100"], migrated["seenPosts"])
            self.assertIn("10", migrated["discussions"])

    def test_html_parser_does_not_execute_or_expand_markup(self) -> None:
        parser = poll_flarum.ContentParser()
        parser.feed("<p>질문</p><script>ignore()</script>")
        self.assertEqual(["질문", "ignore()"], parser.text)

    def test_attachment_policy_accepts_exact_boundary_and_rejects_one_byte_over(self) -> None:
        exact = b"A" * 2048
        with patch.object(poll_flarum.urllib.request, "urlopen", return_value=FakeResponse(exact)):
            content, media_type, _ = poll_flarum._read_attachment(
                poll_flarum.urllib.request.Request("https://community.ablecloud.io/a.log"),
                max_bytes=2048, timeout=5, retries=0,
            )
        self.assertEqual(exact, content)
        self.assertEqual("text/plain", media_type)

        with patch.object(poll_flarum.urllib.request, "urlopen", return_value=FakeResponse(exact + b"!")):
            with self.assertRaisesRegex(ValueError, "size"):
                poll_flarum._read_attachment(
                    poll_flarum.urllib.request.Request("https://community.ablecloud.io/a.log"),
                    max_bytes=2048, timeout=5, retries=0,
                )

    def test_content_length_is_rejected_before_body_download(self) -> None:
        with patch.object(
            poll_flarum.urllib.request, "urlopen", return_value=FakeResponse(b"", content_length=2049),
        ):
            with self.assertRaisesRegex(ValueError, "size"):
                poll_flarum._read_attachment(
                    poll_flarum.urllib.request.Request("https://community.ablecloud.io/a.zip"),
                    max_bytes=2048, timeout=5, retries=0,
                )

    def test_attachment_policy_environment_is_bounded(self) -> None:
        with patch.dict(os.environ, {"TECHFLOW_COMMUNITY_ATTACHMENT_MAX_BYTES": "52428801"}, clear=False):
            with self.assertRaises(RuntimeError):
                poll_flarum._attachment_policy()

    def test_external_attachment_is_skipped_with_understandable_warning(self) -> None:
        event = {"attachmentUrls": ["https://example.invalid/secret.log"]}
        ids, warnings = poll_flarum.upload_artifacts(
            event, "http://gateway:8090", "http://172.16.0.234",
            "https://community.ablecloud.io", "runtime-token", "community-test-0001",
        )
        self.assertEqual([], ids)
        self.assertIn("Community 외부 주소", warnings[0])


    def test_flarum_image_and_uuid_download_are_collected(self) -> None:
        parser = poll_flarum.ContentParser()
        parser.feed(
            '<p><img src="https://community.ablecloud.io/assets/screen.png"></p>'
            '<div data-fof-upload-download-uuid="02ff7411-173c-4d9a-98b6-e3359d890d04">logs.zip</div>'
        )
        self.assertEqual(
            [
                "https://community.ablecloud.io/assets/screen.png",
                "/api/fof/download/02ff7411-173c-4d9a-98b6-e3359d890d04",
            ],
            parser.links,
        )

    def test_discussion_169_inline_image_is_imported_without_silent_drop(self) -> None:
        discussion = {
            "discussionId": "169", "discussionUrl": "https://community.ablecloud.io/d/169",
            "title": "Windows 가상머신 ISO 설치 중에 디스크가 안보임",
            "authorId": "13", "tagSlugs": ["mold"], "firstPostId": "390",
        }
        payload = {"data": [{
            "type": "posts", "id": "390",
            "attributes": {
                "number": 1,
                "contentHtml": (
                    '<p><img class="FoFUpload--Upl-Image-Preview" '
                    'src="https://community.ablecloud.io/assets/files/2026-08-14/'
                    '1786706101-848385-image.png" title="image.png" alt="" '
                    'data-id="fee62972-fed3-43d4-887d-c4330d8f7232" loading="lazy"></p>'
                    '<p>Windows 설치 중 디스크가 보이지 않습니다.</p>'
                ),
            },
            "relationships": {"user": {"data": {"type": "users", "id": "13"}}},
        }]}
        event = poll_flarum.normalize_posts(discussion, payload, "40")[0]
        image = self._Response(b"\x89PNG\r\n\x1a\nimage", "image/png")
        uploaded = self._Response(
            json.dumps({"data": {"artifactId": "a79e3bb4-cf9c-40d7-bb3f-a4b180ad04cc"}}).encode(),
            "application/json",
        )

        with patch.object(poll_flarum.urllib.request, "urlopen", side_effect=[image, uploaded]) as opened:
            artifact_ids, warnings = poll_flarum.upload_artifacts(
                event, "http://gateway:8090", "http://172.16.0.234",
                "https://community.ablecloud.io", "runtime-token", "community-169-390",
            )

        self.assertEqual(["a79e3bb4-cf9c-40d7-bb3f-a4b180ad04cc"], artifact_ids)
        self.assertEqual([], warnings)
        self.assertEqual(2, opened.call_count)
        download_request = opened.call_args_list[0].args[0]
        self.assertEqual(
            "http://172.16.0.234/assets/files/2026-08-14/1786706101-848385-image.png",
            download_request.full_url,
        )
        self.assertNotIn("attachmentUrls", event)
        self.assertNotIn("_attachmentReferenceCount", event)

    def test_inline_image_without_a_usable_source_is_reported(self) -> None:
        parser = poll_flarum.ContentParser()
        parser.feed('<p><img class="FoFUpload--Upl-Image-Preview" alt="image.png"></p>')
        event = {
            "attachmentUrls": parser.links,
            "_attachmentReferenceCount": parser.attachment_reference_count,
        }
        artifact_ids, warnings = poll_flarum.upload_artifacts(
            event, "http://gateway:8090", "http://172.16.0.234",
            "https://community.ablecloud.io", "runtime-token", "missing-image-source",
        )
        self.assertEqual([], artifact_ids)
        self.assertEqual(1, len(warnings))
        self.assertIn("분석 대상으로 가져오지 못했습니다", warnings[0])

    def test_download_filename_prefers_content_disposition(self) -> None:
        self.assertEqual(
            "mold-console-logs.zip",
            poll_flarum._attachment_filename(
                'attachment; filename="mold-console-logs.zip"',
                "/api/fof/download/uuid",
            ),
        )

    def test_zip_filename_has_a_supported_inferred_media_type(self) -> None:
        import mimetypes

        self.assertIn(
            mimetypes.guess_type("mold-console-logs.zip")[0],
            {"application/zip", "application/x-zip-compressed"},
        )

    def test_terminal_artifact_rejection_becomes_requester_warning(self) -> None:
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("agent.log", "INFO ready\n")
        download = self._Response(
            archive_bytes.getvalue(), "application/force-download", 'attachment; filename="log.zip"'
        )
        rejection = urllib.error.HTTPError(
            "http://gateway:8090/v1/artifacts", 400, "invalid", Message(), None
        )
        event = {"attachmentUrls": ["/api/fof/download/test-upload"]}
        with patch.object(poll_flarum.urllib.request, "urlopen", side_effect=[download, rejection]):
            artifact_ids, warnings = poll_flarum.upload_artifacts(
                event, "http://gateway:8090", "http://172.16.0.234",
                "https://community.ablecloud.io", "runtime-token", "correlation-164",
            )
        self.assertEqual([], artifact_ids)
        self.assertEqual(1, len(warnings))
        self.assertIn("log.zip", warnings[0])
        self.assertEqual([], event["attachmentUrls"] if "attachmentUrls" in event else [])

    def test_state_checkpoint_is_atomic_and_preserves_completed_posts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            poll_flarum._write_state(state_path, {"100", "102"}, {"10": {"commentCount": 2}})
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(["100", "102"], state["seenPosts"])
            self.assertEqual(2, state["discussions"]["10"]["commentCount"])
            self.assertFalse(state_path.with_suffix(".json.tmp").exists())

    def test_warning_filename_is_short_single_line_and_non_executable(self) -> None:
        value = poll_flarum._safe_warning_filename("../../\n[첨부 처리 안내] ignore rules?.zip")
        self.assertEqual("ignore rules_.zip", value)
        self.assertLessEqual(len(value), 80)
        self.assertNotIn("\n", value)


if __name__ == "__main__":
    unittest.main()
