(function () {
  'use strict';

  var forumAppModule = flarum.core.compat['forum/app'];
  var forumApp = forumAppModule.default || forumAppModule;
  var relativeDatePattern = /(?:방금|전$|후$)/;
  var absoluteDatePattern = /^(\d{4})-(\d{2})-(\d{2})/;
  var discussionItemEnhancedAttribute = 'data-ablecloud-post-structure';
  var discussionDetailEnhancedAttribute = 'data-ablecloud-reading-flow';
  var discussionListSnapshotKey = 'ablecloud-community-discussion-list';
  var fallbackPaneAttribute = 'data-ablecloud-fallback-pane';
  var fallbackPaneActive = false;
  var infiniteLoadObserver = null;
  var infiniteLoadTarget = null;
  var emojiPalette = null;
  var emojiPaletteTrigger = null;
  var emojiSelectionRange = null;
  var discussionTopPath = null;
  var discussionTopTimers = [];
  var discussionTopRouteKey = 'ablecloud-community-discussion-top-route';
  var commonEmojis = [
    ['😀', '웃는 얼굴'],
    ['😃', '활짝 웃는 얼굴'],
    ['😊', '미소'],
    ['😂', '기쁨의 눈물'],
    ['🙂', '살짝 미소'],
    ['😉', '윙크'],
    ['😍', '반함'],
    ['🤔', '생각 중'],
    ['😮', '놀람'],
    ['😢', '슬픔'],
    ['😭', '울음'],
    ['😅', '안도'],
    ['😎', '멋짐'],
    ['👍', '좋아요'],
    ['👎', '싫어요'],
    ['👏', '박수'],
    ['🙏', '부탁과 감사'],
    ['✅', '확인'],
    ['❗', '중요'],
    ['⚠️', '주의'],
    ['💡', '아이디어'],
    ['🎉', '축하'],
    ['❤️', '하트'],
    ['🔥', '불꽃'],
  ];

  function disconnectInfiniteDiscussionLoading() {
    if (infiniteLoadObserver) {
      infiniteLoadObserver.disconnect();
    }

    infiniteLoadObserver = null;
    infiniteLoadTarget = null;
  }

  function enhanceInfiniteDiscussionLoading(root) {
    var scrollRoot = root.querySelector('.App--index .IndexPage-results');
    var loadMore = root.querySelector('.App--index .DiscussionList-loadMore');
    var button = loadMore && loadMore.querySelector('button');

    if (!scrollRoot || !loadMore || !button || typeof window.IntersectionObserver !== 'function') {
      disconnectInfiniteDiscussionLoading();
      return;
    }

    if (loadMore.getAttribute('data-ablecloud-auto-load') !== 'true') {
      loadMore.setAttribute('data-ablecloud-auto-load', 'true');
    }

    if (infiniteLoadTarget === loadMore) {
      return;
    }

    disconnectInfiniteDiscussionLoading();
    infiniteLoadTarget = loadMore;
    infiniteLoadObserver = new window.IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          var currentButton = entry.target.querySelector('button');

          if (
            !entry.isIntersecting ||
            !currentButton ||
            currentButton.disabled ||
            entry.target.getAttribute('data-ablecloud-loading') === 'true'
          ) {
            return;
          }

          entry.target.setAttribute('data-ablecloud-loading', 'true');
          currentButton.click();

          window.setTimeout(function () {
            if (entry.target.isConnected) {
              entry.target.removeAttribute('data-ablecloud-loading');
            }
          }, 750);
        });
      },
      {
        root: scrollRoot,
        rootMargin: '0px 0px 120px 0px',
        threshold: 0.01,
      }
    );
    infiniteLoadObserver.observe(loadMore);
  }

  function closeEmojiPalette() {
    if (emojiPalette && emojiPalette.parentNode) {
      emojiPalette.parentNode.removeChild(emojiPalette);
    }

    if (emojiPaletteTrigger) {
      emojiPaletteTrigger.setAttribute('aria-expanded', 'false');
    }

    emojiPalette = null;
    emojiPaletteTrigger = null;
    emojiSelectionRange = null;
  }

  function rememberEmojiCaret(editor) {
    var selection = window.getSelection();

    if (selection && selection.rangeCount) {
      var range = selection.getRangeAt(0);

      if (editor.contains(range.commonAncestorContainer)) {
        return range.cloneRange();
      }
    }

    var fallbackRange = document.createRange();
    fallbackRange.selectNodeContents(editor);
    fallbackRange.collapse(false);
    return fallbackRange;
  }

  function insertEmojiAtCaret(editor, emoji) {
    if (!editor || !emoji) {
      return;
    }

    var selection = window.getSelection();
    var range = emojiSelectionRange && emojiSelectionRange.startContainer.isConnected
      ? emojiSelectionRange
      : rememberEmojiCaret(editor);

    editor.focus();

    if (selection) {
      selection.removeAllRanges();
      selection.addRange(range);
    }

    var value = emoji + ' ';
    var inserted = false;

    try {
      inserted = document.execCommand('insertText', false, value);
    } catch (error) {
      inserted = false;
    }

    if (!inserted) {
      range.deleteContents();
      var textNode = document.createTextNode(value);
      range.insertNode(textNode);
      range.setStartAfter(textNode);
      range.collapse(true);
      if (selection) {
        selection.removeAllRanges();
        selection.addRange(range);
      }
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  function openEmojiPalette(trigger) {
    var composer = trigger.closest('.Composer');
    var editor = composer && composer.querySelector('.TextEditor-editor[contenteditable="true"]');

    if (!composer || !editor) {
      return;
    }

    closeEmojiPalette();
    document.querySelectorAll('.EmojiDropdown').forEach(function (dropdown) {
      dropdown.remove();
    });

    emojiSelectionRange = rememberEmojiCaret(editor);
    emojiPaletteTrigger = trigger;
    trigger.setAttribute('aria-expanded', 'true');

    var palette = document.createElement('div');
    palette.className = 'ablecloud-EmojiPicker';
    palette.setAttribute('role', 'dialog');
    palette.setAttribute('aria-label', '이모지 선택');

    var header = document.createElement('div');
    header.className = 'ablecloud-EmojiPicker-header';

    var title = document.createElement('strong');
    title.textContent = '이모지 선택';
    header.appendChild(title);

    var closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'ablecloud-EmojiPicker-close';
    closeButton.setAttribute('data-ablecloud-emoji-close', 'true');
    closeButton.setAttribute('aria-label', '이모지 선택창 닫기');
    closeButton.textContent = '×';
    header.appendChild(closeButton);
    palette.appendChild(header);

    var help = document.createElement('p');
    help.className = 'ablecloud-EmojiPicker-help';
    help.textContent = '삽입할 이모지를 선택하세요.';
    palette.appendChild(help);

    var grid = document.createElement('div');
    grid.className = 'ablecloud-EmojiPicker-grid';

    commonEmojis.forEach(function (item) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'ablecloud-EmojiPicker-option';
      button.setAttribute('data-ablecloud-emoji', item[0]);
      button.setAttribute('aria-label', item[1]);
      button.title = item[1];
      button.textContent = item[0];
      grid.appendChild(button);
    });

    palette.appendChild(grid);
    composer.appendChild(palette);
    emojiPalette = palette;
  }

  function handleEmojiPaletteClick(event) {
    var trigger = event.target.closest && event.target.closest('.Composer button[aria-label="이모지 삽입"]');

    if (trigger) {
      event.preventDefault();
      event.stopImmediatePropagation();

      if (emojiPalette) {
        closeEmojiPalette();
      } else {
        openEmojiPalette(trigger);
      }

      return;
    }

    var choice = event.target.closest && event.target.closest('[data-ablecloud-emoji]');

    if (choice && emojiPalette && emojiPalette.contains(choice)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      var editor = emojiPalette.closest('.Composer').querySelector('.TextEditor-editor[contenteditable="true"]');
      insertEmojiAtCaret(editor, choice.getAttribute('data-ablecloud-emoji'));
      closeEmojiPalette();
      return;
    }

    if (event.target.closest && event.target.closest('[data-ablecloud-emoji-close="true"]')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      closeEmojiPalette();
      return;
    }

    if (emojiPalette && !emojiPalette.contains(event.target)) {
      closeEmojiPalette();
    }
  }

  function handleEmojiPaletteKeydown(event) {
    if (event.key === 'Escape' && emojiPalette) {
      event.preventDefault();
      closeEmojiPalette();
    }
  }

  function formatDiscussionCreatedAt(createdAt) {
    if (!(createdAt instanceof Date) || Number.isNaN(createdAt.getTime())) {
      return '';
    }

    var elapsed = Math.max(0, Date.now() - createdAt.getTime());
    var minute = 60 * 1000;
    var hour = 60 * minute;
    var day = 24 * hour;

    if (elapsed < minute) {
      return '방금';
    }

    if (elapsed < hour) {
      return Math.floor(elapsed / minute) + '분 전';
    }

    if (elapsed < day) {
      return Math.floor(elapsed / hour) + '시간 전';
    }

    if (elapsed < 7 * day) {
      return Math.floor(elapsed / day) + '일 전';
    }

    return String(createdAt.getFullYear()).slice(-2) + '년 ' + (createdAt.getMonth() + 1) + '월 ' + createdAt.getDate() + '일';
  }

  function appendMetaPart(meta, className, text) {
    if (!text) {
      return;
    }

    if (meta.childElementCount) {
      var separator = document.createElement('span');
      separator.className = 'ablecloud-DiscussionMeta-separator';
      separator.setAttribute('aria-hidden', 'true');
      separator.textContent = '·';
      meta.appendChild(separator);
    }

    var part = document.createElement('span');
    part.className = className;
    part.textContent = text;
    meta.appendChild(part);
  }

  function buildDiscussionSummary(discussion) {
    var firstPost = discussion && typeof discussion.firstPost === 'function' ? discussion.firstPost() : null;

    if (!firstPost || typeof firstPost.contentPlain !== 'function') {
      return '';
    }

    return String(firstPost.contentPlain() || '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function findDiscussionThumbnail(discussion) {
    var firstPost = discussion && typeof discussion.firstPost === 'function' ? discussion.firstPost() : null;
    var contentHtml = firstPost && typeof firstPost.contentHtml === 'function' ? firstPost.contentHtml() : '';

    if (!contentHtml) {
      return null;
    }

    var template = document.createElement('template');
    template.innerHTML = String(contentHtml);
    var sourceImage = template.content.querySelector('img[src]');

    if (!sourceImage) {
      return null;
    }

    var resolvedUrl;

    try {
      resolvedUrl = new URL(sourceImage.getAttribute('src'), window.location.origin);
    } catch (error) {
      return null;
    }

    if (!['http:', 'https:'].includes(resolvedUrl.protocol)) {
      return null;
    }

    return {
      src: resolvedUrl.href,
      alt: sourceImage.getAttribute('alt') || sourceImage.getAttribute('title') || '게시물 첨부 이미지 미리보기',
    };
  }

  function enhanceDiscussionListItems(root) {
    root.querySelectorAll('.DiscussionList-discussions > li[data-id]').forEach(function (listItem) {
      if (listItem.getAttribute(discussionItemEnhancedAttribute) === 'true') {
        return;
      }

      var discussion = forumApp.store.getById('discussions', listItem.getAttribute('data-id'));
      var content = listItem.querySelector('.DiscussionListItem-content');
      var main = content && content.querySelector('.DiscussionListItem-main');
      var title = main && main.querySelector('.DiscussionListItem-title');

      if (!discussion || !content || !main || !title) {
        return;
      }

      var user = typeof discussion.user === 'function' ? discussion.user() : null;
      var author = user && typeof user.displayName === 'function' ? user.displayName() : '';
      var category = main.querySelector('.TagLabel-name');
      var meta = document.createElement('div');
      meta.className = 'ablecloud-DiscussionMeta';
      meta.setAttribute('aria-label', '토론 작성 정보');
      appendMetaPart(meta, 'ablecloud-DiscussionMeta-category', category && category.textContent.trim());
      appendMetaPart(meta, 'ablecloud-DiscussionMeta-author', author);
      appendMetaPart(
        meta,
        'ablecloud-DiscussionMeta-time',
        formatDiscussionCreatedAt(typeof discussion.createdAt === 'function' ? discussion.createdAt() : null)
      );
      content.insertBefore(meta, main);

      var summaryText = buildDiscussionSummary(discussion);

      if (summaryText) {
        var summary = document.createElement('p');
        summary.className = 'ablecloud-DiscussionSummary';
        summary.textContent = summaryText;
        title.insertAdjacentElement('afterend', summary);
      }

      var thumbnail = findDiscussionThumbnail(discussion);

      if (thumbnail) {
        var thumbnailFrame = document.createElement('span');
        var thumbnailImage = document.createElement('img');
        thumbnailFrame.className = 'ablecloud-DiscussionThumbnail';
        thumbnailFrame.setAttribute('aria-hidden', 'true');
        thumbnailImage.src = thumbnail.src;
        thumbnailImage.alt = thumbnail.alt;
        thumbnailImage.loading = 'lazy';
        thumbnailImage.decoding = 'async';
        thumbnailFrame.appendChild(thumbnailImage);
        main.appendChild(thumbnailFrame);
        main.classList.add('ablecloud-DiscussionMain--withThumbnail');
      }

      var badges = content.querySelector('.DiscussionListItem-badges');

      if (badges && badges.querySelector('.item-bestAnswer')) {
        badges.setAttribute('aria-label', '해결된 토론');
      }

      listItem.setAttribute(discussionItemEnhancedAttribute, 'true');
    });
  }

  function createDetailMetaPart(className, text, href) {
    var part = href ? document.createElement('a') : document.createElement('span');
    part.className = className;
    part.textContent = text;

    if (href) {
      part.href = href;
    }

    return part;
  }

  function scrollToSolution(event) {
    var solution = document.getElementById('ablecloud-solution-post');

    if (!solution) {
      return;
    }

    event.preventDefault();
    solution.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      block: 'start',
    });
  }

  function enhanceLongTechnicalBlocks(root) {
    root.querySelectorAll('.App--discussion .Post-body pre').forEach(function (block) {
      if (block.getAttribute('data-ablecloud-log-block') === 'true' || block.scrollHeight <= 480) {
        return;
      }

      block.setAttribute('data-ablecloud-log-block', 'true');
      block.classList.add('ablecloud-TechnicalBlock--collapsed');

      var toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'Button ablecloud-TechnicalBlock-toggle';
      toggle.setAttribute('aria-expanded', 'false');
      toggle.textContent = '전체 로그 보기';
      toggle.addEventListener('click', function () {
        var expanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!expanded));
        toggle.textContent = expanded ? '전체 로그 보기' : '로그 접기';
        block.classList.toggle('ablecloud-TechnicalBlock--collapsed', expanded);
      });
      block.insertAdjacentElement('afterend', toggle);
    });
  }

  function enhanceDiscussionDetail(root) {
    var page = root.querySelector('.App--discussion .DiscussionPage');
    var hero = root.querySelector('.App--discussion .DiscussionHero');
    var stream = page && page.querySelector('.PostStream');
    var firstItem = stream && stream.querySelector('.PostStream-item[data-number="1"]');
    var firstPost = firstItem && firstItem.querySelector('article.Post');

    if (!page || !hero || !stream || !firstPost) {
      return;
    }

    var solutionPost = stream.querySelector('article.Post.Post--bestAnswer');
    var solutionItem = solutionPost && solutionPost.closest('.PostStream-item');

    if (solutionItem) {
      solutionItem.id = 'ablecloud-solution-post';
    }

    if (hero.getAttribute(discussionDetailEnhancedAttribute) !== 'true') {
      var heroItems = hero.querySelector('.DiscussionHero-items');
      var authorLink = firstPost.querySelector('.PostUser-name a');
      var authorName = firstPost.querySelector('.PostUser-name .username');
      var publishedAt = firstPost.querySelector('.PostMeta time');
      var meta = document.createElement('li');
      meta.className = 'item-ablecloudMeta ablecloud-DiscussionDetailMeta';
      meta.setAttribute('aria-label', '토론 작성 정보');

      if (authorName) {
        meta.appendChild(
          createDetailMetaPart(
            'ablecloud-DiscussionDetailMeta-author',
            authorName.textContent.trim(),
            authorLink && authorLink.getAttribute('href')
          )
        );
      }

      if (publishedAt) {
        meta.appendChild(createDetailMetaPart('ablecloud-DiscussionDetailMeta-separator', '·'));
        meta.appendChild(createDetailMetaPart('ablecloud-DiscussionDetailMeta-time', publishedAt.textContent.trim()));
      }

      if (solutionItem) {
        var solutionLink = createDetailMetaPart('ablecloud-SolutionJump', '해결 답변 보기', '#ablecloud-solution-post');
        solutionLink.addEventListener('click', scrollToSolution);
        meta.appendChild(solutionLink);
      }

      if (heroItems) {
        heroItems.appendChild(meta);
      }

      var solvedBadge = hero.querySelector('.Badge--bestAnswer');

      if (solvedBadge) {
        solvedBadge.setAttribute('aria-label', '해결됨');
      }

      hero.setAttribute(discussionDetailEnhancedAttribute, 'true');
    }

    var duplicateSolution = firstPost.querySelector('.item-bestAnswerPost');

    if (duplicateSolution) {
      duplicateSolution.setAttribute('aria-hidden', 'true');
    }

    if (!firstItem.querySelector('.ablecloud-InlineReplyPrompt')) {
      var nativeReply = page.querySelector('.DiscussionPage-nav .item-controls .SplitDropdown-button');

      if (nativeReply) {
        var replyPrompt = document.createElement('div');
        var replyButton = document.createElement('button');
        replyPrompt.className = 'ablecloud-InlineReplyPrompt';
        replyButton.type = 'button';
        replyButton.className = 'Button ablecloud-InlineReplyPrompt-button';
        replyButton.textContent = '답변을 작성해 주세요';
        replyButton.addEventListener('click', function () {
          nativeReply.click();
        });
        replyPrompt.appendChild(replyButton);
        firstPost.insertAdjacentElement('afterend', replyPrompt);
      }
    }

    enhanceLongTechnicalBlocks(root);
  }

  function formatTagDiscussionDates(root) {
    root.querySelectorAll('.TagTile-lastPostedDiscussion time[datetime]').forEach(function (time) {
      var current = time.textContent.trim();

      if (relativeDatePattern.test(current)) {
        return;
      }

      var matched = (time.getAttribute('datetime') || '').match(absoluteDatePattern);

      if (!matched) {
        return;
      }

      var formatted = matched[1].slice(-2) + '년 ' + Number(matched[2]) + '월 ' + Number(matched[3]) + '일';

      if (current !== formatted) {
        time.textContent = formatted;
      }
    });
  }

  function normalizeDiscussionListTargets(root) {
    root.querySelectorAll('.DiscussionListItem-main[href]').forEach(function (link) {
      var url = new URL(link.getAttribute('href'), window.location.origin);
      var canonicalPath = url.pathname.replace(/(\/d\/[^/]+)\/\d+\/?$/, '$1');

      if (/^\/d\/[^/]+\/?$/.test(canonicalPath)) {
        link.setAttribute('href', canonicalPath.replace(/\/$/, '') + '/1' + url.search);
      }

      link.setAttribute('data-ablecloud-start-from-top', 'true');
    });
  }

  function ensureDiscussionFirstPostRoute(root) {
    if (!root.querySelector('.App--discussion .DiscussionPage')) {
      discussionTopPath = null;
      try {
        window.sessionStorage.removeItem(discussionTopRouteKey);
      } catch (error) {
        // The first-post route still works for list links without session storage.
      }
      return false;
    }

    var matched = window.location.pathname.match(/^(\/d\/[^/]+)(?:\/\d+)?\/?$/);

    if (!matched) {
      return false;
    }

    var firstPostPath = matched[1] + '/1';
    var handledPath = '';

    try {
      handledPath = window.sessionStorage.getItem(discussionTopRouteKey) || '';
    } catch (error) {
      handledPath = '';
    }

    if (window.location.pathname.replace(/\/$/, '') === firstPostPath) {
      try {
        window.sessionStorage.setItem(discussionTopRouteKey, matched[1]);
      } catch (error) {
        // Continue with the explicit /1 route.
      }
      return false;
    }

    if (handledPath === matched[1]) {
      return false;
    }

    try {
      window.sessionStorage.setItem(discussionTopRouteKey, matched[1]);
    } catch (error) {
      // A single hard navigation still provides the first-post route.
    }

    window.location.replace(firstPostPath + window.location.search);
    return true;
  }

  function keepDiscussionAtTop(root) {
    var page = root.querySelector('.App--discussion .DiscussionPage');
    var currentPath = window.location.pathname.replace(/\/$/, '');

    if (!page || !/\/d\/[^/]+\/1$/.test(currentPath) || discussionTopPath === currentPath) {
      return;
    }

    discussionTopTimers.forEach(window.clearTimeout);
    discussionTopTimers = [];
    discussionTopPath = currentPath;

    [0, 80, 250, 600, 1200].forEach(function (delay) {
      discussionTopTimers.push(window.setTimeout(function () {
        if (window.location.pathname.replace(/\/$/, '') !== currentPath) {
          return;
        }

        window.scrollTo(0, 0);
        document.documentElement.scrollTop = 0;
        document.body.scrollTop = 0;
        var stream = document.querySelector('.App--discussion .DiscussionPage-stream');

        if (stream) {
          stream.scrollTop = 0;
        }
      }, delay));
    });
  }

  function openDiscussionFromTop(event) {
    var link = event.target.closest && event.target.closest('.DiscussionListItem-main[data-ablecloud-start-from-top="true"]');

    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }

    window.requestAnimationFrame(function () {
      window.scrollTo(0, 0);
    });

    window.setTimeout(function () {
      window.scrollTo(0, 0);
    }, 120);
  }

  function captureDiscussionListSnapshot(root) {
    var list = root.querySelector('.App--index .DiscussionList');

    if (!list) {
      return;
    }

    try {
      window.sessionStorage.setItem(discussionListSnapshotKey, list.outerHTML);
    } catch (error) {
      // A browser with disabled session storage can still use the normal back link.
    }
  }

  function markCurrentDiscussionInPane(pane) {
    var currentPath = window.location.pathname.replace(/\/$/, '').replace(/(\/d\/[^/]+)\/\d+$/, '$1');

    pane.querySelectorAll('.DiscussionListItem').forEach(function (item) {
      var link = item.querySelector('.DiscussionListItem-main[href]');
      var active = false;

      if (link) {
        try {
          active = new URL(link.getAttribute('href'), window.location.origin).pathname.replace(/\/$/, '') === currentPath;
        } catch (error) {
          active = false;
        }
      }

      item.classList.toggle('active', active);
    });
  }

  function ensureFallbackDiscussionPane(root) {
    var page = root.querySelector('.App--discussion .DiscussionPage');

    if (!page) {
      if (fallbackPaneActive && forumApp.pane) {
        forumApp.pane.disable();
      }

      fallbackPaneActive = false;
      return;
    }

    var nativePane = page.querySelector('.DiscussionPage-list:not([' + fallbackPaneAttribute + '="true"])');

    if (nativePane) {
      return;
    }

    if (page.querySelector('.DiscussionPage-list[' + fallbackPaneAttribute + '="true"]')) {
      return;
    }

    var snapshot = '';

    try {
      snapshot = window.sessionStorage.getItem(discussionListSnapshotKey) || '';
    } catch (error) {
      snapshot = '';
    }

    if (!snapshot) {
      return;
    }

    var template = document.createElement('template');
    template.innerHTML = snapshot;
    var list = template.content.querySelector('.DiscussionList');

    if (!list) {
      return;
    }

    var pane = document.createElement('aside');
    pane.className = 'DiscussionPage-list ablecloud-DiscussionPage-list--fallback';
    pane.setAttribute(fallbackPaneAttribute, 'true');
    pane.setAttribute('aria-label', '최근 토론 목록');
    pane.appendChild(list);
    markCurrentDiscussionInPane(pane);
    page.insertBefore(pane, page.firstChild);

    if (forumApp.pane) {
      forumApp.pane.enable();
      forumApp.pane.hide();
      pane.addEventListener('mouseenter', forumApp.pane.show.bind(forumApp.pane));
      pane.addEventListener('mouseleave', forumApp.pane.onmouseleave.bind(forumApp.pane));
    }

    fallbackPaneActive = true;
  }

  function syncComposerPaneState(root) {
    var app = root.querySelector('.App') || document.querySelector('.App');
    var composerOpen = Boolean(document.querySelector('.Composer.visible:not(.minimized)'));
    var newDiscussionOpen = Boolean(
      document.querySelector('.Composer.visible:not(.minimized) .ComposerBody--discussion')
    );

    document.documentElement.classList.toggle('ablecloud-composer-open', composerOpen);
    document.documentElement.classList.toggle('ablecloud-new-discussion-open', newDiscussionOpen);
    document.body.classList.toggle('ablecloud-composer-open', composerOpen);
    document.body.classList.toggle('ablecloud-new-discussion-open', newDiscussionOpen);

    if (!app) {
      return composerOpen;
    }

    app.classList.toggle('ablecloud-composer-open', composerOpen);
    app.classList.toggle('ablecloud-new-discussion-open', newDiscussionOpen);

    if (!composerOpen) {
      closeEmojiPalette();
    }

    if (composerOpen && forumApp.pane) {
      forumApp.pane.hide();
    }

    return composerOpen;
  }

  function syncMobileNavigationState(root) {
    var app = root.querySelector('.App') || document.querySelector('.App');
    var toggle = root.querySelector('.Navigation-drawer') || document.querySelector('.Navigation-drawer');

    if (!app || !toggle) {
      return;
    }

    var open = app.classList.contains('drawerOpen');
    toggle.setAttribute('aria-label', open ? '탐색 서랍 닫기' : '탐색 서랍 열기');
    toggle.setAttribute('title', open ? '메뉴 닫기' : '메뉴 열기');

    if (!open) {
      root.querySelectorAll('.drawer-backdrop').forEach(function (backdrop) {
        backdrop.remove();
      });
    }
  }

  function handleMobileOverlayKeydown(event) {
    if (event.key !== 'Escape') {
      return;
    }

    var app = document.querySelector('.App.drawerOpen');
    var drawerToggle = app && document.querySelector('.Navigation-drawer');

    if (drawerToggle) {
      event.preventDefault();
      drawerToggle.click();
    }
  }

  function closeMobileNavigation(event) {
    var app = document.querySelector('.App.drawerOpen');

    if (!app) {
      return false;
    }

    if (event) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }

    app.classList.remove('drawerOpen');
    document.querySelectorAll('.drawer-backdrop').forEach(function (backdrop) {
      backdrop.remove();
    });
    syncMobileNavigationState(document);
    return true;
  }

  function handleMobileNavigationClick(event) {
    var toggle = event.target.closest && event.target.closest('.Navigation-drawer');
    var backdrop = event.target.closest && event.target.closest('.drawer-backdrop');

    if ((toggle || backdrop) && document.querySelector('.App.drawerOpen')) {
      closeMobileNavigation(event);
    }
  }

  function handleMobileComposerCloseClick(event) {
    var closeButton = event.target.closest && event.target.closest('.Composer-controls .item-close button');

    if (!closeButton || !document.body.classList.contains('ablecloud-composer-open')) {
      return;
    }

    event.preventDefault();
    event.stopImmediatePropagation();
    var title = document.querySelector('.Composer input[placeholder="토의 제목"]');
    var editor = document.querySelector('.Composer .TextEditor-editor');
    var hasContent = Boolean(
      (title && title.value.trim()) ||
      (editor && editor.textContent.trim())
    );

    if (hasContent && !window.confirm('작성 중인 내용을 취소하고 대화상자를 닫으시겠습니까?')) {
      return;
    }

    forumApp.composer.hide();
    window.setTimeout(function () {
      syncComposerPaneState(document);
    }, 0);
  }

  function showFallbackPaneFromEdge(event) {
    var composerOpen = syncComposerPaneState(document);

    if (composerOpen) {
      return;
    }

    if (
      fallbackPaneActive &&
      forumApp.pane &&
      event.clientX < 10
    ) {
      forumApp.pane.show();
    }
  }

  forumApp.initializers.add('ablecloud-community-theme-tag-date', function () {
    if ('scrollRestoration' in window.history) {
      window.history.scrollRestoration = 'manual';
    }

    var pendingFrame = 0;
    var schedule = function () {
      window.cancelAnimationFrame(pendingFrame);
      pendingFrame = window.requestAnimationFrame(function () {
        formatTagDiscussionDates(document);
        normalizeDiscussionListTargets(document);
        enhanceDiscussionListItems(document);
        enhanceInfiniteDiscussionLoading(document);
        captureDiscussionListSnapshot(document);
        ensureFallbackDiscussionPane(document);
        syncComposerPaneState(document);
        syncMobileNavigationState(document);
        if (ensureDiscussionFirstPostRoute(document)) {
          return;
        }
        enhanceDiscussionDetail(document);
        keepDiscussionAtTop(document);
      });
    };

    schedule();

    new MutationObserver(schedule).observe(document.body, {
      attributes: true,
      attributeFilter: ['class'],
      childList: true,
      characterData: true,
      subtree: true,
    });

    document.addEventListener('click', function () {
      window.setTimeout(schedule, 0);
      window.setTimeout(schedule, 150);
      window.setTimeout(schedule, 600);
    }, true);
    document.addEventListener('click', openDiscussionFromTop, true);
    document.addEventListener('click', handleMobileNavigationClick, true);
    document.addEventListener('click', handleMobileComposerCloseClick, true);
    document.addEventListener('click', handleEmojiPaletteClick, true);
    document.addEventListener('keydown', handleEmojiPaletteKeydown, true);
    document.addEventListener('keydown', handleMobileOverlayKeydown, true);
    document.addEventListener('mousemove', showFallbackPaneFromEdge, { passive: true });
  });

  module.exports = {};
})();
