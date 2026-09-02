# Issue #112 Community 관리자 답변 AI 자동 응답 억제 검증

## 결론

Community Poller가 질문자와 TechFlow-Assistant가 아닌 모든 사람을 `STAFF / responseRequested=true`로 처리하던 정책을 교정했다. 관리자와 일반 참여자의 댓글은 대화 문맥과 감사 기록에 보존하지만 AI 답변은 만들지 않는다. 인용문·코드 밖에서 `@TechFlow-Assistant` 또는 줄 시작 `/ai`를 사용한 경우에만 AI 응답을 요청한다.

운영 Discussion #178에서 관리자 Post #437은 `STAFF_RECORDED`로 기록됐고 뒤에 Assistant Post가 생기지 않았다. 관리자 명시 호출 Post #438은 `EXPLICIT_AI_REQUEST`로 기록됐고 Assistant Post #439가 게시됐다. 공개 브라우저 화면에서도 같은 순서와 작성자를 확인했다.

## 구현

- 질문자 Post: `REQUESTER_AUTO`, 자동 응답
- Assistant Post: `ASSISTANT_SELF`, 재응답 금지
- 등록 지원 담당자 일반 Post: `STAFF_RECORDED`, 문맥만 저장
- 일반 참여자 Post: `PARTICIPANT_RECORDED`, 문맥만 저장
- 관리자·참여자 명시 호출: `EXPLICIT_AI_REQUEST`, AI 응답
- `blockquote`, `pre`, `code` 내부 호출 문자열 제외
- 해결 관리자 ID, 최종 KB selector ID와 지원 담당자 ID 통합
- 응답 사유를 Community Case 감사 이벤트에 기록
- 이전 Activepieces Flow가 `responseReason`을 전달하지 않아도 역할과 응답 여부로 안전하게 복원

## 회귀시험

- WSL ext4 전체 AI Gateway 시험: 343건 PASS
- Community Poller 집중 시험: 35건 PASS
- 관리자 무응답·기존 Flow 호환 계약: PASS
- Activepieces Flow·보호 서비스 계약: 13건 PASS
- Ruff 변경 파일 검사: PASS
- OpenAPI: 39 Operations
- `git diff --check`: PASS

## 운영 E2E

대상: `https://community.ablecloud.io/d/178`

| Post | 작성자 | 입력·처리 | 결과 |
|---|---|---|---|
| #434 | 질문자 | 최초 E2E 질문 | Provider 구조 응답 실패 후 재시도 |
| #435 | 질문자 | 해결 결과 | 결정적 응답 생성 |
| #436 | TechFlow-Assistant | #435 응답 | 게시 성공 |
| #437 | 관리자 | 직접 지원 답변 | `STAFF_RECORDED`, AI 응답 없음 |
| #438 | 관리자 | `@TechFlow-Assistant` 명시 호출 | `EXPLICIT_AI_REQUEST` |
| #439 | TechFlow-Assistant | #438 응답 | 게시 성공 |

브라우저에서 #437 다음 항목은 관리자 명시 호출 #438이었으며, 자동 AI 답변은 없었다. #438 뒤에는 Assistant #439가 표시됐다.

## 재시도 연속성 보완

E2E 중 원본 Post #434의 기존 재시도가 뒤 Post 처리 후에도 계속되는 문제를 발견했다. 이미 실행 중이던 한 건이 #440을 게시했지만 감사 이벤트는 `sourcePostId=434`, `responseReason=REQUESTER_AUTO`여서 관리자 #437과 무관함을 확인했다.

Issue #113에서 Case가 없던 기존 Discussion을 뒤 Post가 통합 처리할 때 이전 사람 Post ID를 `coalescedPostIds`로 저장하도록 수정했다. 통합 Post가 확인되면 이전 대기 Post도 함께 Seen 처리한다. 현재 운영 Poller는 `pendingPosts=0`, `failed=0`, #434 Seen 상태다.

## 운영 배포

- Gateway: `techflow/ai-gateway:issue112-0.16.8-3047786`, Healthy, Restart 0
- Community Poller: `techflow/ai-gateway:issue113-0.16.8-8330d8c`, Healthy, Restart 0
- Gateway Health: Version 0.16.8, Provider OpenAI, Database·Vector Ready
- Backup: `/home/ablecloud/techflow-ai-gateway-backups/issue112-staff-silence-20260902T090656Z`
- DB Dump: 약 1.4 GiB, mode 0600
- 최종 Package SHA-256: `77e5aff4b1c5d0fa8eedfcecb66938015a7abfb947857a1f45b7702770a6da22`
- 공개 Community·Chat HTTPS: HTTP 200

Source Reconciler, GitHub→Chat Event Gateway, Activepieces App·Worker의 Container ID, Restart Count와 StartedAt은 배포 전후 동일하다. Activepieces 실행 Flow는 중단·재기동하지 않았고 Gateway 하위 호환 판정으로 현재 계약을 유지했다. 저장소 Flow 정의에는 다음 게시 시 `responseReason`을 명시 전달하도록 반영했다.

## 연결

- Issue #112
- Issue #113
- PR #110
- Discussion #178
- `docs/evidence/issue-112/community-staff-ai-policy-validation.json`
