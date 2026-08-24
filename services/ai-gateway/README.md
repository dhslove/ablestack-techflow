# TechFlow AI Gateway

## v0.15.1 수정 범위

- Flarum 답글 멘션과 일반 링크를 첨부파일 후보에서 제외
- 내부 Flarum 주소로 렌더링된 이미지도 신뢰된 내부 Origin으로 안전하게 수집
- 여러 첨부파일이 같은 경고를 만들 때 순서를 유지하며 고유한 경고로 정규화
- Activepieces Webhook 수락 후 Gateway의 `lastSeenPostId` 확인 전에는 Poller 체크포인트 금지
- Gateway 처리 실패·지연 시 Post를 미완료 상태로 유지하고 다음 Poll에서 재시도
- 기존 Discussion에 Case가 없으면 현재 후속 질문 1건에 앞선 질문·지원 답변·첨부를 합쳐 한 번만 분석
- 답변 요청 Event는 Gateway Case가 `PUBLISHED`이고 게시물 ID가 확인된 뒤에만 완료
- 제한된 Assistant 게시물 승인 해제는 Solution Selector 관리자 Identity로 수행

## v0.15.0 구현 범위

- Chat 기술지원 대화를 사용자별 맥락으로 유지하고 `해결` 시점에 종료
- Community 실패 이벤트의 체크포인트 보류·동일 Event ID 재처리·중복 답변 방지
- 지수 백오프, Dead Letter, 수동 재처리와 최초 장애·최초 복구 Chat 알림
- 원문을 포함하지 않는 Community·Chat·Source Coverage·첨부·장애 KPI
- Windows와 Linux에서 동일한 LF 셸 스크립트 배포 패키지 생성 계약

- Discussion #169에서 확인된 인라인 이미지 누락을 막기 위해 Flarum 첨부 참조 수와 Artifact 처리 결과를 대조합니다.
- 첨부 참조는 Artifact ID 또는 명시적 처리 경고로 끝나야 하며, 실제 실패 기록이 없는 Knowledge Base에는 다운로드 실패 문구를 허용하지 않습니다.
- 최종 Knowledge Base 솔루션 확인 이벤트는 운영 DB의 `varchar(32)` 경계를 지키는 `KB_SOLUTION_CONFIRMED`로 기록합니다.
- Ubuntu·RHEL/Rocky·Windows 게스트에서 QEMU Guest Agent 설치·시작·검증 절차를 승인된 로컬 공식 자료로 제공합니다.
- 질문자가 가상머신 관리자라는 전제에서 실행 위치와 복사 가능한 `bash`·`powershell` 명령을 먼저 안내하며, 단순히 시스템 관리자에게 위임하지 않습니다.
- 로컬 공식 자료가 없거나 30일 갱신 기한을 넘긴 경우에만 공식 도메인 제한 웹 검색을 수행하고, 도구가 실제 반환한 공식 URL의 사실만 내부 근거로 사용합니다.
- Glue 질문은 Ceph, Koral 질문은 Kubernetes, Wall 질문은 Grafana 공식 문서로 보완하되 공개 제품명은 Glue·Koral·Wall로 유지합니다.
- 공식 웹 근거는 ABLESTACK 문서·Diplo·연관 제품 코드·Europa Preview 검토를 대체하지 않으며, 사용자에게 내부 출처 URL을 노출하지 않습니다.

## v0.14.6 구현 범위

- 일반 AI 질의는 4,000자 계약을 유지하고, 4,000자를 넘는 Community 대화는 최초 질문·최신 질문의 앞뒤·직전 답변·필수 지침을 보존해 자동 압축합니다.
- Community 글 본문은 최대 16,000자로 수신·보관하고, 첨부파일·이미지·로그·압축 로그는 별도 Artifact 제한으로 처리합니다.
- 해결 선택 후 Knowledge Base 종합은 신뢰된 내부 16,000자 계약을 사용해 선택 답변과 전체 대화를 충분히 검토합니다.
- 선택 답변과 최종 작성 지침의 공간을 먼저 확보해 긴 해결 대화에서도 내부 `ValidationError` 없이 KB를 생성합니다.
- 기존 Activepieces Webhook 계약과 Flow는 변경하지 않습니다.

