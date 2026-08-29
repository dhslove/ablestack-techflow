# Issue #106 Community 전체 폭·상세 첫 위치 완료 보고서

## 결론

Community의 기존 구조·색상·타이포그래피를 유지하면서 데스크톱 Page Shell을 고정 1165px에서 Viewport 기반 전체 폭으로 확장했다. 추가 검증에서 확인된 상세 Header Logo 이동과 마지막 게시물 자동 이동도 함께 교정해 WSL과 운영에 반영했다.

## 변경 내용

- Desktop Shell: `viewport - clamp(32px, 4vw, 80px)`
- Header·Index·Discussion Hero·Discussion Body·Tags·User·Settings·Security 동일 외곽선
- 좌측 메뉴 280px, 오른쪽 Quick Link 예약 80px 유지
- 게시물 Stream의 고정 최대 폭 제거, 남은 폭 사용
- Header 기본 8px 외곽 Padding 제거
- Header Logo를 Shell 내부 `left:15px`에 고정
- 목록 상세 링크를 첫 게시물 `/1` 경로로 정규화
- 직접 상세 URL도 세션별 한 번만 첫 게시물 경로 적용
- `scrollRestoration=manual`과 초기 Scroll 보정으로 지연 마지막 게시물 이동 차단
- Flarum 정규 URL 전환 이후 반복 Redirect 방지

## 자동화·WSL 검증

- Theme 계약 시험 15건 통과
- JavaScript Syntax 검사 통과
- 최종 WSL Cycle: `issue106-detail-stable-final-20260829`
- 활성화→비활성화 롤백→재활성화 PASS
- Flarum Core 1.8.18, 사용자·토론·게시물·첨부 무결성 동일
- 최초 LESS `calc()` 컴파일 오류는 Wikimedia LESS가 CSS Variable 연산을 평가한 것이 원인이었고, LESS Escaped String으로 교정

## 브라우저 실측

| 항목 | 변경 전 1920px | 변경 후 WSL·운영 1920px |
|---|---:|---:|
| Header Shell | X 370~1535, 1165px | X 38~1867, 약 1829px |
| Index Shell | X 370~1535, 1165px | X 38~1867, 약 1829px |
| 목록 결과 | 758px | 1422px |
| 상세 Hero·Body | 고정 1165px | X 38~1867, 약 1828px |
| 상세 Post Stream | 최대 1100px | 약 1508px |
| Tags·User Shell | 고정 1165px | X 38~1867, 약 1828px |
| 목록 Logo X | 53px | 53px |
| 상세 Logo X | 92px | 53px |

목록→상세 전환을 0·100·250·500·900·1500·2500·4000ms에 측정했다. 모든 시점에서 Logo X는 53px, `scrollY=0`, 첫 게시물 번호는 `1`이었다. 상세 URL 직접 진입도 동일했다.

390×844 모바일은 Viewport 390px, 문서 Scroll Width 375px, 목록 폭 330px으로 가로 넘침이 없었다. 데스크톱 전체 폭 규칙은 767px 이하에 적용되지 않는다.

## 운영 배포

- 운영 Server: `172.16.0.234`
- Nginx·PHP-FPM·MariaDB Active
- Server Local HTTP 200, 외부 Browser HTTPS 정상
- Source/Vendor LESS SHA-256 동일: `5d302a43300e935656f85f0b9e80fe76b9d0e33546ff99cfbe38ac5d25603089`
- Source/Vendor JS SHA-256 동일: `310cd469db377bbe6da84a37bf458813c92980a31825b415badbe064d781148d`
- 최종 백업: `/var/backups/techflow-flarum/theme-full-width-stable-20260829T1300KST`

Flarum Core·DB Schema·게시물·첨부·AI Gateway·GitHub→Chat Webhook은 변경하지 않았다.

## 관련 자산

- Issue #106
- PR #101
- `docs/evidence/issue-106/community-full-width-validation.json`
- `docs/runbooks/community-theme-rollout-rollback.md`
