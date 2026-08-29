# ABLESTACK Community Theme 적용 및 롤백 Runbook

## 1. 목적과 경계

`ablecloud/community-theme`을 Flarum 1.8.18에 설치하고 검증하는 절차다. 테마는 화면 CSS와 한글 상태 표시만 제공하며 Core, Vendor 원본, DB Schema와 Community 콘텐츠를 수정하지 않는다.

WSL 검증은 `/srv/techflow-flarum-staging/app`만 허용한다. 운영 경로 `/var/www/html` 적용은 별도 승인 후에만 수행한다.

## 2. WSL 예행연습

저장소 자산을 WSL ext4 영역에 복사한 뒤 전체 주기를 실행한다.

```bash
sudo install -d -m 0755 /srv/techflow-flarum-staging/sources/ablecloud-community-theme
sudo rsync -a --delete \
  deploy/flarum/extensions/ablecloud-community-theme/ \
  /srv/techflow-flarum-staging/sources/ablecloud-community-theme/

sudo TECHFLOW_THEME_SOURCE=/srv/techflow-flarum-staging/sources/ablecloud-community-theme \
  bash deploy/flarum/rehearse-community-theme.sh cycle issue73-review
```

주기는 기본 상태 기록, 활성화, 기능 검증, 비활성화 롤백, 콘텐츠 무결성 비교, 재활성화를 순서대로 수행한다. 결과는 `/srv/techflow-flarum-staging/rehearsals/issue-73/<run-id>/result.json`에 남는다.

## 3. 운영 적용 전 점검

- Flarum Core가 1.8.18인지 확인한다.
- DB, `/var/www/html`, Nginx·PHP-FPM 설정을 `/var/backups/techflow-flarum/issue73-<UTC>`에 백업한다.
- `composer.json`, `composer.lock`, `settings.extensions_enabled`를 별도 보관한다.
- `https://community.ablecloud.io` HTTP 200, 로그인, 검색, 작성, 첨부의 기존 기준선을 기록한다.
- TechFlow Community Poller 상태와 GitHub→Chat 보호 서비스 상태를 기록한다.

## 4. 운영 적용 절차

승인된 변경 창에서만 다음 명령을 사용한다. 비밀번호와 API Key는 필요하지 않다.

```bash
sudo install -d -o www-data -g www-data -m 0755 \
  /var/www/html/extensions/ablecloud-community-theme
sudo rsync -a --delete \
  deploy/flarum/extensions/ablecloud-community-theme/ \
  /var/www/html/extensions/ablecloud-community-theme/

cd /var/www/html
sudo -u www-data env COMPOSER_HOME=/tmp/techflow-composer \
  composer config repositories.ablecloud-community-theme path \
  /var/www/html/extensions/ablecloud-community-theme
sudo -u www-data env COMPOSER_HOME=/tmp/techflow-composer \
  composer require ablecloud/community-theme:@dev --with-dependencies --no-interaction
sudo -u www-data php flarum extension:enable ablecloud-community-theme
sudo -u www-data php flarum cache:clear
sudo -u www-data env TECHFLOW_ALLOWED_FLARUM_ROOT=/var/www/html \
  php vendor/ablecloud/community-theme/tools/warm-korean-locale.php /var/www/html
sudo systemctl restart php8.3-fpm nginx
```

이미 설치된 테마의 CSS·Locale·JS만 갱신할 때는 변경 자산을
`/tmp/ablecloud-community-theme-<id>`에 전송한 뒤 경로 제한 배포기를 사용한다.
배포기는 현재 Extension·Vendor·Composer·컴파일 자산·Locale을
`/var/backups/techflow-flarum/theme-<id>`에 먼저 백업하고, 적용 후 서비스와
컴파일 CSS를 검증한다.

```bash
sudo bash deploy/flarum/apply-community-theme-update.sh \
  /tmp/ablecloud-community-theme-<id> \
  theme-<id>
```

## 5. 적용 후 검증

