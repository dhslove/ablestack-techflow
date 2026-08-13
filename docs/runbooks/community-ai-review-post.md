# Community 원문 승인형 AI 답변 운영 Runbook

## 1. 운영 원칙

Chat은 알림과 검토 진입점이다. 전체 답변의 기준 원문과 승인 화면은 Community Discussion이다. 일반 사용자는 관리자가 승인한 뒤에만 답변을 볼 수 있다.

## 2. 신규 질문 처리

1. Community Poller가 신규 질문과 첨부 링크를 읽는다.
2. 이미지는 원본 바이트를 Artifact API에 등록한다.
3. FoF Upload 첨부는 `/api/fof/download/<uuid>`로 내려받고, 응답 헤더의 파일명을 복원한다.
4. 로그·ZIP·GZIP·TAR.GZ는 안전 제한 안에서 정규화하고 비밀정보를 마스킹한다.
5. Activepieces가 AI Gateway의 Community Case 생성 API를 호출한다.
6. Gateway가 문서, Diplo 중심 소스, 관련 소스, Europa Preview, 공식 플랫폼 자료 순서로 근거를 종합한다.
7. `TechFlow-Assistant` 일반 계정이 전체 답변을 등록한다.
8. Flarum에 `승인 대기 중` 표시가 없으면 처리를 실패시킨다.
9. Chat Bot은 담당자에게 전체 답변 대신 검토 링크를 보낸다.

## 3. 담당자 검토와 승인

1. Chat의 검토 링크를 연다.
2. Community 로그인 상태와 답변 작성자가 `TechFlow-Assistant`인지 확인한다.
3. 다음 항목을 원문에서 검토한다.
   - 증상에는 현상만 있는가
   - 원인은 확정 사실과 가능성을 구분했는가
   - 해결 방법은 서비스 영향이 적은 순서인가
   - 필요한 CLI 확인 명령과 결과 판정이 있는가
   - 이미지 또는 로그의 실제 내용이 반영됐는가
   - Europa 정보가 현재 적용 기능처럼 표현되지 않았는가
4. 이상이 없으면 Community의 `승인`을 누른다.
5. Poller가 승인 상태를 감지해 Case를 `PUBLISHED`로 동기화하는지 확인한다.

수정이 필요하면 답변을 바로 공개하지 말고 수정본을 생성한 뒤 다시 검토한다. 질문이 삭제됐거나 답변하면 안 되는 경우에는 Case를 `REJECTED`로 종료해 재시도를 막고 감사 이력을 보존한다.

## 4. 근거 확인

일반 사용자 화면과 Chat 상세에는 근거 목록을 표시하지 않는다. 내부 Reviewer가 근거를 확인해야 할 때만 Chat에서 다음 형식으로 요청한다.

```text
근거 <Case ID 또는 앞 8자리>
```

응답은 내부 Evidence Ledger의 Source Profile별 수집 여부와 Citation 수를 표시한다. 이 기능은 Reviewer 허용 목록에 포함된 사용자에게만 동작한다.

## 5. 상태 확인

### Gateway와 Poller

```bash
docker ps --format '{{.Names}} {{.Image}} {{.Status}}'
docker logs --since 10m techflow-ai-gateway-community-poller-1 \
  | grep -E 'community_poll_completed|community_chat_notification_sent'
```

정상 기준:

- Gateway가 `healthy`
- 최근 Poll 결과의 `reviewRetryFailed=0`
- 새 초안이 있으면 `community_chat_notification_sent` 기록 존재

### Case 상태

```sql
SELECT discussion_id, state, review_post_id, reviewer, updated_at
FROM community_case
ORDER BY created_at DESC
LIMIT 20;
```

정상 전이:

- 등록 직후: `DRAFT_PENDING`, `review_post_id` 존재
- 관리자 승인 후: `PUBLISHED`, Reviewer가 `flarum:moderator`
- 원본 삭제 또는 명시적 반려: `REJECTED`

