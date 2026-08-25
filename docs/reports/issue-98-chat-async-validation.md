# Issue #98 Synology Chat 비동기 AI 답변 완료 보고서

## 1. 결론

Synology Chat의 Bot 요청 제한시간보다 AI 분석이 오래 걸려 사용자 화면에 실패가 표시되던 문제를 해결했다. AI Gateway 0.16.0은 일반 기술 질문에 즉시 접수 확인을 반환하고, 지속 Job에서 RAG·OpenAI 분석을 수행한 뒤 Synology Chatbot API로 질문자에게 답변을 전송한다.

운영 E2E에서 접수 응답은 0.119초, 전체 AI 처리와 Chat 전송은 144.585초였다. Job은 1회 시도로 `COMPLETED`됐고 질문자에게 완료 답변이 전송됐다.

## 2. 원인

- Chat Webhook 요청 안에서 AI 분석을 동기 실행했다.
- 실제 질문은 35.113초와 53.530초가 걸렸다.
- Synology Chat은 먼저 요청을 종료하고 `봇 서버에 요청을 발송하지 못했습니다`를 표시했다.
- Gateway가 나중에 HTTP 200을 반환해도 Chat Client는 답변을 표시하지 못했다.

## 3. 구현

- Webhook 즉시 접수 확인
- `chat_assist_job` 지속 Queue와 Migration 0015
- 사용자·Context Version·Post ID 멱등 키
- 사용자별 Job 직렬 처리
- 완료 답변 Chatbot API 전송
- Gateway 재시작 시 RUNNING Job 복구
- Provider·Chat 전송 실패 지수 재시도와 Dead Letter
- Chat 전송 재시도 시 이미 생성한 Assistant Turn 재사용
- `해결` 입력 시 같은 Context의 미완료 Job 취소
- 원문을 포함하지 않는 Job·실패 KPI

## 4. 상태 모델

`PENDING → RUNNING → COMPLETED`가 정상 경로다. 일시 실패는 `RETRYING`으로 전환하고 최대 3회 실패하면 `DEAD_LETTER`로 분리한다. 사용자가 해결을 입력하면 같은 Context의 `PENDING`, `RUNNING`, `RETRYING` Job을 `CANCELLED`로 전환한다.

## 5. 운영 E2E

| 항목 | 결과 |
|---|---|
| 공개 Bot Endpoint | HTTP 200 |
| 접수 응답 | 0.119초 |
| 접수 문구 | 질문 접수·완료 후 답변 전송 안내 |
| Job ID | `07dfbb88-db1a-4ffa-a694-684c53a3adb8` |
| Job 상태 | `COMPLETED` |
| 시도 횟수 | 1회 |
| 전체 처리 | 144.585초 |
| Provider | `OPENAI_RAG_ESCALATION_V1` / `gpt-5.6-sol` |
| Provider 지연 | 111.991초 |
| User Turn | 1건 |
| Assistant Turn | 1건 |
| Chatbot 완료 전송 | 성공 |
| 해결 처리 | `RESOLVED` |

## 6. 배포와 연속성

- 운영 이미지: `techflow/ai-gateway:issue98-0.16.0-5290e0f`
- 백업: `/home/ablecloud/techflow-backups/issue98-20260825T075015Z`
- Gateway와 Migration 0015만 변경
- Community Poller·Source Reconciler·GitHub→Chat Event Gateway·Activepieces App·Worker 재기동 없음
- Community·Chat·Activepieces 공개 Endpoint HTTP 200

## 7. 검증

- 전체 Repository 테스트 283건 통과
- 즉시 ACK·완료 전송 시험 통과
- 동일 Post ID 멱등성 시험 통과
- 전송 실패 후 재시도와 답변 재사용 시험 통과
- 재시작 복구 시험 통과
- 해결 시 취소 시험 통과
- 일반 로그에 질문·답변 원문 출력 없음

## 8. 사용 방법

사용자는 `TechFlowAssist` Bot에 일반 기술 질문을 입력한다. 즉시 접수 메시지가 표시되고 분석이 완료되면 같은 대화에 AI 답변이 새 메시지로 도착한다. 후속 질문은 그대로 이어서 입력하며 해결되면 `해결`을 입력한다.

## 9. 관련 자산

- Issue #98
- PR #99
- `docs/evidence/issue-98/chat-async-e2e.json`
- `docs/runbooks/epic4-service-continuity.md`
