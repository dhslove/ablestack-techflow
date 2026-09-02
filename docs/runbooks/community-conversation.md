# Community 자동 답변과 Knowledge Base 운영 Runbook

## 1. 정상 처리 흐름

1. 질문자가 Discussion이나 후속 댓글을 등록한다.
2. Poller가 새 Post와 이미지·로그·압축 로그를 수집한다.
3. AI Gateway가 기존 대화, ABLESTACK 문서와 코드, 승인된 플랫폼 자료를 함께 분석한다. 로컬 공식 자료가 없거나 오래된 경우에만 제품별 공식 도메인을 제한 검색한다.
4. `TechFlow-Assistant`가 이해하기 쉬운 대화체 답변을 바로 공개한다.
5. Chat Bot이 게시 결과와 Community 링크를 담당자에게 알린다.
6. 질문자가 추가 정보나 후속 질문을 올리면 같은 Case에서 분석과 답변을 반복한다. `TechFlow-Assistant` 자신의 Post는 재응답하지 않는다.
7. 관리자·지원 담당자와 일반 참여자의 댓글은 대화 문맥에만 저장하고 자동 답변하지 않는다. AI 검토가 필요하면 인용문이나 코드 블록 밖에서 `@TechFlow-Assistant 검토해 주세요` 또는 줄 시작 `/ai`로 명시적으로 요청한다.
8. 최초 질문자 또는 운영 설정에 등록된 Community 관리자가 Best Answer를 선택하면 해당 답변 중심의 Knowledge Base 최종본을 게시한다.
9. KB 공개를 확인한 뒤 해당 KB Post를 최종 Best Answer로 지정하고 Flarum 재조회 결과가 일치하는지 확인한다.
10. 해결 표시가 해제되거나 질문자의 후속 질문이 생기면 같은 Case를 다시 연다.

진행 중 답변에는 고정된 문서 형식을 강제하지 않는다. 해결 후 KB에만 `증상`, `원인`, `해결 방법`, `추가 고려사항`, `적용 버전`을 사용하며 별도 제목은 붙이지 않는다.

후속 답변은 다음 순서를 지킨다.

1. 최신 질문에 직접 답하고 가장 가능성이 높은 안전한 해결 방법을 먼저 제시한다.
2. 근거가 있는 경우 실행 위치, 정확한 CLI 명령과 정상 판정 기준을 함께 제공한다. 설명은 문장으로 먼저 쓰고 CLI는 Linux의 `bash`, Windows의 `powershell` 독립 코드 블록에 표시한다.
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
- 최초 질문자 또는 등록 관리자 해결 선택 및 KB 최종 지정: `PUBLISHED / RESOLVED`, `knowledge_base_post_id`와 `knowledge_base_solution_selected_at` 존재
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

### 5.1 공식 웹 보완

- 공개 제품명은 Mold, Glue, Koral, Wall을 사용한다.
- 내부 검색에서는 Mold→CloudStack과 필요 시 libvirt/QEMU/KVM, Glue→Ceph, Koral→Kubernetes, Wall→Grafana 용어를 함께 사용한다.
- 로컬 공식 자료가 없거나 30일 갱신 기한을 넘겼을 때만 검색한다.
- 허용 도메인은 Ubuntu·Red Hat·Rocky·Microsoft·QEMU·libvirt·Ceph·Kubernetes·Grafana·Apache CloudStack 공식 사이트로 제한한다.
- 질문의 URL, 이메일, IP와 비밀정보 형태를 제거한 뒤 검색하며 첨부파일과 로그 본문은 보내지 않는다.
- 도구의 실제 Source 목록과 일치하는 HTTPS URL만 내부 Context로 수용한다.
- 공식 웹 자료는 ABLESTACK 제품 문서나 현재 Diplo 구현을 덮어쓸 수 없다.
- 사용자 답변에는 공식 URL과 내부 Citation을 노출하지 않는다.

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