## 6. 첨부 진단

### 이미지

- Discussion HTML에 `<img src>`가 있는지 확인한다.
- Gateway Artifact 메타데이터에서 종류가 `IMAGE`인지 확인한다.
- AI 답변이 화면에 실제로 없는 내용을 단정하지 않았는지 확인한다.

### 로그와 압축 로그

- FoF Upload HTML의 `data-fof-upload-download-uuid`가 수집됐는지 확인한다.
- 다운로드 응답의 `Content-Disposition` 파일명이 원래 파일명으로 복원됐는지 확인한다.
- ZIP이면 `kind=LOG`, `entryCount`, `extractedBytes`, `evidenceTruncated`, `redactionCount`를 확인한다.
- 압축 파일을 호스트 파일시스템에 직접 풀지 않는다. Artifact Store의 안전 파서만 사용한다.

## 7. 장애 대응

| 현상 | 확인 | 조치 |
| --- | --- | --- |
| Chat 알림이 없음 | Reviewer 연결, Bot 로그, `community_chat_notification_sent` | 연결 정보를 복구하고 동일 Case를 reconcile |
| 답변이 공개 상태로 바로 보임 | Assistant가 일반 Member인지, API 키가 관리자에게 바인딩됐는지 | 공개 처리를 중단하고 unbound API key + Assistant user ID로 교체 |
| 미승인 Post를 찾지 못함 | 조회 요청이 Assistant 사용자 문맥인지 | `Authorization: Token ...; userId=<assistant>` 경계 확인 |
| 이미지가 분석되지 않음 | `<img src>` 수집과 Artifact ID 생성 | Poller 파서 및 이미지 제한 확인 |
| ZIP이 일반 바이너리로 거부됨 | `Content-Type`, `Content-Disposition`, 확장자 | 허용 확장자 기반 실제 형식 추론 확인 |
| 삭제된 Discussion 재시도 | Case 상태와 Flarum 404 | Case를 감사 가능한 `REJECTED`로 종료 |

## 8. 배포

1. 배포 전 Gateway 소스, Compose, DB를 백업하고 SHA-256을 기록한다.
2. 서버의 런타임 Secret 파일이 존재하는지만 확인한다. 값은 출력하지 않는다.
3. 소스 아카이브를 전송하고 기존 디렉터리 권한을 보존해 푼다.

```bash
tar -xzf issue64.tar.gz --no-overwrite-dir --no-same-owner --no-same-permissions
docker build -t techflow/ai-gateway:issue-64-answer-clarity services/ai-gateway
export TECHFLOW_RAG_RELEASE=issue-64-answer-clarity
docker compose -f compose.yml -f compose.openai.override.yml \
  up -d --no-deps --force-recreate gateway community-poller
```

단일 `compose.yml`만 사용하면 기본값 `provider=mock`으로 되돌아갈 수 있으므로 OpenAI Override를 생략하지 않는다. 배포한 Compose에 `flarum_assistant_user_id` Secret 선언과 Gateway·Poller Mount가 모두 있는지도 확인한다.

4. Health가 `provider=openai`, `version=0.12.0`인지 확인하고 DB migration `0010`, Poller, 텍스트·이미지·ZIP E2E를 검증한다.
5. 보호 대상 `techflow-activepieces-event-gateway-1`의 Container ID, Image, StartedAt이 배포 전과 같은지 비교한다.

## 9. 롤백

1. 신규 Community 답변 공개를 중지하고 미승인 Post는 그대로 보존한다.
2. Gateway와 Poller만 직전 이미지·Compose로 되돌린다.
3. 필요하면 `0010_flarum_review_post_down.sql`, 이어서 `0009_chat_approval_down.sql`을 적용한다.
4. 백업 DB 복원은 스키마 롤백으로 해결되지 않는 경우에만 수행한다.
5. GitHub→Chat 웹훅 서비스는 롤백 대상에서도 제외한다.
