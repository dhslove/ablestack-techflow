# Issue #96 Community Discussion #137 복구 보고서

## 1. 결론

Discussion #137의 후속 질문 Post #412가 TechFlow-Assist 처리 대상이었지만 첨부 경고 계약과 비동기 완료 판정 결함으로 누락됐다. AI Gateway 0.15.1에서 첨부 수집·경고 정규화·Gateway 확인·게시 완료·관리자 Identity·멀티모달 지연 정책을 보완하고 운영에서 Post #412를 재처리했다.

최종 AI 답변은 Post #414로 게시됐으며 Case는 `PUBLISHED`, 답변은 `ANSWERED`, 대화는 질문자의 해결 확인을 기다리는 `WAITING_RESOLUTION` 상태다.

## 2. 최초 원인

1. Flarum의 답글 멘션 링크가 첨부 후보로 분류됐다.
2. 내부 Flarum API가 이미지 주소를 `https://172.16.0.234`로 렌더링했으나 Poller는 공개 HTTPS와 내부 HTTP Origin만 허용했다.
3. 이미지마다 같은 경고가 생성되어 `artifactWarnings` 유일성 계약을 위반했다.
4. Gateway는 중복 경고를 HTTP 422로 거부했다.
5. Activepieces Flow는 하위 HTTP 실패에도 Webhook 호출자에게 성공을 반환했다.
6. Poller는 Activepieces 수락만으로 Post #412를 `seenPosts`에 기록해 재처리가 중단됐다.

## 3. 구현

- PostMention과 일반 링크를 첨부 후보에서 제외
- 설정된 내부 Flarum Host의 HTTP·HTTPS 기본 Origin을 안전하게 허용
- 같은 첨부 경고를 순서 보존 방식으로 고유하게 정규화
- Activepieces 수락 후 Gateway `lastSeenPostId` 확인 전 체크포인트 금지
- 답변 요청은 Case `PUBLISHED`와 `publishedPostId`까지 확인
- 실패·지연 시 Post를 미완료로 유지하고 다음 Poll에서 재시도
- 기존 Case가 없는 후속 질문은 이전 질문·지원 답변을 텍스트 맥락으로 합성
- 현재 후속 질문의 첨부를 우선 분석
- Assistant 게시 승인 해제는 Solution Selector 관리자 Identity로 실행
- 멀티모달 종합 분석은 `OPENAI_RAG_DEFAULT_V1`을 사용해 지연을 제어

## 4. 운영 복구

- Gateway·Community Poller만 `techflow/ai-gateway:issue96-0.15.1-3194967`로 교체
- Poller 상태와 DB·소스·Compose 설정 백업
- 복구 과정에서 잘못 생성된 Assistant Post #413과 Case 1건을 대상 검증 후 제거
- Post #412와 Discussion #137 Snapshot만 재처리 가능 상태로 복원
- 원 질문·지원 답변·후속 질문과 최신 이미지 2개를 종합 분석

삭제 전 Post #413 JSON과 전체 DB는 `/home/ablecloud/techflow-backups/issue96-20260824T124907Z`에 보관했다. 최종 배포 백업은 `/home/ablecloud/techflow-backups/issue96-latest-20260824T131537Z`다.

## 5. 검증 결과

| 항목 | 결과 |
|---|---|
| Repository 테스트 | 280건 통과 |
| Gateway | 0.15.1, Healthy |
| Poller | Running |
| Discussion Case | `8ad7004f-a996-471a-adba-04dcb80d7e97` |
| 원본 후속 Post | #412 |
| AI 답변 Post | #414 |
| 이미지 Artifact | 2건 |
| Provider | `OPENAI_RAG_DEFAULT_V1` / `gpt-5.6-terra` |
| Provider 지연 | 17,116ms |
| Source Coverage | 9개 Profile 모두 `EVIDENCE_FOUND` |
| 일반 답변 내부 근거 노출 | 0건 |
| 일반 답변 제목 Heading | 0건 |
| Chat 관찰 알림 | 1회 성공 |
| Poller 최종 3분 | 완료 4회, 실패 0회 |
| Community·Chat·Activepieces | HTTP 200 |
| 보호 서비스 변경 | 0건 |

## 6. 최종 상태

Poller 상태에는 Post #412와 Assistant Post #414가 모두 완료로 기록됐고 Discussion Snapshot은 댓글 4건으로 일치한다. 장애 상태는 `RECOVERED`로 전환됐다. 질문자가 Post #414의 확인 절차를 수행한 뒤 해결 답변을 선택할 때까지 같은 Case에서 후속 질문을 계속 처리한다.

## 7. 관련 자산

- Issue #96
- PR #97
- `docs/evidence/issue-96/discussion-137-recovery.json`
- `docs/runbooks/epic4-service-continuity.md`