KB는 최초 질문자 또는 운영 설정에 등록된 Community 관리자의 Best Answer 선택을 해결 신호로 사용한다. 다른 참여자의 선택은 해결 신호로 인정하지 않는다.

1. 전체 Turn을 시간순으로 정렬한다.
2. 승인된 선택자가 고른 Post를 해결 답변으로 표시한다.
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

최초 질문자 또는 등록 관리자가 처음 선택한 해결 답변은 `resolved_post_id`와 `knowledge_base_source_post_id`로 유지한다. 최종 Best Answer는 `knowledge_base_post_id`가 되며, 두 값을 서로 덮어쓰지 않는다.

해결 선택이 해제되면 기존 KB 기록은 감사 이력에 보존하되 활성 KB 연결은 지우고 Conversation을 재개한다.

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
TECHFLOW_FLARUM_SUPPORT_USER_IDS=7,13
```

5. `TECHFLOW_FLARUM_SOLUTION_SELECTOR_USER_ID_SECRET_FILE`은 Best Answer 변경 권한이 있는 Flarum 관리자 ID 파일을 가리키게 한다. 시험 서버에서는 검증된 관리자 User 1을 사용한다.
6. 추가 해결 관리자가 있다면 `.env`의 `TECHFLOW_FLARUM_RESOLUTION_ADMIN_USER_IDS`에 Flarum User ID를 쉼표로 구분해 설정한다. 최종 KB selector User ID는 자동으로 관리자에 포함된다.
7. 답변을 직접 제공하는 지원 담당자는 `TECHFLOW_FLARUM_SUPPORT_USER_IDS`에 등록한다. 해결 관리자와 최종 KB selector는 자동으로 지원 담당자 집합에도 포함되므로 중복 등록하지 않아도 된다. 이 값은 응답 억제 사유를 구분하기 위한 신뢰된 서버 설정이며, 등록되지 않은 일반 참여자의 댓글도 기본적으로 AI를 호출하지 않는다.
8. Windows와 Linux에서 동일한 LF 기반 소스 패키지를 생성한다. Windows Git의 전역 `core.autocrlf=true`가 `git archive` 결과를 CRLF로 변환할 수 있으므로 일반 `git archive`를 직접 사용하지 않는다.

```bash
python tools/package_ai_gateway.py \
  --revision HEAD \
  --output tmp/ai-gateway-release.tar.gz
