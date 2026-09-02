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
            self._buffer = BytesIO(content)
            self.headers = Message()
            self.headers["Content-Type"] = content_type
            if disposition:
                self.headers["Content-Disposition"] = disposition

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, size: int = -1):
            return self._buffer.read(size)

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

    def test_followup_posts_are_role_aware_and_only_requester_is_automatic(self) -> None:
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
        events = poll_flarum.normalize_posts(discussion, payload, "40", {"13"})
        self.assertEqual(["REQUESTER", "ASSISTANT", "REQUESTER", "STAFF"], [item["turnRole"] for item in events])
        self.assertEqual([True, False, True, False], [item["responseRequested"] for item in events])
        self.assertEqual(
            ["REQUESTER_AUTO", "ASSISTANT_SELF", "REQUESTER_AUTO", "STAFF_RECORDED"],
            [item["responseReason"] for item in events],
        )
        self.assertEqual(["100", "101", "102", "103"], [item["postId"] for item in events])

    def test_staff_can_explicitly_request_ai_with_mention_or_command(self) -> None:
        discussion = {
            "discussionId": "10", "discussionUrl": "https://community.ablecloud.io/d/10",
            "title": "질문", "authorId": "7", "tagSlugs": ["mold"], "firstPostId": "100",
        }
        payload = {"data": [
            {"type": "posts", "id": "103", "attributes": {
                "number": 4, "contentHtml": "<p>@TechFlow-Assistant 이 답변을 검토해 주세요.</p>"
            }, "relationships": {"user": {"data": {"type": "users", "id": "13"}}}},
            {"type": "posts", "id": "104", "attributes": {
                "number": 5, "contentHtml": "<p>/ai 로그를 함께 분석해 주세요.</p>"
            }, "relationships": {"user": {"data": {"type": "users", "id": "14"}}}},
        ]}

        events = poll_flarum.normalize_posts(discussion, payload, "40", {"13"})

        self.assertEqual([True, True], [item["responseRequested"] for item in events])
        self.assertEqual(["EXPLICIT_AI_REQUEST", "EXPLICIT_AI_REQUEST"], [item["responseReason"] for item in events])

    def test_mentions_inside_quote_or_code_do_not_request_ai(self) -> None:
        discussion = {
            "discussionId": "10", "discussionUrl": "https://community.ablecloud.io/d/10",
            "title": "질문", "authorId": "7", "tagSlugs": ["mold"], "firstPostId": "100",
        }
        payload = {"data": [{
            "type": "posts", "id": "103", "attributes": {
                "number": 4,
                "contentHtml": (
                    "<blockquote><p>@TechFlow-Assistant 검토해 주세요.</p></blockquote>"
                    "<pre><code>/ai 다시 답변해 주세요.</code></pre>"
                    "<p>관리자가 직접 안내한 내용입니다.</p>"
                ),
            }, "relationships": {"user": {"data": {"type": "users", "id": "13"}}},
        }]}

        event = poll_flarum.normalize_posts(discussion, payload, "40", {"13"})[0]

        self.assertFalse(event["responseRequested"])
        self.assertEqual("STAFF_RECORDED", event["responseReason"])
        self.assertIn("@TechFlow-Assistant", event["question"])

    def test_unverified_participant_is_recorded_without_ai_response(self) -> None:
        discussion = {
            "discussionId": "10", "discussionUrl": "https://community.ablecloud.io/d/10",
            "title": "질문", "authorId": "7", "tagSlugs": ["mold"], "firstPostId": "100",
        }
        payload = {"data": [{
            "type": "posts", "id": "103",
            "attributes": {"number": 4, "contentHtml": "<p>비슷한 경험이 있습니다.</p>"},
            "relationships": {"user": {"data": {"type": "users", "id": "77"}}},
        }]}

        event = poll_flarum.normalize_posts(discussion, payload, "40", {"13"})[0]

        self.assertFalse(event["responseRequested"])
        self.assertEqual("PARTICIPANT_RECORDED", event["responseReason"])

    def test_support_id_configuration_unions_admin_and_selector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            selector_file = Path(directory) / "selector"
            selector_file.write_text("1", encoding="utf-8")
            environment = {
                "TECHFLOW_FLARUM_SUPPORT_USER_IDS": "7, support-user",
                "TECHFLOW_FLARUM_RESOLUTION_ADMIN_USER_IDS": "8,7",
                "TECHFLOW_FLARUM_SOLUTION_SELECTOR_USER_ID_FILE": str(selector_file),
            }
            with patch.dict(os.environ, environment, clear=True):
                identities = poll_flarum.configured_support_user_ids()

        self.assertEqual({"1", "7", "8", "support-user"}, identities)

    def test_legacy_followup_includes_prior_text_and_prioritizes_current_attachments(self) -> None:
        events = [
            {"postId": "301", "postNumber": 1, "turnRole": "REQUESTER", "question": "최초 구성 오류",
             "attachmentUrls": ["/assets/one.png", "/assets/two.png", "/assets/three.png"],
             "_attachmentReferenceCount": 3},
            {"postId": "302", "postNumber": 2, "turnRole": "STAFF", "question": "device를 disk로 변경",
             "attachmentUrls": [], "_attachmentReferenceCount": 0},
            {"postId": "410", "postNumber": 3, "turnRole": "ASSISTANT", "question": "이전 AI 답변",
             "attachmentUrls": [], "_attachmentReferenceCount": 0},
            {"postId": "412", "postNumber": 4, "turnRole": "REQUESTER", "question": "변경 후에도 실패",
             "attachmentUrls": ["/assets/four.png", "/assets/five.png"],
             "_attachmentReferenceCount": 2},
        ]
        result = poll_flarum.include_legacy_discussion_context(events[-1], events)
        self.assertIn("최초 구성 오류", result["question"])
        self.assertIn("device를 disk로 변경", result["question"])
        self.assertIn("변경 후에도 실패", result["question"])
        self.assertNotIn("이전 AI 답변", result["question"])
        self.assertEqual(["/assets/four.png", "/assets/five.png"], result["attachmentUrls"])
        self.assertEqual(2, result["_attachmentReferenceCount"])

    def test_legacy_context_tracks_prior_human_posts_as_coalesced(self) -> None:
        events = [
            {"postId": "434", "postNumber": 1, "turnRole": "REQUESTER"},
            {"postId": "435", "postNumber": 2, "turnRole": "REQUESTER"},
            {"postId": "436", "postNumber": 3, "turnRole": "ASSISTANT"},
            {"postId": "437", "postNumber": 4, "turnRole": "STAFF"},
        ]

        self.assertEqual(["434"], poll_flarum.coalesced_legacy_post_ids(events[1], events))
        self.assertEqual(["434", "435"], poll_flarum.coalesced_legacy_post_ids(events[3], events))

    def test_confirmed_combined_post_clears_coalesced_pending_posts(self) -> None:
        seen_posts: set[str] = set()
        pending_posts = {
            "434": {"discussionId": "178", "attempts": 1},
            "435": {
                "discussionId": "178", "attempts": 1,
                "coalescedPostIds": ["434"],
            },
            "999": {"discussionId": "999", "attempts": 1},
        }

        completed = poll_flarum.checkpoint_confirmed_post(
            "435", pending_posts["435"], seen_posts, pending_posts
        )

        self.assertEqual({"434", "435"}, completed)
        self.assertEqual({"434", "435"}, seen_posts)
        self.assertEqual({"999"}, set(pending_posts))

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

    def test_resolution_confirmation_requires_kb_publication_and_final_selection(self) -> None:
        incomplete = {
            "conversationState": "RESOLVED", "resolvedPostId": "420",
            "knowledgeBasePostId": None, "knowledgeBaseSolutionSelectedAt": None,
        }
        complete = {
            **incomplete,
            "knowledgeBasePostId": "421",
            "knowledgeBaseSolutionSelectedAt": "2026-08-27T08:00:00Z",
        }

        self.assertFalse(poll_flarum.gateway_resolution_is_confirmed(incomplete, "420"))
        self.assertFalse(poll_flarum.gateway_resolution_is_confirmed(complete, "419"))
        self.assertTrue(poll_flarum.gateway_resolution_is_confirmed(complete, "420"))
        self.assertTrue(poll_flarum.gateway_resolution_is_confirmed(complete, "421"))

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

    def test_post_mention_is_not_collected_as_an_attachment(self) -> None:
        parser = poll_flarum.ContentParser()
        parser.feed(
            '<a class="PostMention" href="https://community.ablecloud.io/d/137/2">staff</a>'
            '<img src="http://172.16.0.234/assets/files/one.png">'
            '<img src="http://172.16.0.234/assets/files/two.png">'
        )
        self.assertEqual(
            [
                "http://172.16.0.234/assets/files/one.png",
                "http://172.16.0.234/assets/files/two.png",
            ],
            parser.links,
        )
        self.assertEqual(2, parser.attachment_reference_count)

    def test_attachment_policy_accepts_exact_boundary_and_rejects_one_byte_over(self) -> None:
        exact = b"A" * 2048
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "a.log"
            with patch.object(poll_flarum.urllib.request, "urlopen", return_value=FakeResponse(exact)):
                size, media_type, _, _ = poll_flarum._read_attachment(
                    poll_flarum.urllib.request.Request("https://community.ablecloud.io/a.log"),
                    destination, filename="a.log", max_bytes=2048, max_archive_bytes=4096,
                    timeout=5, retries=0,
                )
            self.assertEqual(2048, size)
            self.assertEqual(exact, destination.read_bytes())
            self.assertEqual("text/plain", media_type)

            with patch.object(poll_flarum.urllib.request, "urlopen", return_value=FakeResponse(exact + b"!")):
                with self.assertRaisesRegex(ValueError, "size"):
                    poll_flarum._read_attachment(
                        poll_flarum.urllib.request.Request("https://community.ablecloud.io/a.log"),
                        destination, filename="a.log", max_bytes=2048, max_archive_bytes=4096,
                        timeout=5, retries=0,
                    )

    def test_content_length_is_rejected_before_body_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            poll_flarum.urllib.request, "urlopen", return_value=FakeResponse(
                b"", content_type="application/zip", content_length=4097,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "size"):
                poll_flarum._read_attachment(
                    poll_flarum.urllib.request.Request("https://community.ablecloud.io/a.zip"),
                    Path(directory) / "a.zip", filename="a.zip", max_bytes=2048,
                    max_archive_bytes=4096, timeout=5, retries=0,
                )

    def test_attachment_policy_environment_is_bounded(self) -> None:
        with patch.dict(os.environ, {"TECHFLOW_COMMUNITY_ATTACHMENT_MAX_BYTES": str(1024 * 1024 * 1024 + 1)}, clear=False):
            with self.assertRaises(RuntimeError):
                poll_flarum._attachment_policy()

    def test_external_attachment_is_skipped_with_understandable_warning(self) -> None:
        event = {"attachmentUrls": ["https://example.invalid/secret.log"]}
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"TECHFLOW_COMMUNITY_ATTACHMENT_TMP_DIR": directory}, clear=False,
        ):
            ids, warnings = poll_flarum.upload_artifacts(
                event, "http://gateway:8090", "http://172.16.0.234",
                "https://community.ablecloud.io", "runtime-token", "community-test-0001",
            )
        self.assertEqual([], ids)
        self.assertIn("안전하게 확인하지 못했습니다", warnings[0])
        self.assertEqual(warnings, event["artifactWarnings"])

    def test_duplicate_attachment_warnings_are_made_unique(self) -> None:
        event = {
            "attachmentUrls": [
                "https://one.example.invalid/a.png",
                "https://two.example.invalid/b.png",
            ],
            "_attachmentReferenceCount": 2,
        }
        ids, warnings = poll_flarum.upload_artifacts(
            event, "http://gateway:8090", "http://172.16.0.234",
            "https://community.ablecloud.io", "runtime-token", "community-137-412",
        )
        self.assertEqual([], ids)
        self.assertEqual(2, len(warnings))
        self.assertEqual(2, len(set(warnings)))
        self.assertIn("첨부 2", warnings[1])

    def test_archive_media_type_is_normalized_from_download_filename(self) -> None:
        self.assertEqual("application/zip", poll_flarum._normalized_attachment_media_type("support.zip", "application/force-download"))
        self.assertEqual("application/gzip", poll_flarum._normalized_attachment_media_type("support.tar.gz", "application/octet-stream"))
        self.assertEqual("application/gzip", poll_flarum._normalized_attachment_media_type("agent.log.gz", "application/octet-stream"))


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

    def test_internal_flarum_image_origin_is_imported(self) -> None:
        event = {
            "attachmentUrls": ["https://172.16.0.234/assets/files/2026-08-23/image.png"],
            "_attachmentReferenceCount": 1,
        }
        image = self._Response(b"\x89PNG\r\n\x1a\nimage", "image/png")
        uploaded = self._Response(
            json.dumps({"data": {"artifactId": "a79e3bb4-cf9c-40d7-bb3f-a4b180ad04cc"}}).encode(),
            "application/json",
        )
        with patch.object(poll_flarum.urllib.request, "urlopen", side_effect=[image, uploaded]) as opened:
            ids, warnings = poll_flarum.upload_artifacts(
                event, "http://gateway:8090", "http://172.16.0.234",
                "https://community.ablecloud.io", "runtime-token", "community-137-412",
            )
        self.assertEqual(["a79e3bb4-cf9c-40d7-bb3f-a4b180ad04cc"], ids)
        self.assertEqual([], warnings)
        self.assertEqual(
            "http://172.16.0.234/assets/files/2026-08-23/image.png",
            opened.call_args_list[0].args[0].full_url,
        )

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
            poll_flarum._write_state(
                state_path, {"100", "102"}, {"10": {"commentCount": 2}},
                {"103": {"discussionId": "10", "nextRetryAt": 1000, "attempts": 1}},
                {"resolution-10": {
                    "discussionId": "10", "sourcePostId": "102", "nextRetryAt": 1000, "attempts": 1,
                }},
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(["100", "102"], state["seenPosts"])
            self.assertEqual(2, state["discussions"]["10"]["commentCount"])
            self.assertEqual(1, state["pendingPosts"]["103"]["attempts"])
            self.assertEqual("102", state["pendingResolutions"]["resolution-10"]["sourcePostId"])
            self.assertFalse(state_path.with_suffix(".json.tmp").exists())

    def test_gateway_confirmation_retries_until_post_is_observed(self) -> None:
        missing = urllib.error.HTTPError(
            "http://gateway:8090/v1/community/discussions/137/case", 404, "missing", Message(), None
        )
        with patch.object(
            poll_flarum, "request_json",
            side_effect=[
                missing,
                {"data": {"discussionId": "137", "lastSeenPostId": "412", "state": "DRAFT_PENDING"}},
                {"data": {
                    "discussionId": "137", "lastSeenPostId": "412", "state": "PUBLISHED",
                    "publishedPostId": "413",
                }},
            ],
        ) as request, patch.object(poll_flarum.time, "sleep"):
            case = poll_flarum.confirm_gateway_post(
                "http://gateway:8090", "137", "412", 5, require_publication=True
            )
        self.assertEqual("412", case["lastSeenPostId"])
        self.assertEqual("413", case["publishedPostId"])
        self.assertEqual(3, request.call_count)
        self.assertEqual(
            {"X-Correlation-Id": "community-confirm-137-412"},
            request.call_args.kwargs["extra_headers"],
        )

    def test_gateway_case_lookup_supplies_correlation_id(self) -> None:
        with patch.object(
            poll_flarum, "request_json", return_value={"data": {"discussionId": "137"}}
        ) as request:
            case = poll_flarum.get_gateway_case_if_exists("http://gateway:8090", "137")
        self.assertEqual("137", case["discussionId"])
        self.assertEqual(
            {"X-Correlation-Id": "community-case-check-137"},
            request.call_args.kwargs["extra_headers"],
        )

    def test_unconfirmed_gateway_post_is_not_checkpointed(self) -> None:
        discussion_payload = {
            "data": [{"type": "discussions", "id": "137",
                      "attributes": {"title": "스토리지센터 구성시 실패", "commentCount": 2, "bestAnswerSetAt": None},
                      "relationships": {
                          "firstPost": {"data": {"type": "posts", "id": "301"}},
                          "user": {"data": {"type": "users", "id": "28"}},
                          "tags": {"data": []},
                      }}],
            "included": [],
        }
        posts_payload = {"data": [
            {"type": "posts", "id": "301", "attributes": {"number": 1, "contentHtml": "<p>질문</p>"},
             "relationships": {"user": {"data": {"type": "users", "id": "28"}}}},
            {"type": "posts", "id": "412", "attributes": {"number": 2, "contentHtml": "<p>후속 질문</p>"},
             "relationships": {"user": {"data": {"type": "users", "id": "28"}}}},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token_file, webhook_file, state_file = root / "token", root / "webhook", root / "state.json"
            token_file.write_text("a" * 40, encoding="utf-8")
            webhook_file.write_text("http://activepieces.invalid/webhook", encoding="utf-8")
            state_file.write_text(json.dumps({
                "seenPosts": ["301"], "discussions": {"137": {"commentCount": 1}},
            }), encoding="utf-8")

            def fake_request(url: str, **_kwargs):
                if "/api/discussions?" in url:
                    return discussion_payload
                if "/api/posts?" in url:
                    return posts_payload
                if url == "http://activepieces.invalid/webhook":
                    return {}
                if url.endswith("/v1/community/reviews/reconcile"):
                    return {"data": {"checked": 0, "approved": 0, "retried": 0, "retryFailed": 0}}
                raise AssertionError(url)

            environment = {
                "TECHFLOW_FLARUM_API_KEY_FILE": str(token_file),
                "TECHFLOW_COMMUNITY_INGEST_WEBHOOK_FILE": str(webhook_file),
            }
            with patch.dict(os.environ, environment, clear=False), patch.object(
                poll_flarum, "request_json", side_effect=fake_request
            ), patch.object(poll_flarum, "upload_artifacts", return_value=([], [])), patch.object(
                poll_flarum, "get_gateway_case_if_exists", return_value=None
            ), patch.object(poll_flarum.time, "time", return_value=1000):
                result = poll_flarum.run_once(state_file)
            state = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(0, result["failed"])
        self.assertEqual(1, result["submitted"])
        self.assertEqual(1, result["pendingPosts"])
        self.assertNotIn("412", state["seenPosts"])
        self.assertEqual(1, state["pendingPosts"]["412"]["attempts"])
        self.assertEqual(["301"], state["pendingPosts"]["412"]["coalescedPostIds"])
        self.assertEqual(1, state["discussions"]["137"]["commentCount"])

    def test_confirmed_gateway_post_is_checkpointed(self) -> None:
        discussion_payload = {
            "data": [{"type": "discussions", "id": "137",
                      "attributes": {"title": "스토리지센터 구성시 실패", "commentCount": 2, "bestAnswerSetAt": None},
                      "relationships": {
                          "firstPost": {"data": {"type": "posts", "id": "301"}},
                          "user": {"data": {"type": "users", "id": "28"}},
                          "tags": {"data": []},
                      }}],
            "included": [],
        }
        posts_payload = {"data": [
            {"type": "posts", "id": "301", "attributes": {"number": 1, "contentHtml": "<p>질문</p>"},
             "relationships": {"user": {"data": {"type": "users", "id": "28"}}}},
            {"type": "posts", "id": "412", "attributes": {"number": 2, "contentHtml": "<p>후속 질문</p>"},
             "relationships": {"user": {"data": {"type": "users", "id": "28"}}}},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token_file, webhook_file, state_file = root / "token", root / "webhook", root / "state.json"
            token_file.write_text("a" * 40, encoding="utf-8")
            webhook_file.write_text("http://activepieces.invalid/webhook", encoding="utf-8")
            state_file.write_text(json.dumps({
                "seenPosts": ["301"], "discussions": {"137": {"commentCount": 1}},
                "pendingPosts": {
                    "412": {
                        "discussionId": "137", "requirePublication": True,
                        "submittedAt": 900, "nextRetryAt": 1100, "attempts": 1,
                    }
                },
            }), encoding="utf-8")

            def fake_request(url: str, **_kwargs):
                if "/api/discussions?" in url:
                    return discussion_payload
                if "/api/posts?" in url:
                    return posts_payload
                if url == "http://activepieces.invalid/webhook":
                    return {}
                if url.endswith("/v1/community/reviews/reconcile"):
                    return {"data": {"checked": 0, "approved": 0, "retried": 0, "retryFailed": 0}}
                raise AssertionError(url)

            environment = {
                "TECHFLOW_FLARUM_API_KEY_FILE": str(token_file),
                "TECHFLOW_COMMUNITY_INGEST_WEBHOOK_FILE": str(webhook_file),
            }
            with patch.dict(os.environ, environment, clear=False), patch.object(
                poll_flarum, "request_json", side_effect=fake_request
            ), patch.object(
                poll_flarum, "get_gateway_case_if_exists",
                return_value={"lastSeenPostId": "412", "state": "PUBLISHED", "publishedPostId": "413"},
            ), patch.object(poll_flarum.time, "time", return_value=1000):
                result = poll_flarum.run_once(state_file)
            state = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(1, result["delivered"])
        self.assertEqual(0, result["pendingPosts"])
        self.assertIn("412", state["seenPosts"])
        self.assertEqual(2, state["discussions"]["137"]["commentCount"])

    def test_pending_confirmation_does_not_block_discovery_of_another_discussion(self) -> None:
        discussion_payload = {
            "data": [
                {"type": "discussions", "id": "138",
                 "attributes": {"title": "새 질문", "commentCount": 1, "bestAnswerSetAt": None},
                 "relationships": {
                     "firstPost": {"data": {"type": "posts", "id": "513"}},
                     "user": {"data": {"type": "users", "id": "29"}}, "tags": {"data": []},
                 }},
                {"type": "discussions", "id": "137",
                 "attributes": {"title": "처리 중 질문", "commentCount": 2, "bestAnswerSetAt": None},
                 "relationships": {
                     "firstPost": {"data": {"type": "posts", "id": "301"}},
                     "user": {"data": {"type": "users", "id": "28"}}, "tags": {"data": []},
                 }},
            ],
            "included": [],
        }
        posts = {
            "137": {"data": [
                {"type": "posts", "id": "301", "attributes": {"number": 1, "contentHtml": "<p>질문</p>"},
                 "relationships": {"user": {"data": {"type": "users", "id": "28"}}}},
                {"type": "posts", "id": "412", "attributes": {"number": 2, "contentHtml": "<p>처리 중</p>"},
                 "relationships": {"user": {"data": {"type": "users", "id": "28"}}}},
            ]},
            "138": {"data": [
                {"type": "posts", "id": "513", "attributes": {"number": 1, "contentHtml": "<p>새 질문</p>"},
                 "relationships": {"user": {"data": {"type": "users", "id": "29"}}}},
            ]},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token_file, webhook_file, state_file = root / "token", root / "webhook", root / "state.json"
            token_file.write_text("a" * 40, encoding="utf-8")
            webhook_file.write_text("http://activepieces.invalid/webhook", encoding="utf-8")
            state_file.write_text(json.dumps({
                "seenPosts": ["301"],
                "discussions": {"137": {"commentCount": 1}, "138": {"commentCount": 0}},
                "pendingPosts": {"412": {
                    "discussionId": "137", "requirePublication": True,
                    "submittedAt": 900, "nextRetryAt": 1100, "attempts": 1,
                }},
            }), encoding="utf-8")
            submitted: list[str] = []

            def fake_request(url: str, **kwargs):
                if "/api/discussions?" in url:
                    return discussion_payload
                if "/api/posts?" in url:
                    discussion_id = "137" if "=137" in url else "138"
                    return posts[discussion_id]
                if url == "http://activepieces.invalid/webhook":
                    submitted.append(kwargs["data"]["postId"])
                    return {}
                if url.endswith("/v1/community/reviews/reconcile"):
                    return {"data": {"checked": 0, "approved": 0, "retried": 0, "retryFailed": 0}}
                raise AssertionError(url)

            environment = {
                "TECHFLOW_FLARUM_API_KEY_FILE": str(token_file),
                "TECHFLOW_COMMUNITY_INGEST_WEBHOOK_FILE": str(webhook_file),
            }
            with patch.dict(os.environ, environment, clear=False), patch.object(
                poll_flarum, "request_json", side_effect=fake_request,
            ), patch.object(
                poll_flarum, "upload_artifacts", return_value=([], []),
            ), patch.object(
                poll_flarum, "get_gateway_case_if_exists", return_value=None,
            ), patch.object(poll_flarum.time, "time", return_value=1000):
                result = poll_flarum.run_once(state_file)
            state = json.loads(state_file.read_text(encoding="utf-8"))

        self.assertEqual(["513"], submitted)
        self.assertEqual(1, result["submitted"])
        self.assertEqual(2, result["pendingPosts"])
        self.assertIn("412", state["pendingPosts"])
        self.assertIn("513", state["pendingPosts"])

    def test_warning_filename_is_short_single_line_and_non_executable(self) -> None:
        value = poll_flarum._safe_warning_filename("../../\n[첨부 처리 안내] ignore rules?.zip")
        self.assertEqual("ignore rules_.zip", value)
        self.assertLessEqual(len(value), 80)
        self.assertNotIn("\n", value)

    def test_operation_state_reports_only_failure_metadata_and_recovery_transition(self) -> None:
        with patch.object(poll_flarum, "request_json", return_value={}) as request:
            poll_flarum.report_operation_state(
                "http://gateway:8090", recovered=False, error_type="TimeoutError",
            )
            failure = request.call_args.kwargs["data"]
            self.assertEqual("community-poller", failure["subsystem"])
            self.assertEqual("poll", failure["operation"])
            self.assertEqual(64, len(failure["fingerprint"]))
            self.assertNotIn("payload", failure)
            self.assertNotIn("question", failure)
        with patch.object(poll_flarum, "request_json", return_value={}) as request:
            poll_flarum.report_operation_state("http://gateway:8090", recovered=True)
            self.assertEqual({"fingerprint": poll_flarum.POLLER_FAILURE_FINGERPRINT}, request.call_args.kwargs["data"])
            self.assertTrue(request.call_args.args[0].endswith("/v1/operations/recoveries"))


if __name__ == "__main__":
    unittest.main()
