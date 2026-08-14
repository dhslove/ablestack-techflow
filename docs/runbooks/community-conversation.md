# Community 자동 답변과 Knowledge Base 운영 Runbook

## 1. 정상 처리 흐름

1. 질문자 또는 다른 참여자가 Discussion이나 후속 댓글을 등록한다.
2. Poller가 새 Post와 이미지·로그·압축 로그를 수집한다.
3. AI Gateway가 기존 대화, ABLESTACK 문서와 코드, 승인된 플랫폼 자료를 함께 분석한다.
4. `TechFlow-Assistant`가 이해하기 쉬운 대화체 답변을 바로 공개한다.
5. Chat Bot이 게시 결과와 Community 링크를 담당자에게 알린다.
6. 사람 참여자가 추가 정보나 후속 질문을 올리면 같은 Case에서 분석과 답변을 반복한다. `TechFlow-Assistant` 자신의 Post는 재응답하지 않는다.
7. 질문자가 Best Answer를 선택하면 해당 답변 중심의 Knowledge Base 최종본을 게시한다.
8. KB 공개를 확인한 뒤 해당 KB Post를 최종 Best Answer로 지정하고 Flarum 재조회 결과가 일치하는지 확인한다.
9. 해결 표시가 해제되거나 후속 질문이 생기면 같은 Case를 다시 연다.

진행 중 답변에는 고정된 문서 형식을 강제하지 않는다. 해결 후 KB에만 `증상`, `원인`, `해결 방법`, `추가 고려사항`, `적용 버전`을 사용하며 별도 제목은 붙이지 않는다.

후속 답변은 다음 순서를 지킨다.

1. 최신 질문에 직접 답하고 가장 가능성이 높은 안전한 해결 방법을 먼저 제시한다.
2. 근거가 있는 경우 실행 위치, 정확한 CLI 명령과 정상 판정 기준을 함께 제공한다. 설명은 문장으로 먼저 쓰고 CLI는 바로 아래의 독립된 `bash` 코드 블록에 표시한다.
3. 첫 조치로 해결되지 않을 때 적용할 대안을 제시한다.
4. 그래도 해결되지 않을 때만 정확한 명령 출력이나 로그 이름을 요청한다.

직전 답변과 같은 원인 설명·점검 목록은 다시 게시하지 않는다. 첫 생성 결과가 반복이면 Gateway가 한 번 재작성하고, 재작성도 진행되지 않으면 `COMMUNITY_RESPONSE_NOT_PROGRESSING`으로 게시를 중단해 Poller 재시도 대상으로 남긴다.

`읽기 전용`, `변경 없음`, `호스트 관리자`, `네트워크 관리자`는 내부 작업 분류 정보이므로 사용자 답변의 제목이나 접두어로 노출하지 않는다. 담당자와 위험 안내가 필요하면 `서버 관리자는 다음 상태를 확인해 주세요`, `DB의 template ID는 직접 수정하지 마세요`처럼 실제 의미를 문장 안에 설명한다.

## 2. 상태 확인

```sql
SELECT discussion_id, state, conversation_state, context_version,
       last_seen_post_id, published_post_id, resolved_post_id,
       knowledge_base_post_id, knowledge_base_source_post_id,
       knowledge_base_version, knowledge_base_published_at,
       knowledge_base_solution_selected_at,
       knowledge_base_solution_selected_by_user_id
FROM community_case
ORDER BY updated_at DESC
LIMIT 20;
```

정상 상태:

- 답변 생성 중: `DRAFT_PENDING / ANALYZING`
- 정보 요청 답변 게시: `PUBLISHED / WAITING_RESOLUTION`
- 일반 답변 게시: `PUBLISHED / WAITING_RESOLUTION`
- 질문자 해결 선택 및 KB 최종 지정: `PUBLISHED / RESOLVED`, `knowledge_base_post_id`와 `knowledge_base_solution_selected_at` 존재
- 해결 해제 또는 후속 질문: `PUBLISHED / ANALYZING`

## 3. 로그 확인

```bash
docker logs --since 10m techflow-ai-gateway-community-poller-1 \
  | grep -E 'community_poll_completed|community_post_delivery_failed'

docker logs --since 10m techflow-ai-gateway-gateway-1 \
  | grep -E 'community_answer_auto_published|community_answer_progression_retry|community_answer_progression_rejected|community_knowledge_base_published|community_knowledge_base_solution_selected|community_chat_notification'
```