- 외부 HTTPS와 서버 로컬 Host/HTTPS 전달 헤더 점검이 모두 200이어야 한다.
- `public/assets/forum.css`에 `--ablecloud-brand-primary`가 있어야 한다.
- `public/assets/forum-ko.js`가 비어 있지 않고 `core.forum.header.search_placeholder`를 포함해야 한다.
- 데스크톱과 모바일에서 홈, 목록, 상세, 검색, 로그인, 글쓰기, 첨부를 확인한다.
- 데스크톱 첫 화면에서 문서 전체의 `scrollY`가 `0`으로 유지되는지 확인한다.
  Welcome Hero는 표시하지 않고 좌측 메뉴는 고정한다. `.IndexPage-results` 전체가 스크롤되어야
  한다. `최신` 선택 콤보를 포함한 `.IndexPage-toolbar`와 토론 행이 함께
  이동해야 하며 `.DiscussionList` 자체의 `scrollTop`은 `0`을 유지해야 한다.
  우측 영역도 `scrollbar-width: none`과 WebKit 규칙으로 스크롤바를 표시하지
  않는다. 화면 하단에는 Footer가 없어야 한다.
- 기존 Footer의 `ABLECLOUD Home`, `Blog`, `Online Docs` 링크는 콘텐츠 오른쪽의
  세로형 원형 퀵 링크로 보여야 한다. 데스크톱에서는 48px 폭, 모바일에서는
  44px 폭이며 토론 목록을 스크롤해도 화면상 Y 좌표가 변하지 않아야 한다.
- 데스크톱 첫 화면은 고정 최대 폭을 두지 않고 Viewport에서 `clamp(32px, 4vw, 80px)`의
  전체 좌우 여백만 제외한 폭을 사용한다. 1920px Viewport와 안정 Scrollbar Gutter에서는
  Header와 본문 셸이 X 38px~1867px, 폭 약 1829px인지 확인한다.
- 태그·태그별 목록·사용자 프로필·설정·보안 화면의 Header·Hero·본문도 같은
  Viewport 기반 외곽선을 사용한다. 본문과 Hero의 오른쪽 80px은 고정 퀵 링크 영역으로
  예약해 겹침을 방지한다. 모바일에는 이 데스크톱 폭을 강제하지 않는다.
- 데스크톱 Header의 Flarum 기본 8px 외곽 Padding을 제거해 Header와 본문 셸의
  왼쪽·오른쪽 끝이 정확히 일치해야 한다.
- 좌측 메뉴는 사용자 설정 화면과 같이 고정한다. 높이가 짧아 태그가 모두 보이지
  않을 때 내부 스크롤은 허용하지만 `scrollbar-width: none`과 WebKit 규칙으로
  스크롤바는 표시하지 않는다.
- 토론 목록 바깥 Container와 개별 행에 Card Border·Background·Shadow를
  만들지 않는다. 투명한 평면 피드에서 1px 구분선으로만 행을 나누고,
  작성 정보·제목·첫 글 요약·태그·댓글 수·더보기 기능과 파란색 Hover/Focus
  상태를 유지한다.
- 해결 배지와 대표 카테고리·작성자·작성 시각은 같은 헤더 행에서 서로 겹치지
  않아야 한다. 사용자 아바타는 해결 여부와 관계없이 행 좌측 상단의 본문 경계
  안에 있어야 한다.
- 첫 게시물에 이미지가 있으면 첫 이미지를 데스크톱 124×92px, 모바일 88×72px
  우측 썸네일로 표시한다. 이미지가 없는 글에는 빈 썸네일 영역을 만들지 않으며,
  썸네일은 기존 Store 데이터에서 생성하고 지연 로딩해야 한다.
- 토론 상세 Hero와 본문 셸은 시작 페이지와 같은 Viewport 기반 외곽선을 사용해야 한다.
  상세 Header도 같은 외곽선을 사용해 Header·Hero·본문의 좌우 끝이 정확히 일치해야 한다.
  게시물 Stream은 남은 가용 폭을 사용하고 기존 Flarum 세로 탐색 구조는 유지한다.
  1920px 검증 기준 게시물 Stream은 약 1508px이다. 세로 탐색에는 답장·팔로우·
  원본/최신 게시물·현재 위치·읽지 않음 정보가 표시되어야 한다.