## v0.14.4 구현 범위

- Community 질문과 후속 질문에 AI-Assistant가 관리자 승인 없이 바로 답변합니다.
- 최초 질문자뿐 아니라 토론에 참여한 다른 사람의 후속 질문과 추가 정보도 같은 Conversation을 진행합니다. AI-Assistant 자신의 Post만 재응답 대상에서 제외합니다.
- 후속 답변은 가장 가능성이 높은 해결 방법과 근거 있는 CLI 명령·성공 기준을 먼저 제시하고, 해결되지 않을 때만 대안과 정확한 로그를 요청합니다.
- 설명과 CLI 명령을 같은 문장에 섞지 않습니다. 실행 명령은 설명 다음의 독립된 `bash` 코드 블록에 넣어 바로 복사할 수 있게 합니다.
- 직전 답변과 같은 점검 목록을 반복하면 한 번 재생성하고, 그래도 진단이 진행되지 않으면 게시하지 않고 재시도 상태로 둡니다.
- 새 디스크 마운트 뒤 QEMU Guest Agent 파일시스템 동결 권한 오류는 게스트 안의 마운트·권한·SELinux AVC를 안전한 명령으로 확인하며, SELinux 전체 비활성화나 `chmod 777`은 제안하지 않습니다.
- 진행 중 답변은 고정 보고서 서식 대신, 전문 엔지니어가 제품을 처음 접한 사용자에게 설명하는 쉬운 대화형 문장으로 제공합니다.
- 최초 질문자 또는 운영 설정에 등록된 Community 관리자가 해결 답변을 선택할 때까지 같은 Discussion의 질문·답변·첨부파일 맥락을 유지합니다.
- 해결 선택자는 Gateway의 관리자 ID 허용 목록으로 판정하며, 일반 참여자의 선택은 Knowledge Base 생성 신호로 인정하지 않습니다.
- 해결 답변이 선택되면 선택된 답변과 전체 대화를 다시 검토해 제목 없는 Knowledge Base 최종본을 게시합니다.
- Knowledge Base 공개가 확인되면 해당 KB Post를 Flarum의 최종 Best Answer로 지정하고 재조회로 일치 여부를 검증합니다.
- 최초 해결 답변 Post는 KB 생성 원본으로 보존하며, KB 최종 솔루션 지정 시각과 selector ID를 감사 이력에 남깁니다.
- Synology Chat은 승인 채널이 아니라 자동 게시·실패·Knowledge Base 생성 상태를 확인하는 운영 관찰 채널로 사용합니다.
- 내부 Citation과 상세 근거는 Community에 공개하지 않고, 연결된 운영자의 `근거 <Case>` 명령으로만 확인합니다.

사용자 이용 방법은 `../../docs/guides/community-automation-user-guide.md`, 설계와 운영 절차는
`../../docs/adr/0010-community-auto-publish-knowledge-base.md`와
`../../docs/runbooks/community-conversation.md`를 참조합니다.

TechFlow AI Gateway는 Activepieces와 AI Provider 사이에서 ABLESTACK 지식의 Source Registry, 검역·승인, Parser·Chunk·Embedding, 검색 범위와 인용, 삭제 정책을 소유하는 FastAPI 서비스입니다. 저장소 원문을 실행하지 않으며 Activepieces가 정책·상태·인프라 작업을 대신 소유하지 않습니다.

## v0.11.3 구현 범위

