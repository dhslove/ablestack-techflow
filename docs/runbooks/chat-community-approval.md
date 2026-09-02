# Chat 기반 Community 승인 배포·운영 Runbook

## 1. 보호 경계

배포 전후 다음 보호 가드를 실행한다.

```bash
python deploy/compose/activepieces/scripts/protected_service_guard.py \
  --lock deploy/compose/activepieces/protected-services.json \
  --env-file deploy/compose/activepieces/.env.example \
  --compose deploy/compose/activepieces/compose.yml \
  --ingress deploy/compose/activepieces/ingress/Caddyfile
```

결과는 `protected_service=github-chat-v1 state=frozen guard=passed`여야 한다. 기존 `/techflow/hooks/*`, GitHub Flow, Event Gateway와 Chat Adapter는 변경·재배포하지 않는다.

## 2. Secret과 설정

GitHub Actions Secret은 다음 이름을 사용한다.

- `TECHFLOW_CHAT_BOT_TOKEN`
- `TECHFLOW_FLARUM_API_KEY`
- `TECHFLOW_COMMUNITY_APPROVE_WEBHOOK_URL`
- `TECHFLOW_COMMUNITY_REJECT_WEBHOOK_URL`

서버에서는 실제 값을 `.secrets`의 보호 파일로만 두고 Compose에는 파일 참조를 전달한다.

```text
TECHFLOW_CHAT_BOT_ENABLED=true
TECHFLOW_CHAT_BASE_URL=https://chat.ablecloud.io
TECHFLOW_CHAT_BOT_TOKEN_SECRET_FILE=/protected/path/chat-bot-token
TECHFLOW_CHAT_REVIEWER_USERNAMES=<허용된 사용자 이름 목록>
TECHFLOW_COMMUNITY_APPROVE_WEBHOOK_SECRET_FILE=/protected/path/community-approve-webhook
TECHFLOW_COMMUNITY_REJECT_WEBHOOK_SECRET_FILE=/protected/path/community-reject-webhook
```

Flarum 서버 간 전송은 시험망의 사설 경로 `http://172.16.0.234`, 사용자에게 보여 주는 링크는 `https://community.ablecloud.io`로 분리한다. Token, Webhook URL, API Key, 비밀번호와 인증 응답은 로그·문서·Git에 기록하지 않는다.

## 3. Synology Chat Bot 설정

1. `프로필 → 통합 → 봇`에서 Bot 이름과 설명을 생성한다. 단순 Incoming/Outgoing Webhook 유형으로 대체하지 않는다.
2. Outgoing URL을 `https://techflow.ablecloud.io/techflow/chat/assist`로 설정한다.
3. 생성된 Token을 GitHub Secret과 서버 보호 파일에 주입한다.
4. 담당자는 Bot 대화에서 `연결`을 한 번 실행한다.
5. `대기`, `상세`, `근거`, `이력`으로 연결과 권한을 확인한다.

Bot Token은 URL·문서에 직접 복사하지 않는다. 사용자가 보낸 명령은 Outgoing URL에서 검증하고, Gateway가 먼저 보내는 알림은 Bot 설정의 받는 URL과 동일한 `SYNO.Chat.External method=chatbot version=2` 계약을 사용한다. `method=incoming`은 Incoming Webhook 전용이므로 Bot Token과 함께 사용하지 않는다.

## 4. 사전 백업

시험 서버 배포 전 다음을 `/home/ablecloud/techflow-ai-gateway/backups/issue22-predeploy-<UTC>`에 저장한다.

- AI Gateway PostgreSQL Custom Dump
- AI Gateway와 Activepieces Compose
- Caddy Ingress 설정
- 직전 Gateway Image ID
- 배포 대상 Source
- `SHA256SUMS`

배포 전에 `sha256sum -c SHA256SUMS`를 실행하고, 백업 디렉터리와 파일 권한이 운영 기준을 충족하는지 확인한다.

## 5. 배포 절차

1. 새 Gateway 이미지를 `techflow/ai-gateway:issue-22-chat-approval`로 빌드한다.
2. `0009_chat_approval_up.sql`을 적용한다.
3. Schema가 22개 Table이고 `chat_reviewer_identity`가 존재하는지 확인한다.
4. AI Gateway를 Activepieces `automation` Network의 고정 주소 `172.30.19.3`으로 기동한다.
5. Community Poller는 충돌을 피하도록 `172.30.19.4`로 고정한다.
6. Caddy Ingress를 `automation_egress` Network에 추가하고 Chat 전용 Route를 적용한다.
7. Gateway와 Poller만 재생성한다. GitHub Chat 보호 서비스는 건드리지 않는다.
8. Health, 외부 위조 요청 403, Chat 연결·대기·이력을 확인한다.

```bash
curl -fsS http://127.0.0.1:18090/healthz
curl -sS -o /dev/null -w '%{http_code}' \
  -X POST https://techflow.ablecloud.io/techflow/chat/assist \
  -d 'token=invalid&text=help'
```

두 번째 명령은 `403`이어야 한다.

## 6. 담당자 운영 절차

