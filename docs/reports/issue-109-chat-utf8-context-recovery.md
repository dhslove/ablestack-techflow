# Issue #109 Chat 한글 누적 문맥 장애 복구 보고서

## 결론

Synology Chat의 일반 평문 질문은 정상 접수됐지만 누적 대화 문맥의 글자 수와 UTF-8 Byte 상한이 일치하지 않아 AI 분석 전 단계에서 반복 실패했다. 사용자가 질문 형식을 바꿔야 하는 문제가 아니었다.

AI Gateway 0.16.6에서 Chat 문맥과 검색 확장을 UTF-8 Byte 기준으로 제한하고, 기존 Dead Letter 질문을 사용자의 재전송 없이 재처리했다. 원래 질문은 공식 자료 검색 5건과 종합 분석을 거쳐 Chat 답변 전송까지 완료됐다.

## 장애 원인

| 항목 | 장애 값 |
|---|---:|
| 누적 Turn | 11개 |
| 누적 문자 | 4,392자 |
| 누적 UTF-8 | 9,291 Byte |
| 기존 Chat 문맥 상한 | 16,000자 |
| Embedding 입력 상한 | 7,936 Byte |
| 실패 | `ProviderContractError` 3회 |
| 최종 상태 | `DEAD_LETTER` |

한글은 한 글자가 여러 UTF-8 Byte를 사용한다. 기존 `build_chat_question()`은 문자 수로만 압축했고 `expand_retrieval_question()`도 4,000자 기준으로 잘랐다. 따라서 문자 수 검사는 통과하지만 Embedding의 7,936 Byte 계약을 초과했다. 재시도는 같은 초과 입력을 사용해 복구 효과가 없었다.

## 구현

- Chat 문맥 기본 상한을 `MAX_INPUT_BYTES`와 동일한 7,936 Byte로 연결
- 최신 질문을 보존하고 오래된 Turn부터 제거
- 긴 Turn의 앞·뒤 문맥을 UTF-8 경계가 깨지지 않도록 압축
- Source 검색어 확장을 UTF-8 4,000 Byte 이하로 제한
- 결과 문맥이 상한을 넘으면 Provider 호출 전에 명시적으로 차단
- AI Gateway 버전 `0.16.6`

## 시험

- Conversation·Versioned Assist·Chat Operations 관련 시험 62건 PASS
- 서버에서 새 Image로 같은 62건 PASS
- 전체 AI Gateway 시험 323건 중 322건 PASS
- 나머지 1건은 변경 범위 밖 `tmp/research/activepieces-0.86.3`의 기존 CRLF Shell 파일 검사 실패
- 한글 11개 Turn이 첫 시도에 `COMPLETED`되고 실패 문구를 보내지 않는 회귀시험 추가
- `git diff --check` PASS

## 운영 배포와 복구

- Server: `172.16.0.231`
- Image: `techflow/ai-gateway:issue109-0.16.6-f9228ca`
- Image ID: `sha256:6c5513246ebd45262738c4ea76218bcb750cca136e4fcc1539bbd3a6ee1196869`
- Package SHA-256: `e7cf05a38de3bc5f5fbc7af3354923018eedac60b0d1d526b34e504b6d7d99f1`
- Backup: `/home/ablecloud/techflow-ai-gateway-backups/issue109-chat-utf8-20260902T0302Z`
- DB Schema 변경 없음
- Gateway만 재생성

기존 실패 Job은 메타데이터를 백업한 뒤 `RETRYING`, `attempt_count=0`으로 전환했다. 새 Gateway 시작 시 Job을 회수했으며 다음을 확인했다.

- `official_web_search_completed`, 결과 5건
- Embedding 8회 `SUCCEEDED`
- Responses 1회 `SUCCEEDED`
- `chat_async_answer_sent`, Attempt 1
- Assistant Turn 1,267자 저장
- 장애 상태 `RECOVERED`

## 서비스 연속성

- Gateway Health: `healthy`, Version `0.16.6`, Restart 0
- Provider·Database·Vector: `ready`
- Chat HTTPS: 200
- Community HTTPS: 200
- Community Poller: 기존 Container ID·Image·StartedAt 유지, `failed=0`
- Source Reconciler: 기존 Container ID·Image·StartedAt 유지
- GitHub→Chat Event Gateway: 기존 Container ID·Image·StartedAt 유지, Restart 0

## 관련 항목

- Issue #109
- PR #110
- `docs/runbooks/chat-community-approval.md`
- `docs/evidence/issue-109/chat-utf8-context-recovery.json`
