# Community 지속 대화 운영 Runbook

## 1. 정상 처리 흐름

1. 질문자가 새 Discussion 또는 후속 댓글을 등록한다.
2. Community Poller가 새 Post를 수집하고 작성자를 `REQUESTER`, `STAFF`, `ASSISTANT`로 분류한다.
3. 이미지, 일반 로그, ZIP, GZIP, TAR.GZ 첨부를 검증해 Artifact Store에 등록한다.
4. AI Gateway가 기존 대화와 새 자료를 함께 분석하고 새 Draft Version을 만든다.
5. `TechFlow-Assistant`가 전체 답변을 Flarum의 미승인 Post로 등록한다.
6. 담당자는 Chat 알림의 링크로 원문을 열어 승인, 수정 승인 또는 반려한다.
7. 승인된 답변은 `WAITING_RESOLUTION` 상태로 질문자의 해결 표시를 기다린다.
8. 질문자가 Best Answer를 설정하면 Case를 `RESOLVED`로 전환한다.
9. 해결 표시가 해제되거나 후속 질문이 등록되면 같은 Case를 다시 연다.

사용자 답변은 별도 제목 없이 `증상`으로 시작한다. 적용 버전은 `ABLESTACK Diplo`, `ABLESTACK Europa`로 표시한다.

## 2. 상태 확인

```sql
SELECT discussion_id, state, conversation_state, context_version,
       last_seen_post_id, review_post_id, published_post_id,
       requester_user_id, resolved_post_id, resolved_by_user_id,
       resolved_at, reopened_at
FROM community_case
ORDER BY updated_at DESC
LIMIT 20;
```

정상 전이:

- 새 질문 또는 후속 자료: `DRAFT_PENDING / WAITING_REVIEW`
- 담당자 승인: `PUBLISHED / WAITING_RESOLUTION`
- 질문자 해결 표시: `PUBLISHED / RESOLVED`
- 해결 해제 또는 후속 질문: `PUBLISHED / ANALYZING`

Turn과 첨부 확인:

```sql
SELECT source_post_id, post_number, author_user_id, role,
       artifact_ids, created_at
FROM community_turn
WHERE case_id = (
  SELECT id FROM community_case WHERE discussion_id = '<DISCUSSION_ID>'
)
ORDER BY post_number, created_at;
```

## 3. 로그 확인

```bash
docker logs --since 10m techflow-ai-gateway-community-poller-1 \
  | grep -E 'community_poll_completed|community_post_delivery_failed'

docker logs --since 10m techflow-ai-gateway-gateway-1 \
  | grep -E 'community_review_post_created|community_chat_notification_sent'
```

정상 기준:

- `community_poll_completed`
- `failed=0`
- 새 초안 생성 시 `community_review_post_created`
- Chat 통지 시 `community_chat_notification_sent`

## 4. 첨부 처리

### 4.1 지원 형식

- 이미지: PNG, JPEG, WebP
- 일반 로그 및 텍스트 파일
- 압축 로그: ZIP, GZIP, TAR.GZ

압축은 경로 탈출, 압축 폭탄, 중첩 압축, 바이너리 위장 및 비밀정보 노출을 차단한다. Activepieces에는 원본 파일이 아니라 검증된 Artifact ID만 전달한다.

### 4.2 macOS ZIP

macOS가 만든 ZIP에는 실제 로그와 함께 다음 메타데이터가 들어갈 수 있다.

- `__MACOSX/`
- `.DS_Store`
- `._<파일명>` AppleDouble 파일

이 파일은 분석 대상 로그가 아니므로 ZIP과 TAR.GZ 파서가 건너뛴다. 실제 로그에는 기존 보안 검사를 그대로 적용한다.

### 4.3 처리 불가 첨부

첨부 하나가 영구적으로 처리 불가하더라도 해당 Discussion과 전체 수집 큐를 계속 막지 않는다.

- HTTP 400, 404, 410, 413, 415, 422: 안전한 경고 문구를 질문 맥락에 추가하고 Post 처리를 계속한다.
- 네트워크 오류 또는 일시적 5xx: 상태를 진행시키지 않고 다음 Poll에서 재시도한다.
- 첨부 제한 초과: 파일명이나 비밀정보를 노출하지 않는 안내만 답변 생성기에 전달한다.

## 5. 상태 체크포인트와 재처리

Poller는 성공한 Post마다 상태 파일을 임시 파일에 쓴 뒤 원자적으로 교체한다. Webhook 전송이 성공하기 전에는 해당 Post를 처리 완료로 기록하지 않는다.

특정 Discussion의 새 Post가 실패하면 다음 규칙을 적용한다.