1. `대기`로 검토 대상 Case를 찾는다.
2. `상세 <Case>` 또는 알림 버튼으로 질문과 답변 초안만 확인한다. 기본 상세에는 Citation과 Source Coverage가 표시되지 않는다.
3. 내부 근거 검토가 필요한 경우에만 `근거 <Case>`를 명시적으로 실행해 Citation, 전체 Coverage, 현재판·프리뷰 판정을 확인한다.
4. 초안이 그대로 적합하면 `승인 <Case> <Version>`을 실행한다.
5. 수정이 필요하면 `수정 <Case> <Version> <최종 답변>`을 실행한다.
6. 근거가 부족하거나 부적합하면 `반려 <Case> <Version> <사유>`를 실행한다.
7. `이력` 또는 `이력 <Case>`로 최종 상태와 Reviewer를 확인한다.

Chat에 표시된 최종 상태가 `PUBLISHED`인 경우에만 Community 게시 완료로 판정한다. 단순 Webhook HTTP 200은 성공 판정 기준이 아니다.

신규 미답변 Discussion은 Poller가 10초 간격으로 확인하며, 최초 Case 생성 시 연결된 담당자에게 “새 Community 글이 등록되어 검토가 필요합니다” 알림을 자동 전송한다. 전송은 최대 3회 재시도되고 같은 Discussion의 중복 Event에는 다시 알리지 않는다. 알림이 오지 않으면 Poller의 `community_poll_completed`, Gateway의 `community_chat_notification_sent|failed|skipped` 구조화 로그와 Reviewer 연결 상태를 확인한다. `bot type error`가 기록되면 Bot 발송 메서드가 `chatbot`인지 우선 확인한다.

## 7. 영구 삭제된 원본 정리

원본 Discussion이 영구 삭제되면 게시를 재시도하지 않는다. 운영자는 삭제 사실을 확인한 뒤 Case를 `REJECTED`로 전환하고 Reviewer를 `techflow:source-deletion-reconcile`로 기록한다. 감사 Event에는 Discussion ID, 확인 시각과 사유를 남기되 삭제된 원문을 복원하거나 저장하지 않는다.

Discussion #143은 이 절차로 정리했다. 이후 `대기`에서 제외되고 `이력`에 삭제 정리 Reviewer가 표시되는지 확인했다.

## 8. 롤백

1. `TECHFLOW_CHAT_BOT_ENABLED=false`로 Chat 경로를 Fail-closed 처리한다.
2. Gateway Image와 Compose를 사전 백업본으로 복구한다.
3. Caddy의 `/techflow/chat/assist` 블록과 Gateway Network 연결만 되돌린다.
4. 기존 `/techflow/hooks/*`, Event Gateway, GitHub Chat Flow는 그대로 유지한다.
5. Migration Down은 Reviewer 연결 이력을 삭제하므로 제품 책임자의 명시적 승인과 DB Dump 검증 후에만 실행한다.
6. 이미 게시된 Community 답변은 자동 삭제하지 않는다.

## 9. 점검 명령

```bash
docker ps --format '{{.Names}}|{{.Image}}|{{.Status}}'
docker run --rm --user 0:0 \
  -v /home/ablecloud/techflow-ai-gateway:/workspace:ro \
  -w /workspace/services/ai-gateway \
  --entrypoint python techflow/ai-gateway:issue-22-chat-approval \
  -m unittest discover -s tests -p 'test_*.py'
docker exec techflow-ai-gateway-database-1 \
  psql -U techflow_bootstrap -d techflow_rag -Atc \
  "select count(*) from pg_catalog.pg_tables where schemaname='public';"
```

## 10. 한글 누적 대화의 입력 상한과 복구

Chat 질문은 평문으로 입력한다. 사용자에게 JSON이나 정해진 질문 양식을 요구하지 않는다.
Gateway는 누적 대화를 Embedding으로 검색하기 전에 다음 Byte 상한을 적용한다.

- Chat 문맥: UTF-8 7,936 Byte 이하
- 검색어 확장: UTF-8 4,000 Byte 이하
- 최신 질문 우선 보존, 오래된 Turn부터 제거

Gateway가 Healthy인데 `ProviderContractError`로 같은 Chat Job이 반복 실패하고 Provider
감사 기록이 없다면, 문맥의 문자 수뿐 아니라 `octet_length(content)` 합계를 확인한다.
한글은 문자 수보다 UTF-8 Byte가 크므로 `length(content)`만으로 판정하지 않는다.

수정 Image 배포 후 기존 Dead Letter 질문을 복구할 때는 먼저 해당 Job 메타데이터만
백업한다. 질문 원문과 Bot Token은 운영 증적에 복사하지 않는다. 정확한 Job ID와
`DEAD_LETTER` 상태를 확인한 경우에만 Attempt를 0으로 초기화하고 `RETRYING`으로 전환한
뒤 Gateway를 재생성한다. 시작 시 Gateway가 대기 Job을 회수한다.

완료 기준은 다음과 같다.

- Job `COMPLETED`
- Assistant Turn 한 건 생성
- `chat_async_answer_sent` 기록
- Provider 감사 기록 `SUCCEEDED`
- Operation Failure `RECOVERED`
- Community Poller와 GitHub→Chat Event Gateway의 Container ID·Image·StartedAt 불변