- 승인된 QEMU/libvirt 운영 지식과 공식 문서를 로컬 스냅샷으로 고정해, 외부 네트워크 없이도 플랫폼 런타임 원인과 안전한 CLI 진단 절차를 답변 근거에 포함한다.
- Mold 콘솔 `연결중` 증상을 ABLESTACK 코드 결함이 아닌 `CURRENT_RUNTIME_ISSUE`로 분류하고, 라이브 마이그레이션 우선·정지 후 시작 대안·후순위 Console Proxy 경로 점검을 구분한다.
- 사용자 답변에는 저장소·코드 경로·공식 참조 URL을 노출하지 않고, 내부 Evidence Ledger에서만 출처와 승인 이력을 유지한다.
- Reviewer `상세`에는 답변만 표시하고 `근거 <Case>`에서만 내부 Citation·Coverage를 표시한다.
- 신규 Community 글은 10초 Poll 후 Synology Chat Bot의 `chatbot` 수신 메서드로 연결 Reviewer에게 선제 알림한다.

## v0.11.2 구현 범위

- 콘솔이 `연결중`에 머무는 질문은 Console Proxy, noVNC, WebSocket, websockify, VNC 구현 용어를 내부 검색에 확장한다.
- 정확한 런타임 원인이 미확정이어도 근거가 있는 안전한 점검 절차는 답변하되, 원인을 확정해서 표현하지 않는다.
- 공개 답변은 내부 검색어·저장소·브랜치·경로를 노출하지 않고 트러블슈팅 문서 형식을 유지한다.

## v0.11.1 구현 범위

- 모든 일반 기술지원 질의에서 공개 문서, Diplo 현재 출시 Cloud와 5개 연관 제품 코드를 각각 검토
- Europa는 미출시 프리뷰로 분리해 현재 오류의 개선 진행·일부 개선·미확인 여부만 비교
- 내부 Evidence Ledger와 Community·일반 Chat용 안전 Projection 분리
- 공개 답변을 `증상·원인·해결 방법·추가 고려사항·적용 버전` 순서의 트러블슈팅 문서로 표준화
- 일반 Chat 사용자 기술 질문 자동 응답과 승인 담당자 전용 상세 근거·결정 명령 분리
- 현재 오류·Europa 개선·미개선·설정 오류·정상·근거 부족 6개 Versioned Golden Case

- Synology Chat Bot Token과 Reviewer 허용목록 검증
- Chat 사용자 ID·이름 연결과 Community Case 대기·상세·이력 조회
- 승인·수정 승인·반려 명령과 interactive button 처리
- Activepieces의 사설 승인·반려 Flow 경유와 최종 상태 대기
- 새 Community 초안의 연결 Reviewer 알림
- 같은 상태·Draft Version 결정의 멱등 재처리
- 삭제된 원본 Discussion의 게시 재시도 금지·반려 정리 운영 기준
- OpenAPI 33개 Operation, PostgreSQL 22개 Table

## v0.6.0 구현 범위

- 70개 D0 Golden Question과 7개 저장소·9개 Source Profile 고정 Commit 계약
- 실제 질문·답변·Citation·자동 판정·Codex 검토 판정 산출물
- 비동기 Evaluation 실행과 원문 없는 DB 결과 조회 API
- OpenAI 8,192-token 경계보다 낮은 7,936-byte Embedding 입력 상한과 UTF-8 안전 분할
- `compose.openai.override.yml` 기반 실 OpenAI 모드와 활성 인덱스를 유지하는 원자적 `REINDEX`
- Branch Isolation·미승인 Cross-Repository·근거 부족 보류 검증

## v0.5.0 구현 범위

- Activepieces 5개 Flow용 최소 Event·Correlation·Idempotency 계약
- Ingestion Job·Evaluation Run `correlation_id` 영속화
- 9개 Source Profile Discovery·Scan 반복 실행 멱등성
- 승인·Compatibility·철회·평가 정책을 Gateway에 유지
- `RETRYABLE`·`TERMINAL`·`MANUAL_REVIEW` 실패 계약

