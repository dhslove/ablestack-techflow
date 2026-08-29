# Issue #107 Community 상세 본문 폭·긴 문자열 완료 보고서

## 결론

Community 상세 Page Shell과 Post Stream은 전체 폭으로 확장돼 있었지만 게시물 내부 일반 문단은 `max-width: 82ch` 때문에 약 728px만 사용하고 있었다. 이 제한을 제거해 일반 문단·목록·인용문이 Post Body 전체 폭을 사용하도록 WSL과 운영에 반영했다.

작성기 저장 문제도 함께 확인했다. 일반 질문 원문의 DOM에는 작성기가 추가한 `<br>`·`<wbr>`가 없었으며, 잘림처럼 보인 원인은 저장 데이터가 아니라 CSS 폭 제한이었다. Composer에는 저장 개행 변경 없이 화면상 긴 문자열 줄바꿈만 적용했다.

추가 UI 검토에서 최종 해결 가이드만 녹색 카드·배지·강조선을 사용해 ABLESTACK의 블루 중심 테마와 이질적인 점을 확인했다. 해결 상태의 배경·테두리·강조선·상태 칩을 Primary Blue의 명도 단계로 통일했다. 온라인 상태점처럼 해결 상태와 의미가 다른 녹색 표시는 유지한다.

## 구현

- `.Post-body p`, `li`, `blockquote`의 `82ch` 최대 폭 제거
- 문단·목록·인용문 `width:100%`, `max-width:none`, `min-width:0`
- 일반 한국어 `word-break:keep-all`
- 긴 URL·Hash·오류 문자열·Inline Code `overflow-wrap:anywhere`
- `pre code`는 `white-space:pre`, `overflow-wrap:normal` 유지
- 넓은 Table은 Post Body 내부 가로 Scroll
- Composer Editor `white-space:pre-wrap`, `overflow-wrap:anywhere`
- 원본 게시물·DB·Formatter·Markdown 변환 로직 변경 없음
- 최종 해결 카드 Surface `#edf4ff`, Border `#8fb5ef`, Accent `#155eef`, Ink `#0b3b91`
- 상세 Hero·목록·카드·해결 상태 칩·선택 미리보기의 해결 상태 팔레트 통일

## 검증

| 항목 | 변경 전 운영 | 변경 후 WSL·운영 |
|---|---:|---:|
| 1920px Post Body | 1383px | 1383px |
| 일반 문단 | 약 728px | 1383px |
| 문단 Max Width | 약 82ch | none |
| 긴 문자열 내부 넘침 | 제한 폭 영향 | 0px |
| 일반 원문 BR/WBR | 0 / 0 | 0 / 0 |
| 390px 문서 Scroll Width | 375px | 375px |
| 모바일 가로 넘침 | 없음 | 없음 |

- Theme 계약 시험 17건 PASS
- WSL Cycle `issue107-detail-content-width-20260829` PASS
- WSL 해결 팔레트 Cycle `issue107-solution-blue-20260829` PASS
- 활성화→비활성화 롤백→재활성화 완료
- 이미지 `max-width:100%`와 Code Block 자체 Scroll 회귀 없음
- 운영 토론 #176에서 최종 해결 카드·Hero 배지·상태 칩 렌더링 확인
- 운영 계산 색상: 강조선 `rgb(21, 94, 239)`, 테두리 `rgb(143, 181, 239)`, 칩 배경 `rgb(220, 233, 255)`, 칩 글자 `rgb(11, 59, 145)`

## 운영 배포

- 운영 Server: `172.16.0.234`
- Nginx·PHP-FPM·MariaDB Active
- Local HTTP 200, 외부 Browser HTTPS 정상
- Source·Vendor LESS SHA-256: `45a98c73513043957e4d40cc052be5c16cb9e2b9320e5a865bee5608455ac1d1`
- 최신 백업: `/var/backups/techflow-flarum/theme-issue107-solution-blue-20260829`

Flarum Core·DB Schema·게시물·첨부·AI Gateway·GitHub→Chat Webhook은 변경하지 않았다.

## 관련 자산

- Issue #107
- PR #108
- `docs/evidence/issue-107/community-detail-content-width-validation.json`
- `docs/runbooks/community-theme-rollout-rollback.md`