- 목록의 상세 링크는 첫 게시물 경로 `/1`을 사용한다. 직접 상세 URL로 진입해도
  세션별 한 번만 첫 게시물 경로를 적용하고, Flarum이 정규 주소로 바꾼 뒤 재이동하지
  않아야 한다. 전환 후 `scrollY=0`, 첫 Stream 항목 `data-number=1`을 확인한다.
- 상세 Pane이 기능 버튼 자리를 예약하더라도 Logo는 Header Shell의 `left:15px`에
  고정해 목록과 상세에서 같은 X 좌표를 사용해야 한다.
- 상세 셸 오른쪽 80px은 퀵 링크 영역으로 예약하며 세로 탐색과 퀵 링크의 겹침은
  0px이어야 한다.
- 상세 제목은 Welcome Hero와 같은 배너 외형을 사용하지 않는다. 흰 배경의 콘텐츠
  제목 영역에서 해결 상태·태그·제목·작성자·작성 시각을 왼쪽 정렬로 표시한다.
- 데스크톱 상세 Hero는 고정 Header 아래에서 16px 내려 배치하고 Header 하단과 첫
  태그 사이에 약 18px의 시각적 간격이 있어야 한다.
- 일반 답변은 카드 중첩 없이 1px 구분선으로 나누고 AI 기술지원·추가 확인 필요·
  최종 해결 가이드만 의미 색상 카드로 구분한다.
- 최종 해결 가이드의 배경·테두리·강조선·상태 칩은 별도의 녹색 팔레트를 사용하지
  않고 ABLESTACK Primary Blue의 명도 단계로 표현한다. 온라인 상태점처럼 의미가 다른
  상태 색상은 이 규칙의 대상이 아니다.
- 상세 게시물의 `p`, `li`, `blockquote`, `ul`, `ol`에는 글자 수 기반 최대 폭을
  적용하지 않고 Post Body 가용 폭을 사용한다. 일반 한국어 문장은 `word-break: keep-all`,
  URL·Hash·Inline Code는 `overflow-wrap: anywhere`로 영역 안에서 줄바꿈한다.
- `pre` Code·Log Block은 `white-space: pre`와 자체 가로 Scroll을 유지하고, Table은
  Post Body 안에서만 가로 Scroll한다. Composer는 `white-space: pre-wrap`으로 입력창에서
  긴 문자열을 시각적으로 줄바꿈하되 저장 원문에 임의 개행을 추가하지 않는다.
- 첫 게시물 안의 선택 답변 미리보기는 숨기고 `해결 답변 보기`가 실제 선택 답변으로
  이동해야 한다. 이동 후 선택 답변 상단은 고정 Header 아래에서 보여야 한다.
- 질문 다음에는 `답변을 작성해 주세요` 버튼이 표시되어 기존 Flarum 답장 작성기를
  열어야 한다. 480px보다 긴 `pre` 로그에는 `전체 로그 보기`와 `로그 접기`가 제공되어야 한다.
- 왼쪽 토론 목록은 400px 폭을 유지하되 메타 정보, 두 줄 제목, 두 줄 요약을 세로로
  배치해야 한다. 썸네일은 72×54px 오른쪽 전용 열, 댓글 수는 오른쪽 아래에 두고
  제목·요약과 겹치지 않아야 한다.
- 작성기의 미리보기·굵게·기울임·코드·인용·링크·이미지·목록·추가 서식 아이콘은
  SVG Mask로 표시되어야 하며 `P`나 검은 사각형 대체 문자가 없어야 한다.
- 목록에서 상세 화면으로 이동했을 때 전체 페이지를 다시 열지 않고 Flarum SPA
  전환을 유지해야 한다. 상세 화면의 `scrollY`는 0이고 왼쪽 가장자리 Hover 시
  400px 토론 목록이 표시되어야 한다. 상세 새로고침 뒤에도 직전 목록 Snapshot을
  사용해 목록을 복원해야 한다.