정상 기준:

- Poller `failed=0`
- 일반 답변: `community_answer_auto_published`
- 해결 최종본: `community_knowledge_base_published`
- KB 최종 솔루션 지정: `community_knowledge_base_solution_selected`
- Chat: `community_chat_notification_sent`

## 4. Chat 사용

Chat은 승인 채널이 아니라 관찰 채널이다.

- `연결`: 게시 알림 수신자로 등록
- `대기`: 처리 중이거나 실패한 Case 조회
- `상세 <Discussion 또는 Case>`: 게시·대화·KB 상태와 원문 링크 조회
- `근거 <Discussion 또는 Case>`: 내부 담당자만 Evidence Ledger 조회
- `이력 [Case]`: 자동 게시와 KB 게시 이벤트 조회

기존 `승인`, `수정`, `반려` 명령은 게시 작업을 수행하지 않고 자동 게시 정책을 안내한다.

## 5. 첨부 처리

- 이미지: PNG, JPEG, WebP
- 텍스트·일반 로그
- 압축 로그: ZIP, GZIP, TAR.GZ
- macOS 메타데이터 `__MACOSX/`, `.DS_Store`, `._*`는 분석에서 제외
- 경로 탈출, 압축 폭탄, 중첩 압축, 바이너리 위장과 비밀정보는 차단

영구 처리 불가 첨부는 안전한 안내로 바꾸고 나머지 질문 처리를 계속한다. 네트워크 오류와 5xx는 Seen 상태를 진행하지 않고 재시도한다.

## 6. 자동 게시 안전장치

- Flarum Assistant 계정으로 글을 작성한다.
- Approval 확장이 글을 보류하면 API 통합 계정이 방금 작성한 정확한 Post만 즉시 승인한다.
- `techflow-answer:<case>:v<version>` 값을 SHA-256한 보이지 않는 0폭 링크로 일반 답변을 멱등 처리한다.
- `techflow-kb:<case>:resolved:<post>` 값도 같은 방식으로 KB를 멱등 처리하며, 원문 Marker나 내부 식별자는 사용자 본문에 표시하지 않는다.
- 근거 부족으로 AI가 `ABSTAINED`를 반환해도 답변을 비워 두지 않고, 버전·발생 시각·로그·화면 등 필요한 정보를 쉬운 문장으로 요청해 자동 게시한다.
- 공개 본문에서 Citation, 저장소, 브랜치, 커밋, 경로, 비밀정보를 제거한다.
- 게시 실패는 503으로 반환해 Poller와 Activepieces가 다시 시도하게 한다.
- 반복 답변은 한 번 재작성한 뒤에도 새 해결 단계가 없으면 공개하지 않는다.
- 기존 승인 대기 초안은 공개 전에 대화체로 변환하고 저장 본문도 동일하게 갱신한다.

## 7. Knowledge Base 생성

KB는 질문자의 Best Answer 선택을 해결 신호로 사용한다.

1. 전체 Turn을 시간순으로 정렬한다.
2. 선택된 Post를 해결 답변으로 표시한다.
3. 선택 답변과 실제 조치 결과를 우선하고 폐기된 가설을 제외한다.
4. 최신 첨부 최대 5개를 다시 검토한다.
5. 제목 없이 다음 형식으로 공개한다.

```text
증상
원인
해결 방법
추가 고려사항
적용 버전
```

6. 통합 API Key와 별도 selector identity로 Discussion의 `bestAnswerPostId`를 KB Post ID로 변경한다.
7. `bestAnswerPost`를 즉시 재조회해 KB Post와 일치할 때만 `KNOWLEDGE_BASE_SOLUTION_SELECTED`를 기록한다.

질문자가 처음 선택한 해결 답변은 `resolved_post_id`와 `knowledge_base_source_post_id`로 유지한다. 최종 Best Answer는 `knowledge_base_post_id`가 되며, 두 값을 서로 덮어쓰지 않는다.

질문자가 해결 선택을 해제하면 기존 KB 기록은 감사 이력에 보존하되 활성 KB 연결은 지우고 Conversation을 재개한다.

## 8. 배포

1. Gateway 소스, Compose와 DB를 백업한다.
2. Secret은 존재와 권한만 확인하고 값을 출력하지 않는다.
3. Migration `0012_community_auto_publish_kb_up.sql`과 `0013_community_kb_solution_up.sql`을 적용한다.
4. 환경 설정을 다음처럼 변경한다.

