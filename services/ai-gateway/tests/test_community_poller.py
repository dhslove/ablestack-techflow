from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "poll_flarum", Path(__file__).parents[1] / "scripts" / "poll_flarum.py"
)
poll_flarum = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(poll_flarum)


class CommunityPollerTests(unittest.TestCase):
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

    def test_followup_posts_are_role_aware_and_requester_driven(self) -> None:
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
        ]}
        events = poll_flarum.normalize_posts(discussion, payload, "40")
        self.assertEqual(["REQUESTER", "ASSISTANT", "REQUESTER"], [item["turnRole"] for item in events])
        self.assertEqual([True, False, True], [item["responseRequested"] for item in events])
        self.assertEqual(["100", "101", "102"], [item["postId"] for item in events])

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


if __name__ == "__main__":
    unittest.main()