- 데스크톱 활성 작성기는 최소 336px 높이를 가져야 하며 게시 버튼은 화면 하단에서
  20px 이상 떨어져야 한다. 작성기가 표시되는 동안 왼쪽 토론 목록은 숨겨져 서로
  겹치지 않아야 하고, 작성기를 닫으면 목록이 다시 표시되어야 한다.
- 작성기 본문 편집 영역과 하단 도구막대는 독립된 세로 Flex 행이어야 한다. 두 영역의
  경계는 맞닿을 수 있지만 교차하면 안 되며 도구막대 하단 전체가 작성기 경계 안에
  있어야 한다. 작성 중인 배경 토론 행은 Hover 상태에서도 작성기보다 앞으로 나오면
  안 된다.
- 400px 토론 목록의 더보기 메뉴는 32×32px이고 카드 상단과 오른쪽에서 약 10px
  안쪽에 있어야 한다. `translateY`를 사용하지 않으며 버튼 전체가 카드 경계 안에
  포함되어야 한다.
- 시작 페이지의 목록 끝까지 스크롤하면 기존 `더 보기` 버튼을 직접 누르지 않아도
  다음 20건이 자동으로 로드되어야 한다. 연속 두 번 스크롤해 20→40→60건을
  확인하고, 같은 로딩 표식 때문에 DOM 변경이 반복되지 않는지 화면 조작 지연도
  함께 확인한다. 브라우저가 `IntersectionObserver`를 지원하지 않는 경우에는 기존
  버튼을 사용할 수 있어야 한다.
- 새 토론의 `이모지 삽입` 버튼은 한글 안내가 있는 공통 이모지 24개 선택기를
  표시해야 한다. `regional_indicator_a` 같은 내부 영문 이름이나 원래 Dropdown이
  함께 표시되면 안 되며, 항목 선택 후 실제 편집기 본문에 Unicode 이모지가
  들어가는지 확인한다.
- 새 토론 작성기는 화면 하단 레이어가 아니라 전체 화면 배경 차단 레이어 위의 중앙
  대화상자로 표시되어야 한다. 최소화·전체 화면은 숨기고 닫기는 유지한다. 본문
  편집 영역과 도구막대가 독립 행으로 대화상자 안에 모두 들어가며, 첫 클릭만으로
  대화상자 상태가 적용되어야 한다. 답장 작성기는 기존 흐름을 유지한다.
- 390×844 모바일 시작 화면에서 Header 아래 `.IndexPage-nav > ul`은 빈 둥근
  사각형을 만들지 않아야 한다. 현재 필터와 새 토론 버튼은 Header에서 계속
  동작해야 한다.
- 모바일 좌측 Drawer는 270px 단일 열로 표시하고 검색·언어·신고·알림·계정을
  세로 행으로 배치한다. 닫힌 Locale·Session Dropdown은 공간을 차지하지 않아야
  하며 44×44px 닫기 버튼, 배경 클릭, ESC로 닫은 뒤 `.drawer-backdrop`은 0건이어야 한다.
- 모바일 토론 작성기와 모든 Flarum Modal에는 항상 보이는 44×44px `×` 닫기
  버튼을 제공한다. 닫기 버튼 중심의 실제 Hit Target이 버튼 자신인지 확인하고,
  태그 Modal은 고정 Header와 독립적으로 스크롤되는 Body를 사용해야 한다.
- 모바일 Drawer에서 언어·계정 하위 메뉴를 펼칠 때 Flarum의 터치 전용
  `.dropdown-backdrop`이 Drawer를 덮거나 색을 입히면 안 된다. `한국어 → English →
  한국어` 전환 후 Drawer가 정상 닫히고 최종 언어가 `ko`인지 확인한다.
