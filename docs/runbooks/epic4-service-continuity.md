# Epic #4 Chat·Community 서비스 연속성 Runbook

## 1. 운영 원칙

TechFlow AI Gateway 0.15.0은 Chat 직접 상담과 Community 자동 답변을 함께 운영한다. 정상 상태를 주기적으로 Chat에 알리지 않는다. 같은 장애의 최초 발생과 실제 복구 전환만 알린다. 질문·답변·로그 원문은 장애 큐와 KPI에 복제하지 않는다.

GitHub→Chat Webhook의 `github-chat-v1`, `chat-adapter`, `activepieces-control`은 보호 서비스다. 이 Runbook의 배포·재기동·장애 주입 대상이 아니다.

## 2. Chat 연속 상담

1. 사용자가 Synology Chat의 `TechFlowAssist` Bot에 기술 질문을 입력한다.
2. Gateway는 사용자 ID별 활성 Conversation을 열고 User Turn과 지속 Chat Job을 기록한다.
3. Webhook에는 2초 이내 접수 확인을 반환하고 AI 분석은 요청 수명과 분리한다.
4. Job은 사용자별로 직렬 실행하며 같은 Context Version의 최근 Turn을 현재 질문과 함께 검토한다.
5. DOC, ABLESTACK Diplo, Wall·Cockpit·Genie·Kickstart·QEMU 도구, ABLESTACK Europa Preview 순서로 종합한다.
6. 완료 답변은 Synology Chatbot API로 질문자에게 능동 전송한다.
7. 실패 Job은 지수 재시도하고, 한도 초과 시 사용자 안내와 Dead Letter를 기록한다.
8. 사용자가 `해결`을 입력하면 같은 Context의 진행 중 Job을 취소하고 다음 질문은 새 Context Version으로 시작한다.

일반 답변에는 Repository·Branch·Commit·Path·Line·Evidence ID를 표시하지 않는다. 권한 있는 담당자의 `근거 <Case>` 명령만 Community Case의 내부 근거를 표시한다.

## 3. Community 연속성

Poller는 Activepieces Webhook 수락만으로 게시물을 완료하지 않는다. Gateway Case의 `lastSeenPostId`가 현재 Flarum Post ID와 일치하는 것을 확인한 뒤에만 Post ID를 원자적으로 체크포인트한다. 다운로드·Artifact·Webhook·AI 처리·Gateway 확인 중 하나라도 실패하면 해당 Post ID를 완료 처리하지 않으므로 다음 주기에 다시 시도한다. Gateway는 Flarum Post ID 기반 Event ID와 Idempotency Key로 같은 답변이 중복 게시되는 것을 막는다.

Gateway 확인 제한시간은 기본 600초이며 `TECHFLOW_COMMUNITY_GATEWAY_CONFIRM_TIMEOUT_SECONDS`로 조정한다. 제한시간이 지나면 `community_post_delivery_failed`를 기록하고 장애 상태를 Chat에 한 번 알린다. 같은 Post가 이후 성공하면 복구 상태로 전환한다.

운영 Poller의 Flarum API 주소는 내부 경로 `http://172.16.0.234`이고 사용자에게 제공하는 링크는 `https://community.ablecloud.io`다. 외부 공개 주소를 운영 서버의 수집 경로로 바꾸지 않는다.

해결 답변이 선택될 때까지 Discussion의 Turn을 누적한다. 이미지·로그·압축파일은 Artifact ID만 Conversation에 연결하며, 파일 원문은 보존 정책에 따라 격리·삭제한다. 해결 선택 후 KB 최종본 게시와 솔루션 지정까지 같은 Case로 추적한다.

## 4. 장애·복구 상태

`operation_failure`는 다음 상태만 저장한다.

- `OPEN`: 최초 실패, 1초 뒤 재시도 가능
- `RETRYING`: 운영자가 수동 재처리를 요청함
- `DEAD_LETTER`: 기본 3회 실패하여 자동 재시도 한도를 초과함
- `RECOVERED`: 동일 Fingerprint 작업이 다시 성공함

재시도 간격은 1, 2, 4초 기준의 지수 백오프로 늘어난다. Community Poller의 정상 주기는 별도 설정값을 따른다. 수동 재처리는 다음 API로 큐 상태를 `RETRYING`으로 전환한 뒤 Poller가 같은 미완료 Event를 다시 가져가게 한다.

```bash
curl -sS -X POST "http://gateway:8090/v1/operations/failures/<Failure-ID>/retry" \
  -H "X-Correlation-Id: manual-retry-<unique>" \
  -H "Idempotency-Key: manual-retry-<unique>"
```

## 5. 상태·KPI 확인

```bash
curl -sS "http://gateway:8090/v1/operations/failures?state=OPEN,RETRYING,DEAD_LETTER" \
  -H "X-Correlation-Id: operations-check-<unique>"

curl -sS "http://gateway:8090/v1/operations/kpis?windowHours=24" \
  -H "X-Correlation-Id: kpi-check-<unique>"
```

KPI 응답은 Community 게시·해결·추가 정보 요청, Chat 대화·해결·Turn, 장애·복구·Dead Letter, DOC·Diplo·관련 코드·Europa Preview 검토와 Artifact 처리 건수만 제공한다. 원문 질문·답변·로그·Source 경로는 포함하지 않는다.

## 6. 배포

Windows 체크아웃에서도 셸 스크립트를 LF로 고정하기 위해 일반 `git archive`를 직접 사용하지 않는다.

```bash
python tools/package_ai_gateway.py \
  --revision HEAD \
  --output tmp/ai-gateway-release.tar.gz
```

배포 전 DB와 AI Gateway 설정을 백업한다. `0014_epic4_operations_up.sql`을 적용한 뒤 Gateway와 Community Poller만 새 이미지로 교체한다. `github-chat-v1`을 포함한 보호 서비스의 Container ID·Image ID·StartedAt을 전후 비교한다.

## 7. 완료 점검

- Chat 질문 2회가 같은 Context Version에 기록되고 `해결` 뒤 새 Context가 열림
- Community 미답변 글이 자동 게시되고 후속 Turn과 해결 상태가 이어짐
- 실패 Post가 seen 처리되지 않고 같은 Event ID로 재처리됨
- 같은 장애 알림 1회, 복구 알림 1회, 정상 주기 알림 0회
- Dead Letter와 수동 재처리가 동작함
- KPI에 원문 또는 내부 Source 상세가 없음
- Gateway·Poller가 Healthy이고 Community HTTPS가 200임
- GitHub→Chat 보호 서비스의 런타임 식별자가 배포 전후 동일함

## 8. 롤백

Gateway·Poller 이미지를 직전 Digest로 되돌린다. 신규 테이블은 하위 호환이며 서비스 롤백만으로 기존 경로가 복구된다. 스키마 제거가 꼭 필요한 경우에만 백업 확인 후 `0014_epic4_operations_down.sql`을 실행한다. Community의 이미 게시된 답변과 KB는 자동 삭제하지 않는다.