- OpenAPI 21개 Operation, PostgreSQL RAG Table 19개
- 7개 영속 Bare Mirror, 9개 Allowlisted Source Profile
- `REGISTERED → QUARANTINED → APPROVED → INDEXING → ACTIVE` 상태 계약
- Markdown Heading Parser와 Tree-sitter Parser 13종
- Parser 실패 시 160 Line·Overlap 20의 결정론적 Fallback
- 최대 7,936-byte Chunk, UUIDv5 기반 안정 ID, Source Version Lineage
- `text-embedding-3-large`, 3072차원, 공식 OpenAI Python SDK Adapter
- FTS 20·Identifier 20·exact cosine 30 후보와 RRF `k=60`
- 최종 최대 10개 Repository·Branch·Commit·Path·Line·Symbol 인용
- WITHDRAW 즉시 검색 제외와 Chunk·Embedding·Symbol·Relation 삭제 Ledger
- OpenAI Responses API의 `store=false`·`background=false`·Tool 0개·Strict Structured Output
- 단일 근거 `gpt-5.6-terra/medium`, 복합 근거 `gpt-5.6-sol/high` 결정론적 라우팅
- Branch·Compatibility·Test-only 사전 보류와 Citation 사후 검증
- `ANSWERED`·`ABSTAINED`·`FAILED`, 재시도·Circuit Breaker와 원문 없는 Provider 감사

`POST /v1/rag/query`는 `actorId`를 필수로 받아 안정적인 가명 `safety_identifier`를 만들고, 로컬에서 검색한 최대 10개 D0 Chunk만 답변 Provider에 전달합니다. 원본 질문·응답·Chunk는 Provider 감사 테이블에 저장하지 않습니다.

## 개발과 검증

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/export_openapi.py
.venv/bin/python scripts/build_migration_manifest.py
.venv/bin/python ../../tools/ai_gateway/validate_issue_43.py
```

Memory·Mock 기본값은 네트워크 호출 없이 계약을 검증합니다.

```bash
TECHFLOW_RAG_STORE=memory TECHFLOW_RAG_PROVIDER_MODE=mock \
  .venv/bin/uvicorn app.main:app --port 8090
```

PostgreSQL Migration과 운영 Secret은 Runtime 환경 또는 보호된 파일로만 주입합니다.

```bash
TECHFLOW_RAG_MIGRATION_DSN='runtime-only' python scripts/migrate.py up
TECHFLOW_RAG_MIGRATION_DSN='runtime-only' python scripts/migrate.py verify
```

실 OpenAI 모드는 API Key 값을 환경변수나 문서에 기록하지 않고, 보호된 파일을 컨테이너 Secret으로 `/run/secrets/openai_api_key`에 마운트한 뒤 다음 참조만 설정합니다.

```text
TECHFLOW_RAG_PROVIDER_MODE=openai
TECHFLOW_OPENAI_API_KEY_FILE=/run/secrets/openai_api_key
TECHFLOW_OPENAI_PROJECT_ID_FILE=/run/secrets/openai_project_id
TECHFLOW_SAFETY_IDENTIFIER_SALT_FILE=/run/secrets/safety_identifier_salt
```

## 주요 자산

- OpenAPI: `openapi/techflow-ai-gateway-v1.json`
- Migration: `migrations/0000_*`부터 `migrations/0006_*`
- Migration Checksum: `migrations/manifest.json`
- Compose: `../../deploy/compose/ai-gateway/compose.yml`
- Source Runbook: `../../docs/runbooks/source-registry-quarantine.md`
- Parser·검색 Runbook: `../../docs/runbooks/parser-embedding-retrieval.md`
- 근거 답변 Runbook: `../../docs/runbooks/grounded-responses.md`
- Orchestration Runbook: `../../docs/runbooks/activepieces-rag-orchestration.md`
- 완료 보고서: `../../docs/reports/issue-45-activepieces-rag-orchestration-validation.md`
- Chat 승인 Runbook: `../../docs/runbooks/chat-community-approval.md`
- Chat 승인 완료 보고서: `../../docs/reports/issue-22-chat-community-approval-validation.md`