```

9. 패키지 안의 모든 `*.sh`에 CRLF가 없는지 확인한 뒤 Gateway와 Poller만 0.16.8 이상 이미지로 교체한다. `/usr/bin/env: sh\r: No such file or directory`가 나타나면 새 이미지를 배포하지 말고 패키징 단계부터 다시 수행한다.
10. Health에서 `version=0.16.8` 이상, `provider=openai`, `database=ready`, `vector=ready`를 확인한다.
11. `.env`에 `TECHFLOW_OFFICIAL_WEB_SEARCH_ENABLED=true`를 설정하고 공식 도메인 제한 실호출을 검증한다.
12. 기존 GitHub-to-Chat Event Gateway는 재시작·재배포·설정 변경하지 않는다.

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
| 관리자 답변 뒤 AI가 다시 답변함 | Poller의 `turnRole`, `responseRequested`, `responseReason` | 관리자의 일반 답변은 `STAFF`, `false`, `STAFF_RECORDED`인지 확인하고 지원 담당자 ID 설정을 점검 |
| 관리자가 AI 검토를 요청했지만 답변하지 않음 | 최신 Post의 HTML과 `responseReason` | 인용문·코드 밖에서 `@TechFlow-Assistant` 또는 줄 시작 `/ai`를 사용했는지 확인 |
| 일반 참여자 댓글 뒤 AI가 다시 답변함 | Poller의 `responseRequested`, `responseReason` | 일반 참여자는 `false`, `PARTICIPANT_RECORDED`가 정상이며 명시 호출만 `EXPLICIT_AI_REQUEST`인지 확인 |
| 명령이 설명 문장 안에 섞임 | 공개 Post의 HTML `<pre><code class="language-bash">` | AI Gateway 0.14.4 이상인지 확인하고, 코드 블록 수와 인라인 CLI가 없는지 점검 |
| 긴 대화의 Activepieces HTTP 단계가 `ValidationError`로 실패 | Gateway `request_failed`, Conversation·검색 확장 길이 | AI Gateway 0.14.5 이상인지 확인한다. 실패 Post가 Poller 체크포인트에 이미 있으면 기존 Community Webhook으로 해당 이벤트를 한 번 재전달하고 HTTP 201과 새 Assistant Post를 확인한다. |
| 해결 표시 후 Activepieces HTTP 단계가 `ValidationError`로 실패 | KB 종합 Prompt 길이, `knowledgeBaseSourcePostId` | AI Gateway 0.14.6 이상인지 확인한다. 일반 질의 4,000자와 내부 KB 종합 16,000자 계약이 분리됐는지 확인하고 동일 해결 이벤트를 재시도한다. 기존 해결 Post는 원본으로 유지한다. |
| 해결 표시 후 KB가 없음 | `resolved_post_id`, `RESOLVED_BY_REQUESTER` 또는 `RESOLVED_BY_ADMINISTRATOR`, KB 실패 로그 | 선택자가 최초 질문자 또는 등록 관리자에 해당하는지와 AI 응답·Flarum API 확인 |
| KB는 있으나 최종 솔루션이 아님 | `knowledge_base_solution_selected_at`, `community_knowledge_base_solution_selection_failed`, Flarum `bestAnswerPost` | selector identity 권한을 확인하고 동일 해결 이벤트를 재시도한다. 기존 KB Post는 재사용한다. |
| Chat 알림만 실패 | `community_chat_notification_failed` | Community 게시 상태를 먼저 확인하고 Chat Bot 연결 복구 |
| 후속 질문이 새 Case로 생성됨 | `discussion_id`, `community_turn` | Poller Discussion ID와 Post ID 정규화 확인 |
| 첨부가 큐를 막음 | Artifact HTTP 상태, Poller Seen 상태 | 영구 오류는 안전 경고로, 일시 오류는 재시도로 분리 |
| 이미지가 글에는 보이지만 답변에서 확인하지 못함 | Activepieces 최초 Webhook의 `artifactIds`, `artifactWarnings`, Poller의 첨부 참조 수 | 인라인 이미지 참조 1건마다 Artifact ID 또는 처리 경고가 1건 생겨야 한다. 둘 다 0이면 Poller 0.14.9 이상으로 교체하고 해당 Post를 재처리한다. 실패 기록이 없는데 KB에 다운로드 실패 문구가 있으면 게시 내용을 교정한다. |
| OS 설치 방법을 다른 관리자에게 넘김 | OS 이름과 로컬 공식 자료 검색 결과 | 0.14.7 이상인지 확인하고 Ubuntu·RHEL/Rocky·Windows 설치 스냅샷이 Context에 포함됐는지 확인 |
| Glue·Koral·Wall·Mold 질문의 기반 자료가 부족함 | `official_web_search_completed`, 내부 Citation의 허용 도메인과 수집 시각 | 운영 플래그와 OpenAI 모드를 확인하고 비허용 도메인 결과는 폐기 |
| 명백한 제품 식별자 오타를 다시 확인함 | 직전 Assistant Turn의 정식 식별자와 최신 사용자 Token | 단일 후보만 오타로 가정한다고 한 번 알리고 핵심 증상 분석을 계속한다. 상태·IP·UUID·명령·로그 원문은 자동 교정하지 않는다. |
| 명령은 있지만 어디서 실행할지 알 수 없음 | `community_answer_progression_retry`의 `actionabilityIssues` | 실행 대상, `ssh -p <SSH_PORT> <ADMIN>@<IP>` 또는 콘솔, 권한, 정확한 `.service`, 정상 기준을 포함해 Provider가 재작성하도록 한다. |
| 로그 요청에 경로·시간 범위가 없음 | `missing-log-source`, `missing-time-window`, `missing-redaction-guidance` | `journalctl -u <service> --since ... --until ...` 또는 승인된 `/var/log/...` 경로와 공개 마스킹 방법을 포함한다. |
| 기존 Assistant Post를 교정했지만 다음 질문에서 옛 답변을 사용함 | Flarum Post, `community_case.draft_answer`, 최신 `community_response`, 동일 `community_turn` | 같은 Post ID의 교정 경로로 네 위치를 함께 갱신하고 `AUTO_PUBLISHED_CORRECTED` 이벤트를 확인한다. |

### 9.1 본문과 첨부자료 제한

- Community 글·댓글 원문 텍스트: 최대 16,000자 수신·보관
- 일반 AI 질의 Prompt: 최대 4,000자, 초과 시 최초 질문·최신 질문 앞뒤·직전 답변·필수 지침을 보존해 재구성
- 해결 후 내부 KB 종합 Prompt: 최대 16,000자
- 첨부파일 1개: 최대 10MB
- 압축 해제 합계: 최대 20MB, 항목 100개, 압축률 20배
- 분석용 로그 증거: Artifact당 최대 120,000자
- 한 AI 질의에 연결하는 Artifact: 최대 5개

본문 글자 수에는 이미지·첨부파일·로그·압축 로그의 바이트나 추출 문자열을 더하지 않는다. Artifact는 별도 저장·검역한 뒤 식별자와 관련 증거 구간만 질의에 연결한다.

`적용 버전`에는 해결 방법을 실제 적용해도 되는 공개 제품 버전만 적는다. 내부 Diplo 상태 판정, Europa Preview 비교, 개선 미확인, 제품 보완 검토는 Evidence Ledger에만 유지하고 Community KB에는 표시하지 않는다.

### 9.2 오타 완화와 실행 가능한 운영 안내

- 영문 제품 식별자는 이전 TechFlow 답변의 정식 표기와 비교한다. 첫 세 글자가 같고 유사도 0.90 이상인 단일 후보만 오타 후보로 사용한다.
- 사용자 원문은 변경하지 않는다. 답변에서 “문맥상 오타로 보고 진행한다”고 한 번 알린 뒤 최신 상태 분석을 계속한다.
- `Available`, `Suspect`, `Degraded`, IP, UUID, 버전, 포트, 명령, 경로, API 이름, 화면·로그 원문, Citation ID, Artifact ID는 자동 교정하지 않는다.
- `systemctl`, `journalctl`, `virsh`, `grep`, `tail`이 있으면 실행 대상·접속 예시·권한·정확한 Unit·정상 기준이 있어야 한다.
- 로그 요청에는 정확한 `/var/log/...` 경로 또는 `journalctl -u <service>`, `--since`·`--until`, 비밀정보와 내부 인프라 식별자 마스킹 방법이 있어야 한다.
- 현재 승인된 공개 운영 로그 경로는 `/var/log/cloudstack/management/management-server.log`와 `/var/log/cloudstack/agent/agent.log`다. 저장소 Source 경로와 내부 Citation 경로는 계속 숨긴다.
- 1차 답변이 계약을 충족하지 않으면 누락 Code를 포함해 한 번 재작성한다. 2차 답변도 실패하면 공개 게시하지 않고 재처리 대상으로 남긴다.

## 10. 롤백

1. `TECHFLOW_COMMUNITY_AUTO_PUBLISH_ENABLED=false`로 자동 게시를 중단한다.
2. Gateway와 Poller를 직전 이미지로 되돌린다.
3. 필요하면 `TECHFLOW_COMMUNITY_REVIEW_POST_ENABLED=true`로 이전 승인 흐름을 임시 복구한다.
4. Migration Down은 데이터 열을 삭제하므로 별도 승인과 백업 없이는 실행하지 않는다.
5. 이미 공개된 Community 글과 KB를 자동 삭제하지 않는다.
6. `techflow-activepieces-event-gateway-1`은 롤백 범위에서 제외한다.