```dotenv
TECHFLOW_COMMUNITY_PUBLISH_ENABLED=true
TECHFLOW_COMMUNITY_REVIEW_POST_ENABLED=false
TECHFLOW_COMMUNITY_AUTO_PUBLISH_ENABLED=true
TECHFLOW_FLARUM_SOLUTION_SELECTOR_USER_ID_FILE=/run/secrets/flarum_solution_selector_user_id
```

5. `TECHFLOW_FLARUM_SOLUTION_SELECTOR_USER_ID_SECRET_FILE`은 Best Answer 변경 권한이 있는 Flarum 관리자 ID 파일을 가리키게 한다. 시험 서버에서는 검증된 관리자 User 1을 사용한다.
6. Gateway와 Poller만 0.14.4 이미지로 교체한다.
7. Health에서 `version=0.14.4`, `provider=openai`, `database=ready`, `vector=ready`를 확인한다.
8. 기존 GitHub-to-Chat Event Gateway는 재시작·재배포·설정 변경하지 않는다.

OpenAI 시험 환경에서는 재생성 명령에 `compose.openai.override.yml`을 반드시 포함한다. 기본 `compose.yml`만 사용하면 Gateway가 안전 기본값인 Mock Provider로 기동한다.

```bash
docker compose --env-file .env \
  -f compose.yml -f compose.openai.override.yml \
  up -d --no-deps --force-recreate gateway community-poller
```

## 9. 장애 대응

| 증상 | 확인 | 조치 |
| --- | --- | --- |
| 답변 생성 후 공개되지 않음 | `community_answer_auto_publish_failed`, Flarum Post 상태 | API 권한과 Assistant ID를 확인하고 동일 Post 이벤트 재시도 |
| 같은 답변이 중복 게시됨 | 본문 Marker와 Case Draft Version | Marker 검색 권한과 Post 조회 범위 확인 |
| 후속 답변이 같은 점검을 반복함 | `community_answer_progression_retry`, `community_answer_progression_rejected` | 최신 사용자 Turn이 저장됐는지 확인하고, 근거 Context에 구체적인 다음 단계가 있는지 점검 |
| 다른 참여자의 후속 댓글에 답하지 않음 | Poller의 `turnRole`, `responseRequested`, `seenPosts` | 사람 글은 `REQUESTER` 또는 `STAFF`이고 `responseRequested=true`인지, Assistant 글만 false인지 확인 |
| 명령이 설명 문장 안에 섞임 | 공개 Post의 HTML `<pre><code class="language-bash">` | AI Gateway 0.14.4 이상인지 확인하고, 코드 블록 수와 인라인 CLI가 없는지 점검 |
| 해결 표시 후 KB가 없음 | `resolved_post_id`, KB 실패 로그 | 선택 사용자와 최초 질문자 일치 여부, AI 응답과 Flarum API 확인 |
| KB는 있으나 최종 솔루션이 아님 | `knowledge_base_solution_selected_at`, `community_knowledge_base_solution_selection_failed`, Flarum `bestAnswerPost` | selector identity 권한을 확인하고 동일 해결 이벤트를 재시도한다. 기존 KB Post는 재사용한다. |
| Chat 알림만 실패 | `community_chat_notification_failed` | Community 게시 상태를 먼저 확인하고 Chat Bot 연결 복구 |
| 후속 질문이 새 Case로 생성됨 | `discussion_id`, `community_turn` | Poller Discussion ID와 Post ID 정규화 확인 |
| 첨부가 큐를 막음 | Artifact HTTP 상태, Poller Seen 상태 | 영구 오류는 안전 경고로, 일시 오류는 재시도로 분리 |

## 10. 롤백

1. `TECHFLOW_COMMUNITY_AUTO_PUBLISH_ENABLED=false`로 자동 게시를 중단한다.
2. Gateway와 Poller를 직전 이미지로 되돌린다.
3. 필요하면 `TECHFLOW_COMMUNITY_REVIEW_POST_ENABLED=true`로 이전 승인 흐름을 임시 복구한다.
4. Migration Down은 데이터 열을 삭제하므로 별도 승인과 백업 없이는 실행하지 않는다.
5. 이미 공개된 Community 글과 KB를 자동 삭제하지 않는다.
6. `techflow-activepieces-event-gateway-1`은 롤백 범위에서 제외한다.
