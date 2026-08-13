from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "poll_flarum", Path(__file__).parents[1] / "scripts" / "poll_flarum.py"
)
poll_flarum = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(poll_flarum)


class CommunityPollerTests(unittest.TestCase):
    def test_only_unanswered_discussions_are_normalized(self) -> None:
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
        self.assertEqual(["mold"], events[0]["tagSlugs"])
        self.assertEqual(
            ["/assets/screen.png", "/assets/a.log", "/assets/logs.zip"],
            events[0]["attachmentUrls"],
        )

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


if __name__ == "__main__":
    unittest.main()
