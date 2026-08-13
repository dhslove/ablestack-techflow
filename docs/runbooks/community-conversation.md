# Community 지속 대화 운영 Runbook

## 1. 정상 운영 흐름

1. 질문자가 새 Discussion 또는 후속 댓글을 등록한다.
2. Poller가 Post 단위로 수집하고 작성자를 `REQUESTER`, `STAFF`, `ASSISTANT`로 분류한다.
3. 이미지·로그·압축 로그가 있으면 Artifact Store에 검증 등록한다.
4. AI Gateway가 이전 Turn과 새 Turn을 함께 분석해 Draft Version을 증가시킨다.
5. TechFlow-Assistant가 전체 답변을 미승인 Post로 등록한다.
6. 담당자는 Chat 링크를 열어 Flarum에서 승인·수정·반려한다.
7. 승인 후 Case는 `WAITING_RESOLUTION`이 된다.
8. 질문자가 Best Answer를 설정하면 `RESOLVED`가 된다.
9. 질문자가 해결 표시를 해제하거나 후속 질문을 쓰면 같은 Case가 다시 `ANALYZING`이 된다.

사용자 답변은 제목 없이 `증상`으로 시작한다. 적용 버전은 `ABLESTACK Diplo`, `ABLESTACK Europa`로 표시한다.

## 2. 상태 확인

```sql
SELECT discussion_id, state, conversation_state, draft_version,
       review_post_id, published_post_id, requester_user_id,
       resolved_post_id, resolved_by_user_id, resolved_at, reopened_at
FROM community_case
ORDER BY updated_at DESC
LIMIT 20;
```

정상 전이:

- 신규 또는 후속 질문: `DRAFT_PENDING / WAITING_REVIEW`
- 승인: `PUBLISHED / WAITING_RESOLUTION`
- 질문자 해결: `PUBLISHED / RESOLVED`
- 해결 해제: `PUBLISHED / ANALYZING`

Turn 확인:

```sql
SELECT source_post_id, post_number, author_user_id, role, artifact_ids, created_at
FROM community_turn
WHERE case_id = (SELECT id FROM community_case WHERE discussion_id = '<DISCUSSION_ID>')
ORDER BY post_number, created_at;
```

## 3. 로그 확인

```bash
docker logs --since 10m techflow-ai-gateway-community-poller-1 \
  | grep -E 'community_poll_completed|community_poll_failed'

docker logs --since 10m techflow-ai-gateway-gateway-1 \
  | grep -E 'community_review_post_created|community_chat_notification_sent|community-resolution'
```

정상 기준:

- `community_poll_completed`
- `reviewRetryFailed=0`
- 후속 질문 처리 시 `community_review_post_created`
- 해결·해제 이벤트의 `/v1/community/cases` 응답 `201`

## 4. 첨부 점검

### 이미지

- Community 본문 `<img src>`가 수집되는지 확인한다.
- Artifact 종류가 `IMAGE`인지 확인한다.
- 질문과 다른 화면이면 답변에서 근거로 사용하지 않고 불일치 사실을 설명한다.

### 로그·압축 로그

- 허용 형식: 일반 텍스트 로그, ZIP, GZIP, TAR.GZ
- 압축 파일은 파일 수, 전체 추출 크기, 경로 이탈, 중첩 압축, 바이너리를 제한한다.
- 비밀번호·토큰·키는 마스킹한다.
- Activepieces에는 원본 바이트가 아니라 Artifact ID만 전달한다.

## 5. 승인과 해결

담당자 승인은 Flarum Approval을 사용한다. Chat은 전체 답변을 복제하지 않고 Review Post 링크를 전달한다. Flarum에서 승인된 Post만 공개 답변이 된다.

질문자의 Best Answer만 자동 해결로 인정한다. 관리자가 대신 선택하거나 다른 사용자가 선택하면 자동 `RESOLVED`로 닫지 않는다. Best Answer가 해제되면 `reopened_at`을 기록하고 같은 Case를 다시 연다.

## 6. 배포

1. Gateway 소스, Compose, DB를 백업하고 DB Dump SHA-256을 남긴다.
2. Secret 파일은 존재와 권한만 확인하고 값을 출력하지 않는다.
3. `0011_community_conversation_up.sql`을 적용한다.
4. Gateway와 Poller 이미지를 같은 Release Tag로 빌드한다.
5. OpenAI Override를 포함해 Gateway와 Poller만 교체한다.

```bash
cd /home/ablecloud/techflow-ai-gateway/deploy/compose/ai-gateway
export TECHFLOW_RAG_RELEASE=issue-68-community-conversation
docker compose -p techflow-ai-gateway --env-file .env \
  -f compose.yml -f ../../../compose.openai.override.yml build gateway
docker compose -p techflow-ai-gateway --env-file .env \
  -f compose.yml -f ../../../compose.openai.override.yml \
  up -d --no-deps gateway community-poller
```

Health에서 `provider=openai`, `version=0.13.0`, DB·Vector `ready`를 확인한다. `community_case`의 Conversation 열 8개와 `community_turn`, `community_response` 테이블을 확인한다.

## 7. 장애 대응

| 증상 | 확인 | 조치 |
| --- | --- | --- |
| 후속 댓글이 새 Draft를 만들지 않음 | Poller `delivered`, Post ID 중복, Activepieces Run | Post 단위 멱등성 키와 Flow 입력 확인 |
| 해결 설정만 400 | 해결 이벤트 Idempotency-Key | ISO 시각 직접 사용 여부 확인, 해시 기반 키 적용 |
| 승인했지만 공개 동기화 안 됨 | Review Post `isApproved`, reconcile 로그 | Poller 재조정, 현재 Draft Version 확인 |
| 삭제된 Review Post 반복 오류 | Flarum 404, `reviewsMissing` | Case를 `REJECTED/ANALYZING`으로 전환 후 새 답변 생성 |
| 이미지·ZIP이 누락 | HTML 링크, Artifact ID, 허용 형식 | 다운로드 경로와 Content-Disposition 확인 |
| 답변이 재귀 생성됨 | Turn role | Assistant ID Secret과 역할 판별 확인 |

## 8. 롤백

1. 새 Community 입력과 승인을 잠시 중지한다.
2. Gateway와 Poller만 직전 이미지로 되돌린다.
3. 필요할 때 `0011_community_conversation_down.sql`을 적용한다. Down Migration은 Turn·Response 이력을 삭제하므로 DB 백업이 확인된 경우에만 수행한다.
4. Flarum 원문과 승인된 Post는 삭제하지 않는다.
5. `techflow-activepieces-event-gateway-1` GitHub→Chat 서비스는 롤백 대상에서도 제외한다.
