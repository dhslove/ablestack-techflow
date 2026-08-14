# Issues #66-#68 Community 지속 대화 구현·검증 보고서

- 검증일: 2026-08-13
- 환경: TechFlow 시험 서버, ABLESTACK Community
- 릴리스: TechFlow AI Gateway 0.13.0
- 실제 E2E: [Community Discussion #163](https://community.ablecloud.io/d/163)

## 1. 결론

Community 질문을 단발성 답변이 아닌 지속 Conversation으로 처리하도록 구현했다. 최초 질문, 추가 정보 요청, 질문자의 후속 댓글, 이미지, ZIP 로그, 새 답변 검토, 관리자 승인, 질문자의 해결 표시, 해결 해제 후 재개, 재해결을 하나의 Case에서 검증했다.

사용자 답변은 별도 제목 없이 `증상`으로 시작한다. 적용 버전 표기는 `ABLESTACK Diplo`, `ABLESTACK Europa`로 통일했다. 내부 Citation·Repository·Commit은 사용자 답변에 노출하지 않는다.

## 2. 구현 결과

| 범위 | 결과 |
| --- | --- |
| Conversation·Turn·Response 모델 | 완료 |
| Post 단위 증분 수집 | 완료 |
| 질문자·담당자·Assistant 역할 구분 | 완료 |
| 이미지·ZIP 로그 누적 분석 | 완료 |
| 후속 질문별 Draft Version | 완료 |
| Flarum 미승인 원문 검토 | 완료 |
| 최초 질문자 또는 등록 관리자 Best Answer 해결 판정 | 완료 |
| 해결 해제 재개 | 완료 |
| 제목 없는 답변 | 완료 |
| `ABLESTACK Diplo/Europa` 표기 | 완료 |

DB Migration `0011`은 Community Case에 Conversation 상태 열 8개를 추가하고 `community_turn`, `community_response`를 생성한다. Gateway API Version은 `0.13.0`이다.

## 3. 실제 E2E

### 3.1 최초 질문

- Discussion: #163
- 최초 질문 Post: #350
- 질문: Mold 가상머신 콘솔이 `연결중`에서 멈추는 현상
- 최초 Review Post: #351
- 결과: Draft Version 1, `WAITING_REVIEW`

답변은 증상과 원인을 분리하고, QEMU/VNC 잔존 세션 가능성을 설명했다. 확인에 필요한 `virsh domstate`, `domdisplay`, QMP `query-vnc`, Dump XML, journalctl 결과를 요청했다.

### 3.2 후속 자료

- 질문자 후속 Post: #352
- 이미지: 1개
- ZIP 로그: 1개
- 신규 Review Post: #353
- Draft Version: 2
- 연결된 Artifact: 2개

ZIP 로그에서 다음 상태를 분리했다.

- 게스트 OS와 서비스: 정상
- 이전 QEMU VNC 세션: `still_open`
- 새 VNC 세션: `waiting`
- 영향 범위: `console_only`

이미지는 질문의 콘솔 화면이 아니라 다른 VM의 용량 부족 화면이었다. 답변은 이를 콘솔 문제의 근거로 사용하지 않고 자료 불일치를 명시했다. 즉, 첨부가 존재한다는 이유만으로 질문과 관계없는 화면을 증거로 채택하지 않았다.

### 3.3 승인·해결·재개

| 단계 | 기대 상태 | 실제 상태 |
| --- | --- | --- |
| Post #353 생성 | `DRAFT_PENDING / WAITING_REVIEW` | 일치 |
| 담당자 승인 | `PUBLISHED / WAITING_RESOLUTION` | 일치 |
| 최초 질문자 또는 등록 관리자 Best Answer | `PUBLISHED / RESOLVED` | 일치 |
| Best Answer 해제 | `PUBLISHED / ANALYZING` | 일치 |
| 질문자 재설정 | `PUBLISHED / RESOLVED` | 일치 |

최종 증적:

- `draft_version=2`
- `review_post_id=353`
- `published_post_id=353`
- `resolved_post_id=353`
- `resolved_by_user_id=1`
- `resolved_at` 존재
- `reopened_at` 존재

## 4. 발견 문제와 개선

### 4.1 삭제된 과거 Review Post

Poller 시작 후 과거 미승인 Review Post 5개가 Flarum에서 영구 삭제되어 404를 반환했다. 404가 Poll 전체를 중단하지 않도록 삭제된 Post를 `REJECTED/ANALYZING`으로 종료하고 감사 이벤트를 남기도록 보완했다. 이후 `reviewsMissing=5`, 미해결 대기 0건을 확인했다.

### 4.2 해결 이벤트 멱등성 키

최초 구현은 Best Answer 시각을 Idempotency-Key에 그대로 포함했다. ISO 8601의 `:`와 `+`가 Gateway 허용 문자 규칙을 위반해 설정 이벤트만 400이 됐다. 해결 해제는 시각이 없어 정상 처리됐기 때문에 비대칭 현상으로 확인됐다.

조치 후에는 `discussion|bestPost|setAt`을 SHA-256 16자리로 요약한다. 설정과 해제 모두 Gateway 201을 반환했고 최종 `RESOLVED`를 확인했다.

### 4.3 제품 표기

사용자 문서의 적용 버전에서 불필요한 `Cloud` 접두어를 제거하고 `ABLESTACK Diplo/Europa`로 통일했다. 생성 규칙과 단위 테스트를 함께 수정해 이후 답변에서도 같은 표기를 강제한다.

## 5. 검증 결과

- Python 전체 단위·통합 테스트: 196건 통과
- Community Poller 집중 테스트: 8건 통과
- Versioned Assist 집중 테스트: 17건 통과
- Activepieces Flow 계약: 3개 Flow 유효
- OpenAPI Operation: 34개
- Gateway Health: Process·Database·Vector `ready`, Provider `openai`, Version `0.13.0`
- DB: Community Conversation 테이블 2개, Case 열 8개 확인
- Poller: 정상 Poll, `reviewRetryFailed=0`
- 실제 승인·해결·재개: 통과
- Secret 값 저장·출력: 없음

## 6. 배포와 보호 경계

Gateway와 Poller만 `techflow/ai-gateway:issue-68-community-conversation` 이미지로 배포했다. Activepieces Community Draft·Approve·Reject Flow를 갱신했다. 배포 전 Gateway 소스·Compose·DB를 백업했다.

보호 대상 `techflow-activepieces-event-gateway-1`은 Container ID, Image `ablestack-techflow/event-gateway:0.4.0`, StartedAt이 작업 전후 동일했다. GitHub→Chat 웹훅 서비스는 변경·재배포·재시작하지 않았다.

## 7. 승인 판단

Issues #66-#68의 구현 완료 기준을 충족했다. PR 병합 전 검토자는 다음을 확인하면 된다.

1. 최초 질문자 또는 운영 설정에 등록된 Community 관리자의 Best Answer를 자동 해결로 인정하는 정책
2. 해결 해제 후 같은 Case를 재개하는 정책
3. 사용자 출력에서 내부 근거를 숨기는 정책
4. 답변 제목 제거와 `ABLESTACK Diplo/Europa` 표기
5. DB Migration `0011` Down 적용 시 Turn·Response 이력이 삭제되는 점