- 모바일 새 토론과 댓글 작성기는 모두 44×44px `×` 닫기를 제공한다. 댓글 작성기에는
  최소화·전체 화면 버튼을 표시하지 않으며, 닫기 후 `.ablecloud-composer-open` 상태와
  보이는 Composer가 모두 제거되어야 한다.
- 헤더 검색에 `v2k`처럼 해결 답변과 일반 토론이 함께 조회되는 검색어를 입력한다.
  검색 결과 한 건은 태그·제목·질문 요약·선택 답변 요약이 위에서 아래로 표시되어야
  하며, 네 영역이 가로 열로 압축되거나 글자가 한두 자씩 끊기면 안 된다. 검색 접두
  아이콘과 비우기 아이콘은 사각형 대체 문자가 아닌 SVG Mask로 보여야 한다.
- 사용자 프로필·설정 화면을 1,150px 폭에서 스크롤했을 때 고정 메뉴 폭이
  280px로 유지되고 메뉴 오른쪽 끝이 본문 왼쪽보다 작거나 같은지 확인한다.
- `Answered`, `Best Answer`, `Select Best Answer` 원문 노출이 없어야 한다.
- 사용자·토의·게시물 수와 첨부 해시가 적용 전과 같아야 한다.

## 6. 즉시 롤백

화면 깨짐, 원문 번역 키 노출, 로그인·작성 장애가 하나라도 발생하면 테마만 비활성화한다.

```bash
cd /var/www/html
sudo -u www-data php flarum extension:disable ablecloud-community-theme
sudo -u www-data php flarum cache:clear
sudo -u www-data env TECHFLOW_ALLOWED_FLARUM_ROOT=/var/www/html \
  php vendor/ablecloud/community-theme/tools/warm-korean-locale.php /var/www/html
sudo systemctl restart php8.3-fpm nginx
```

비활성화 후 외부 HTTPS, 로그인, 검색, 글쓰기와 첨부를 다시 확인한다. Package 삭제나 DB 복원은 테마 비활성화만으로 복구되지 않는 별도 장애가 확인될 때만 수행한다.

## 7. 판정

- GO: HTTP 200, 한글 원문 키 0건, 핵심 기능 정상, 콘텐츠·첨부 불변.
- ROLLBACK: 화면·번역·로그인·작성·첨부 중 하나라도 실패.
- 2026-08-29 운영 적용 완료: 데스크톱 공통 셸을 Viewport 전체 폭으로 확장하고
  Header·목록·상세·태그·사용자 화면의 좌우선을 통일했다. 토론 상세 Logo와 첫 게시물
  진입도 Pane 상태와 관계없이 고정했다. 최신 운영 백업은
  `/var/backups/techflow-flarum/theme-full-width-stable-20260829T1300KST`이다.
- 2026-08-29 상세 본문 후속 적용 완료: 기존 `82ch` 문단 제한을 제거하고 긴 문자열·
  URL·Inline Code의 안전한 줄바꿈을 적용했다. 최신 백업은
  `/var/backups/techflow-flarum/theme-content-width-20260829T1035KST`이다.
- 2026-08-20 운영 적용 완료: 사용자 메뉴 겹침 보완과 Reddit형 평면 피드·게시물
  정보 계층·이미지 썸네일, 하단 Footer 제거와 우측 고정 퀵 링크, 메인 환영 배너
  제거, Flarum 세로 탐색 복원과 당시 1165px 상세 셸 정렬이 WSL 및 운영에 반영되었다.
  최신 운영 백업은
  `/var/backups/techflow-flarum/theme-infinite-emoji-dialog-final-20260820T1430KST`에
  보존한다. 목록 자동 로딩, 한글 이모지 삽입, 새 토론 중앙 대화상자까지 운영
  브라우저에서 확인했다. 모바일 메인·Drawer·대화상자 보완의 최신 백업은
  `/var/backups/techflow-flarum/theme-mobile-submenu-reply-20260820T151526KST`이며,
  390×844 운영 브라우저에서 Drawer 하위 메뉴 전환과 새 토론·댓글 작성기 닫기를
  확인했다.