- 실패한 Discussion의 `commentCount`와 해당 Post의 Seen 상태는 진행시키지 않는다.
- 다른 Discussion의 수집은 계속한다.
- 다음 Poll에서 실패한 Post만 다시 시도한다.
- 성공한 Post는 즉시 체크포인트하므로 이미 만든 Draft를 반복 생성하지 않는다.

## 6. 장시간 AI 처리

Community Draft 생성은 문서, Diplo 코드, 기타 제품 코드, 필요 시 가상화 공식 자료와 첨부 로그를 함께 분석하므로 120초를 넘길 수 있다. Activepieces의 `create_reviewable_draft` HTTP Action 제한은 300초로 설정한다. 다른 Community Action의 기본 제한은 120초를 유지한다.

```bash
python3 deploy/compose/activepieces/scripts/manage-rag-flows.py \
  --base-url http://172.16.0.231:8080 \
  --bundle deploy/compose/activepieces/flows/community-assist-v1.json
```

배포 후 `community-question-draft-v1`의 Published Version에서 `create_reviewable_draft.settings.input.timeout=300`을 확인한다.

## 7. 승인과 해결

Chat은 전체 답변을 잘라서 보내지 않고 Flarum 검토 링크를 전달한다. 담당자는 Flarum Approval로 원문 전체를 확인한 뒤 공개를 결정한다. 질문자의 Best Answer만 자동 해결로 인정한다.

미승인 Review Post가 만들어진 상태는 장애가 아니다. 다음 세 항목이 일치하면 정상 승인 대기 상태다.

- Case: `DRAFT_PENDING / WAITING_REVIEW`
- Review Post: `isApproved=false`
- Gateway Log: `community_chat_notification_sent`

## 8. 배포

1. Gateway 소스, Compose, DB를 백업하고 DB Dump SHA-256을 기록한다.
2. Secret 파일은 존재와 권한만 확인하고 값을 출력하지 않는다.
3. Gateway와 Poller를 같은 Release Tag로 빌드한다.
4. Gateway와 Poller만 교체한다.
5. Activepieces Community Flow를 다시 게시하고 Draft Action의 300초 제한을 확인한다.

```bash
cd /home/ablecloud/techflow-ai-gateway/deploy/compose/ai-gateway
export TECHFLOW_RAG_RELEASE=issue-68-community-conversation
docker compose -p techflow-ai-gateway --env-file .env \
  -f compose.yml -f ../../../compose.openai.override.yml build gateway
docker compose -p techflow-ai-gateway --env-file .env \
  -f compose.yml -f ../../../compose.openai.override.yml \
  up -d --no-deps gateway community-poller
```

Health에서 `provider=openai`, `version=0.13.2`, `database=ready`, `vector=ready`를 확인한다.

## 9. 장애 대응 표

| 증상 | 확인 | 조치 |
| --- | --- | --- |
| 후속 ZIP 이후 새 Draft가 없음 | Poller의 `community_post_delivery_failed`, Artifact HTTP 상태 | macOS 메타데이터 여부와 실제 로그 수를 확인하고 0.13.2 이상으로 교체 |
| AI 일시 실패 후 같은 Post가 소비됨 | `answerState=FAILED`, Draft와 Review Post 없음 | 0.13.2의 실패 Draft 재시도 경로로 같은 Post를 다시 전달 |
| 같은 Review Post가 반복 처리됨 | Poller 상태의 Seen Post와 `commentCount` | 원자적 체크포인트 적용 여부 확인 후 실패 Post만 재실행 |
| Gateway에는 Draft가 있으나 Flow가 시간 초과 | Gateway 요청 시간과 Activepieces Action timeout | `create_reviewable_draft`를 300초로 게시 |
| 승인 대기 Post가 사용자에게 안 보임 | Case 상태, Review Post `isApproved` | 정상 승인 대기면 Chat 링크에서 담당자가 승인 |
| 처리 불가 첨부가 큐를 막음 | HTTP 400/413/415/422 반복 | 영구 오류를 안전 경고로 전환하고 후속 답변 생성 |
| Poller 상태 파일 손상 | JSON 파싱 실패, `.tmp` 잔존 | 백업 상태로 복구하고 파일시스템 권한·공간 확인 |

## 10. 롤백

1. Community 입력과 승인을 잠시 중단한다.
2. Gateway와 Poller만 직전 이미지로 되돌린다.
3. Activepieces Community Flow를 직전 Published Version으로 되돌린다.
4. Flarum의 원문, 승인된 답변 및 미승인 Review Post를 임의 삭제하지 않는다.
5. `techflow-activepieces-event-gateway-1` GitHub-to-Chat 서비스는 배포·롤백 대상에서 제외한다.
