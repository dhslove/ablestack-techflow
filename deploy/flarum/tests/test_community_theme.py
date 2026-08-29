from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
THEME = ROOT / "deploy" / "flarum" / "extensions" / "ablecloud-community-theme"


def luminance(hex_color: str) -> float:
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class CommunityThemeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.composer = json.loads((THEME / "composer.json").read_text(encoding="utf-8"))
        cls.less = (THEME / "resources" / "less" / "forum.less").read_text(encoding="utf-8")
        cls.korean = (THEME / "locale" / "ko.yml").read_text(encoding="utf-8")
        cls.forum_js = (THEME / "js" / "dist" / "forum.js").read_text(encoding="utf-8")
        cls.extend_php = (THEME / "extend.php").read_text(encoding="utf-8")
        cls.rehearsal = (ROOT / "deploy" / "flarum" / "rehearse-community-theme.sh").read_text(encoding="utf-8")

    def test_is_isolated_flarum_extension(self) -> None:
        self.assertEqual(self.composer["type"], "flarum-extension")
        self.assertEqual(self.composer["require"]["flarum/core"], "^1.8")
        self.assertNotIn("vendor/", self.rehearsal)
        self.assertIn("extension:disable", self.rehearsal)

    def test_required_screen_contracts(self) -> None:
        selectors = (
            ".WelcomeHero",
            ".DiscussionListItem",
            ".DiscussionHero",
            ".Post-body",
            ".Composer",
            ".FoFUpload-uploadButton",
            ".Search-input input",
            ".Modal-content",
            ".UserHero",
            ".UserPage-content",
            ".SettingsPage",
            ".UserSecurityPage",
            ".NotificationGrid",
            ".AccessTokensList",
        )
        for selector in selectors:
            with self.subTest(selector=selector):
                self.assertIn(selector, self.less)

    def test_ai_states_are_distinct(self) -> None:
        for state in ("assistant", "knowledge-base", "needs-information"):
            self.assertIn(f"TechFlowPost--{state}", self.less)
        self.assertIn("/u/TechFlow-Assistant", self.less)
        self.assertIn('content: "최종 해결 가이드"', self.less)

    def test_korean_best_answer_labels(self) -> None:
        for text in ("해결됨", "해결 답변으로 선택", "해결 답변 선택 취소", "해결된 답변"):
            self.assertIn(text, self.less)
        self.assertIn("answered_badge: 해결됨", self.korean)
        self.assertIn("this_best_answer: 해결 답변으로 선택", self.korean)
        self.assertIn("remove_best_answer: 해결 답변 선택 취소", self.korean)
        self.assertIn("best_answer_button: 해결 답변", self.korean)
        self.assertIn("label: 연결된 계정", self.korean)
        self.assertIn("unlink: 계정 연결 해제", self.korean)
        self.assertIn("discussions_solutions_heading: 해결된 토론", self.korean)
        self.assertIn("해결된 토론 검색", self.korean)

    def test_accessibility_contract(self) -> None:
        self.assertIn(":focus-visible", self.less)
        self.assertIn("prefers-reduced-motion", self.less)

    def test_embedded_svg_icon_and_navigation_contract(self) -> None:
        self.assertIn("--ablecloud-icon", self.less)
        self.assertIn("mask-image: var(--ablecloud-icon, none)", self.less)
        for icon in (
            ".fa-bars",
            ".fa-flag",
            ".fa-bell",
            ".fa-user",
            ".fa-cog",
            ".fa-sign-out-alt",
            ".fa-sync",
            ".fa-comment",
            ".fa-thumbs-up",
            ".fa-file-upload",
            ".fa-at",
            ".fa-shield-alt",
            ".fa-book",
            ".fa-angle-double-up",
            ".fa-angle-double-down",
            ".fa-envelope",
            ".fa-stopwatch",
            ".fa-paper-plane",
            ".fa-photo-video",
            ".fa-smile",
            ".fa-eye",
            ".fa-eye-slash",
            ".fa-bold",
            ".fa-italic",
            ".fa-code",
            ".fa-quote-left",
            ".fa-link",
            ".fa-image",
            ".fa-list-ul",
            ".fa-list-ol",
            ".fa-plus",
            ".fa-strikethrough",
            ".fa-subscript",
            ".fa-superscript",
            ".fa-terminal",
            ".fa-caret-square-right",
            ".fa-google",
            ".fa-github",
        ):
            with self.subTest(icon=icon):
                self.assertIn(icon, self.less)
        self.assertIn(".sideNav .Dropdown-menu > li > a:hover", self.less)
        self.assertIn(".UserPage .UserPage-nav .Dropdown-menu > li > a:hover", self.less)
        self.assertIn("transform: translateX(2px)", self.less)
        self.assertIn("font-size: 18px", self.less)
        self.assertIn(".Header-secondary > ul", self.less)
        self.assertIn("height: 44px", self.less)
        self.assertIn('width: ~"calc(100% - var(--ablecloud-page-inline-space))"', self.less)
        self.assertIn("--ablecloud-footer-icon", self.less)
        self.assertGreaterEqual(len(re.findall(r"min-height:\s*44px", self.less)), 3)
        self.assertGreaterEqual(contrast("#155eef", "#ffffff"), 4.5)
        self.assertGreaterEqual(contrast("#15253e", "#ffffff"), 12.0)
        self.assertGreaterEqual(contrast("#056038", "#d9f5e6"), 6.0)

    def test_responsive_and_korean_readability_contract(self) -> None:
        self.assertIn("@media (max-width: 767px)", self.less)
        self.assertIn("word-break: keep-all", self.less)
        self.assertIn('"Noto Sans KR"', self.less)
        self.assertIn("font-size: 16px", self.less)

    def test_tag_date_format_contract(self) -> None:
        self.assertIn("->js(__DIR__.'/js/dist/forum.js')", self.extend_php)
        self.assertIn("flarum.core.compat['forum/app']", self.forum_js)
        self.assertIn("module.exports = {}", self.forum_js)
        self.assertIn(".TagTile-lastPostedDiscussion time[datetime]", self.forum_js)
        self.assertIn("relativeDatePattern", self.forum_js)
        self.assertIn("matched[1].slice(-2) + '년 '", self.forum_js)
        self.assertIn("Number(matched[2]) + '월 '", self.forum_js)
        self.assertIn("Number(matched[3]) + '일'", self.forum_js)
        self.assertIn("normalizeDiscussionListTargets", self.forum_js)
        self.assertIn(".DiscussionListItem-main[href]", self.forum_js)
        self.assertIn("data-ablecloud-start-from-top", self.forum_js)
        self.assertIn("/(\\/d\\/[^/]+)\\/\\d+\\/?$/", self.forum_js)
        self.assertIn("openDiscussionFromTop", self.forum_js)
        self.assertNotIn("window.location.assign(href)", self.forum_js)
        self.assertNotIn("event.preventDefault()", self.forum_js.split("function openDiscussionFromTop", 1)[1].split("function captureDiscussionListSnapshot", 1)[0])
        self.assertIn("window.scrollTo(0, 0)", self.forum_js)
        self.assertIn("canonicalPath.replace(/\\/$/, '') + '/1'", self.forum_js)
        self.assertIn("ensureDiscussionFirstPostRoute", self.forum_js)
        self.assertIn("keepDiscussionAtTop", self.forum_js)
        self.assertIn("window.history.scrollRestoration = 'manual'", self.forum_js)
        self.assertIn("document.addEventListener('click', openDiscussionFromTop, true)", self.forum_js)
        self.assertIn("captureDiscussionListSnapshot", self.forum_js)
        self.assertIn("ensureFallbackDiscussionPane", self.forum_js)
        self.assertIn("ablecloud-community-discussion-list", self.forum_js)
        self.assertIn("data-ablecloud-fallback-pane", self.forum_js)
        self.assertIn("forumApp.pane.enable()", self.forum_js)
        self.assertNotIn("addFallbackPanePinButton", self.forum_js)
        self.assertIn("document.addEventListener('mousemove', showFallbackPaneFromEdge", self.forum_js)
        self.assertIn("syncComposerPaneState", self.forum_js)
        self.assertIn("app.classList.toggle('ablecloud-composer-open', composerOpen)", self.forum_js)
        self.assertIn("document.documentElement.classList.toggle('ablecloud-composer-open', composerOpen)", self.forum_js)
        self.assertIn("composerOpen && forumApp.pane", self.forum_js)
        self.assertIn("forumApp.pane.hide()", self.forum_js)

    def test_infinite_scroll_emoji_and_new_discussion_dialog_contract(self) -> None:
        for script_contract in (
            "enhanceInfiniteDiscussionLoading",
            "new window.IntersectionObserver",
            "rootMargin: '0px 0px 120px 0px'",
            "currentButton.click()",
            "data-ablecloud-auto-load",
            "handleEmojiPaletteClick",
            "ablecloud-EmojiPicker",
            "data-ablecloud-emoji",
            "document.execCommand('insertText'",
            "삽입할 이모지를 선택하세요.",
            "ablecloud-new-discussion-open",
            "attributeFilter: ['class']",
            "window.setTimeout(schedule, 150)",
            "window.setTimeout(schedule, 600)",
        ):
            with self.subTest(script_contract=script_contract):
                self.assertIn(script_contract, self.forum_js)

        for style_contract in (
            "&.ablecloud-new-discussion-open .App-composer",
            "background: rgba(20, 42, 75, 0.46)",
            "max-width: 960px",
            "height: calc(100vh - 120px) !important",
            ".ablecloud-EmojiPicker-grid",
            "grid-template-columns: repeat(6, minmax(0, 1fr))",
            ".EmojiDropdown > li:not(.Dropdown-header) > button",
        ):
            with self.subTest(style_contract=style_contract):
                self.assertIn(style_contract, self.less)

    def test_mobile_navigation_and_dialog_contract(self) -> None:
        for script_contract in (
            "syncMobileNavigationState",
            "탐색 서랍 닫기",
            "탐색 서랍 열기",
            "handleMobileOverlayKeydown",
            "handleMobileNavigationClick",
            "handleMobileComposerCloseClick",
            "document.body.classList.contains('ablecloud-composer-open')",
            "forumApp.composer.hide()",
            "작성 중인 내용을 취소하고 대화상자를 닫으시겠습니까?",
            "drawerToggle.click()",
        ):
            with self.subTest(script_contract=script_contract):
                self.assertIn(script_contract, self.forum_js)

        for style_contract in (
            ".App--index .IndexPage-nav",
            ".App--index .IndexPage-nav > ul",
            "pointer-events: none",
            ".App.drawerOpen .App-drawer",
            ".App.drawerOpen .Header-secondary > ul",
            ".dropdown:not(.open) > .Dropdown-menu",
            ".App.drawerOpen .Header-secondary .Dropdown-menu > .dropdown-backdrop",
            "flex-direction: column",
            ".App.drawerOpen .Navigation-drawer",
            ".App.drawerOpen .Navigation-drawer .fa-bars",
            ".Modal-body",
            "max-height: calc(100vh - 24px)",
            ".Modal-close .Button",
            ".Modal-close .Button::after",
            ".Composer-controls .item-close",
            ".Composer-controls .item-close .Button::after",
            "&.ablecloud-composer-open .Composer:not(.fullScreen) .Composer-controls .item-minimize",
            "&.ablecloud-composer-open .Composer:not(.fullScreen) .Composer-controls .item-close",
            "z-index: 1002",
            "display: block !important",
        ):
            with self.subTest(style_contract=style_contract):
                self.assertIn(style_contract, self.less)

    def test_reddit_style_discussion_item_structure_contract(self) -> None:
        for script_contract in (
            "enhanceDiscussionListItems",
            "forumApp.store.getById('discussions'",
            "discussion.firstPost()",
            "firstPost.contentPlain()",
            "ablecloud-DiscussionMeta",
            "ablecloud-DiscussionSummary",
            "formatDiscussionCreatedAt",
            "data-ablecloud-post-structure",
            "meta.setAttribute('aria-label', '토론 작성 정보')",
            "badges.setAttribute('aria-label', '해결된 토론')",
            "findDiscussionThumbnail",
            "firstPost.contentHtml()",
            "template.content.querySelector('img[src]')",
            "thumbnailImage.loading = 'lazy'",
            "ablecloud-DiscussionMain--withThumbnail",
            "ablecloud-DiscussionThumbnail",
        ):
            with self.subTest(script_contract=script_contract):
                self.assertIn(script_contract, self.forum_js)

        for style_contract in (
            ".ablecloud-DiscussionMeta",
            ".ablecloud-DiscussionMeta-category",
            ".ablecloud-DiscussionSummary",
            "-webkit-line-clamp: 2",
            ".App--index .IndexPage-results .DiscussionListItem-badges .Badge--bestAnswer::after",
            'content: "해결됨"',
            "min-height: 136px",
            "font-size: 18px",
            ".ablecloud-DiscussionThumbnail",
            "object-fit: cover",
            "grid-template-columns: minmax(0, 1fr) 124px",
            "grid-template-columns: minmax(0, 1fr) 88px",
        ):
            with self.subTest(style_contract=style_contract):
                self.assertIn(style_contract, self.less)

    def test_discussion_detail_reading_flow_contract(self) -> None:
        for script_contract in (
            "enhanceDiscussionDetail",
            "data-ablecloud-reading-flow",
            "ablecloud-DiscussionDetailMeta",
            "ablecloud-solution-post",
            "해결 답변 보기",
            "scrollToSolution",
            "ablecloud-InlineReplyPrompt",
            "답변을 작성해 주세요",
            "enhanceLongTechnicalBlocks",
            "전체 로그 보기",
            "duplicateSolution.setAttribute('aria-hidden', 'true')",
        ):
            with self.subTest(script_contract=script_contract):
                self.assertIn(script_contract, self.forum_js)

        for style_contract in (
            ".App--index .WelcomeHero",
            ".App--discussion .DiscussionHero",
            ".App--discussion .DiscussionHero-title",
            ".ablecloud-DiscussionDetailMeta",
            ".ablecloud-SolutionJump",
            ".App--discussion .DiscussionPage-stream",
            ".App--discussion .PostStream-item",
            ".App--discussion .item-bestAnswerPost",
            ".ablecloud-InlineReplyPrompt",
            ".ablecloud-TechnicalBlock--collapsed",
            "native Flarum vertical navigator",
        ):
            with self.subTest(style_contract=style_contract):
                self.assertIn(style_contract, self.less)

        self.assertIn("display: none !important", self.less)
        self.assertIn("max-width: none", self.less)
        self.assertNotIn("max-width: 1165px", self.less)
        self.assertIn("padding-right: 80px", self.less)
        self.assertIn("scrollbar-gutter: stable", self.less)
        self.assertIn(".App--discussion .App-header > .container", self.less)
        self.assertIn("margin-top: 16px", self.less)
        self.assertIn(".App--discussion.hasPane .Header-title", self.less)
        self.assertIn("transform: translateX(-39px)", self.less)
        self.assertIn("justify-content: flex-start", self.less)

    def test_compact_hero_and_navigation_width_contract(self) -> None:
        self.assertIn("--ablecloud-page-inline-space: clamp(32px, 4vw, 80px)", self.less)
        self.assertIn("--ablecloud-page-edge-gutter: clamp(16px, 2vw, 40px)", self.less)
        self.assertIn("--ablecloud-page-rail-space: 80px", self.less)
        for shell_selector in (
            ".App-header > .container",
            ".WelcomeHero > .container",
            ".TagHero > .container",
            ".UserHero .container",
            ".TagsPage > .container",
            ".UserPage > .container",
        ):
            with self.subTest(shell_selector=shell_selector):
                self.assertIn(shell_selector, self.less)
        self.assertIn('width: ~"calc(100% - var(--ablecloud-page-inline-space))"', self.less)
        self.assertIn("max-width: none", self.less)
        self.assertIn("padding-right: var(--ablecloud-page-rail-space)", self.less)
        self.assertIn("Shared desktop shell", self.less)
        self.assertIn(".WelcomeHero .container", self.less)
        self.assertIn("font-size: 28px", self.less)
        self.assertIn("width: 280px", self.less)
        self.assertIn(".TagsPage-nav > ul", self.less)
        self.assertIn(".TagsPage-nav .Dropdown-menu", self.less)
        self.assertIn("justify-content: center", self.less)
        self.assertIn("bottom: 4px", self.less)
        self.assertIn(".TagTiles", self.less)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", self.less)
        self.assertIn("gap: 18px", self.less)
        self.assertIn(".TagTile-lastPostedDiscussion::before", self.less)
        self.assertIn('content: "최근 토론"', self.less)
        self.assertIn("border-top: 4px solid var(--tag-bg)", self.less)
        self.assertIn(".TagsPage-content > .TagCloud", self.less)
        self.assertIn("grid-column-start: 1", self.less)
        self.assertIn("grid-column-end: -1", self.less)
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", self.less)
        self.assertIn('content: "보조 태그 · 제품과 기능별 세부 토론"', self.less)
        self.assertIn("content: attr(title)", self.less)
        self.assertIn("border-left: 4px solid var(--tag-bg)", self.less)
        self.assertIn("width: 100%", self.less)
        self.assertIn("article.Post.Post--bestAnswer > div", self.less)
        self.assertIn("✓ 선택된 해결 답변", self.less)
        self.assertIn("@media (min-width: 768px)", self.less)
        self.assertIn("white-space: nowrap", self.less)
        self.assertIn("padding: 11px 64px 11px 52px", self.less)
        self.assertIn("padding-top: 19px", self.less)
        self.assertIn("padding-bottom: 19px", self.less)
        self.assertIn("padding: 17px 15px", self.less)
        self.assertIn("border-bottom: 0", self.less)
        self.assertIn(".PostStream-item:not(:last-child)", self.less)
        self.assertIn(".DiscussionListItem-author", self.less)
        self.assertIn("margin-top: 1px !important", self.less)
        self.assertIn(".DiscussionListItem-controls > .Dropdown-toggle", self.less)
        self.assertIn("border: 0", self.less)
        self.assertIn("background: transparent", self.less)
        self.assertIn("box-shadow: none", self.less)
        self.assertIn('.IndexPage-toolbar .Dropdown-menu .Button-icon:not([class*="fa-"])', self.less)
        self.assertIn("visibility: hidden", self.less)
        self.assertIn(".fa-bolt", self.less)
        self.assertIn(".DiscussionPage-list", self.less)
        self.assertIn(".DiscussionPage-list .ablecloud-DiscussionMeta", self.less)
        self.assertIn(".DiscussionPage-list .ablecloud-DiscussionMain--withThumbnail", self.less)
        self.assertIn("grid-template-columns: minmax(0, 1fr) 72px", self.less)
        self.assertIn(".DiscussionPage-list .ablecloud-DiscussionSummary", self.less)
        self.assertIn(".DiscussionPage-list .DiscussionListItem-count", self.less)
        self.assertIn("height: calc(100vh - 68px)", self.less)
        self.assertIn("scrollbar-width: thin", self.less)
        self.assertIn("html.ablecloud-composer-open .DiscussionPage-list", self.less)
        self.assertIn(".App.ablecloud-composer-open .DiscussionPage-list", self.less)
        self.assertIn(".App.hasPane.panePinned.ablecloud-composer-open .App-composer", self.less)
        self.assertIn(".DiscussionPage-list .DiscussionListItem-controls", self.less)
        self.assertIn("top: 10px", self.less)
        self.assertIn("width: 32px", self.less)
        self.assertIn(".Composer.active:not(.fullScreen)", self.less)
        self.assertIn("min-height: 336px", self.less)
        self.assertIn(".Composer.active:not(.fullScreen) .Composer-content", self.less)
        self.assertIn("height: 100% !important", self.less)
        self.assertIn(".Composer.active:not(.fullScreen) .ComposerBody-content", self.less)
        self.assertIn(".Composer.active:not(.fullScreen) .TextEditor", self.less)
        self.assertIn("display: flex", self.less)
        self.assertIn("flex-direction: column", self.less)
        self.assertIn("flex: 1 1 auto", self.less)
        self.assertIn(".Composer.active:not(.fullScreen) .TextEditor-editorContainer", self.less)
        self.assertIn(".Composer.active:not(.fullScreen) .TextEditor-controls", self.less)
        self.assertIn("position: static", self.less)
        self.assertIn("bottom: auto", self.less)
        self.assertIn("padding-bottom: 12px", self.less)
        self.assertIn("html.ablecloud-composer-open .DiscussionListItem:hover", self.less)
        self.assertIn("z-index: 0 !important", self.less)
        self.assertIn(".Search-input input:focus-visible", self.less)
        self.assertIn("outline: none !important", self.less)
        self.assertIn('.Header-secondary .Dropdown-menu .Button-icon:not([class*="fa-"])', self.less)
        self.assertIn(".Header-secondary .Dropdown-menu .Button-label", self.less)
        self.assertIn("position: static", self.less)
        self.assertIn("flex: 0 0 19px", self.less)
        self.assertIn("margin: 0", self.less)
        self.assertIn(".Header-secondary .item-locale .Dropdown-menu", self.less)
        self.assertIn("min-width: 180px", self.less)
        self.assertIn("padding: 10px 12px", self.less)
        self.assertIn("transform: none", self.less)
        self.assertIn('.Search-input input[type="search"]::-webkit-search-cancel-button', self.less)
        self.assertIn("-webkit-appearance: none", self.less)
        self.assertIn(".fa-times-circle", self.less)
        self.assertIn(".Search .Search-input::before", self.less)
        self.assertIn(".Search .Search-clear .fa-times-circle::before", self.less)
        self.assertIn(".Header-secondary .Search .Search-results", self.less)
        self.assertIn(".Search-results .SolutionSearchResult > a", self.less)
        self.assertIn("display: block !important", self.less)
        self.assertIn('width: ~"min(560px, calc(100vw - 24px))"', self.less)
        self.assertIn(".Search-results .SolutionSearchResult-tags .TagsLabel", self.less)
        self.assertIn(".Search-results .SolutionSearchResult-bestAnswer", self.less)
        self.assertIn("-webkit-line-clamp: 2", self.less)
        self.assertIn(".DiscussionListItem-count::before", self.less)
        self.assertIn(".DiscussionListItem.unread .DiscussionListItem-count:hover::before", self.less)
        self.assertIn(".Post-actions", self.less)
        self.assertIn("right: 0", self.less)
        self.assertIn(".Post-actions > ul > li", self.less)
        self.assertIn("gap: 8px", self.less)
        self.assertIn("width: auto", self.less)
        self.assertIn("top: auto", self.less)
        self.assertIn("bottom: -48px", self.less)
        self.assertIn("bottom: -52px", self.less)
        self.assertIn(".item-like .Button-label::before", self.less)
        self.assertIn(".item-bestAnswer .Button-label::before", self.less)
        self.assertIn('content: "더 보기"', self.less)
        self.assertIn(".fa-reply { --ablecloud-icon", self.less)
        self.assertIn('[aria-disabled="true"]', self.less)
        self.assertIn(":has(.Header-secondary .item-logIn)", self.less)
        self.assertIn(".App--index > .App-navigation", self.less)
        self.assertIn("display: none !important", self.less)
        self.assertNotIn(".App--index > .App-navigation .Navigation-drawer", self.less)
        self.assertIn(".App--index > .App-content", self.less)
        self.assertIn("html:has(body > .App--index)", self.less)
        self.assertIn("body:has(> .App--index)", self.less)
        self.assertIn(".App--index .IndexPage-results .DiscussionList", self.less)
        self.assertIn(".App--index .IndexPage-results .DiscussionList-discussions", self.less)
        self.assertIn("reserved rail sits immediately next", self.less)
        self.assertIn("Follow Reddit's flat feed composition", self.less)
        self.assertIn(".App--index .IndexPage-results::-webkit-scrollbar", self.less)
        self.assertIn(".App--index .IndexPage-nav::-webkit-scrollbar", self.less)
        self.assertIn("scrollbar-width: none", self.less)
        self.assertGreaterEqual(self.less.count("scrollbar-width: none"), 2)
        self.assertIn("overflow: visible", self.less)
        self.assertIn("flex: 0 0 auto", self.less)
        self.assertIn("background: rgba(21, 94, 239, 0.055)", self.less)
        self.assertIn("overscroll-behavior: contain", self.less)
        self.assertIn("position: fixed", self.less)
        self.assertIn("bottom: 0", self.less)
        self.assertNotIn("bottom: 56px", self.less)
        deploy_script = (ROOT / "deploy" / "flarum" / "apply-community-theme-update.sh").read_text(encoding="utf-8")
        self.assertIn('chown -R www-data:www-data "$extension_root"', deploy_script)
        self.assertIn('find "$extension_root" -type d -exec chmod 0755 {} +', deploy_script)
        self.assertIn(".UserHero .UserCard-profile", self.less)
        self.assertIn(".UserPage .UserPage-nav", self.less)
        self.assertIn(".UserPage .UserPage-content", self.less)
        self.assertIn(".UserPage .UserPage-nav > ul.affix", self.less)
        self.assertIn("width: 280px !important", self.less)
        self.assertIn("max-width: 280px", self.less)
        self.assertIn(".UserHero .UserCard-avatar", self.less)
        self.assertIn("position: absolute", self.less)
        self.assertIn("likes_link: 좋아요", self.korean)
        self.assertIn("media: 내 미디어", self.korean)
        self.assertIn("security_link: 보안", self.korean)
        self.assertIn("아직 작성한 게시물이 없습니다.", self.korean)
        self.assertIn("내 게시물이 해결 답변으로 선택되었을 때", self.korean)
        self.assertIn("참여한 토론에 해결 답변이 선택되었을 때", self.korean)
        self.assertIn("새 토큰", self.korean)
        self.assertIn("내가 속한 그룹이 게시물에서 언급되었을 때", self.korean)
        self.assertIn("토론의 마지막 게시물뿐 아니라 새 게시물이 등록될 때마다 알림", self.korean)
        self.assertIn("서식 편집기 사용", self.korean)
        self.assertIn("문단 사이의 빈 줄을 줄여서 표시", self.korean)
        self.assertIn("검색 정보 설정", self.korean)
        self.assertIn(".DiscussionListItem-controls", self.less)
        self.assertIn("z-index: 1080", self.less)
        self.assertIn("right: 58px", self.less)
        self.assertIn(".SettingsPage fieldset", self.less)
        self.assertIn(".UserSecurityPage fieldset", self.less)
        self.assertIn(".UserSecurityPage .LinkedAccountsList-item-icon", self.less)
        self.assertIn("flex: 0 0 28px", self.less)
        self.assertIn("overflow-x: auto", self.less)
        self.assertIn(".Composer.active", self.less)
        self.assertIn(".Modal .FormControl:focus-visible", self.less)
        self.assertIn(".Modal .Button--primary", self.less)
        self.assertIn(".Modal-close .Button:focus-visible", self.less)
        self.assertIn(".TagSelectionModal .TagsInput.FormControl.focus", self.less)
        self.assertIn(".TagSelectionModal-list > li.selected", self.less)
        self.assertIn("outline: none !important", self.less)
        self.assertIn("주 태그를 선택하세요", self.korean)
        self.assertIn("태그 필수 조건 무시", self.korean)
        self.assertIn("#console-nav-footer", self.less)
        self.assertIn("#footer-content .feedback-menu-left", self.less)
        self.assertIn("#footer-content .feedback-menu-left", self.less)
        self.assertIn("#floatright .feedback-menu-right:first-of-type", self.less)
        self.assertIn("#floatright .feedback-menu-right:last-of-type", self.less)
        self.assertIn("mask-image: var(--ablecloud-footer-icon)", self.less)
        self.assertIn("legacy footer bar is replaced with a fixed vertical quick-link rail", self.less)
        self.assertIn(".App--index .App-header > .container", self.less)
        self.assertIn(".App--index .WelcomeHero > .container", self.less)
        self.assertIn("Align the top navigation and welcome area", self.less)
        self.assertIn('right: ~"calc(var(--ablecloud-page-edge-gutter) + 16px)"', self.less)
        self.assertIn("flex-direction: column", self.less)
        self.assertIn('width: ~"calc(100% - var(--ablecloud-page-inline-space))"', self.less)
        self.assertIn("padding-right: 80px", self.less)
        self.assertIn("transform: translateY(-50%)", self.less)
        self.assertIn("bottom: 16px", self.less)

    def test_rehearsal_is_staging_only_and_preserves_content(self) -> None:
        self.assertIn('APP_ROOT" == "/srv/techflow-flarum-staging/app"', self.rehearsal)
        self.assertIn("productionChanged", self.rehearsal)
        self.assertIn("compare_integrity", self.rehearsal)
        self.assertIn("uploads_sha256", self.rehearsal)
        self.assertIn("storage/locale", self.rehearsal)
        self.assertIn("core.forum.header.search_placeholder", self.rehearsal)
        self.assertIn("warm-korean-locale.php", self.rehearsal)
        self.assertIn('TECHFLOW_THEME_EXPECTED="$theme_expected"', self.rehearsal)
        locale_warmer = (THEME / "tools" / "warm-korean-locale.php").read_text(encoding="utf-8")
        self.assertIn("core.forum.user.security_link", locale_warmer)
        self.assertIn("flarum-likes.forum.user.likes_link", locale_warmer)
        self.assertIn("fof-upload.forum.buttons.media", locale_warmer)
        self.assertIn("fof-best-answer.forum.this_best_answer", locale_warmer)
        self.assertIn("fof-best-answer.forum.remove_best_answer", locale_warmer)
        self.assertIn("fof-oauth.forum.user.settings.linked-account.label", locale_warmer)
        self.assertIn("fof-oauth.forum.unlink", locale_warmer)

    def test_production_theme_update_is_path_scoped(self) -> None:
        updater = (
            ROOT / "deploy" / "flarum" / "apply-community-theme-update.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('/var/www/html/extensions/ablecloud-community-theme', updater)
        self.assertIn('/tmp/ablecloud-community-theme-*', updater)
        self.assertIn('/var/backups/techflow-flarum/theme-*', updater)
        self.assertIn('rsync -a --delete "$source_root/" "$extension_root/"', updater)
        self.assertIn("UserPage-nav > ul.affix", updater)
        self.assertIn("RESULT=PASS", updater)


if __name__ == "__main__":
    unittest.main()
