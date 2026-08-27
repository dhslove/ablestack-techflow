# Issue #103 Community Poller 근본 복구 보고서

## 1. 결론

Discussion #176 Post #419가 답변되지 않은 원인은 Gateway나 Poller 프로세스가 주기적으로 죽었기 때문이 아니다. 두 컨테이너는 Restart 0, OOM 0이었고 서버 자원도 충분했다. 실제 원인은 해결 성공 댓글을 일반 RAG 질문으로 처리한 Gateway의 응답 거부와, Activepieces 비동기 수락 뒤 결과를 최대 600초 동안 동기 확인하던 Poller의 단일 루프 점유가 결합된 것이다.

AI Gateway 0.16.3에서 해결 결과 전용 응답과 비차단 `pendingPosts`·`pendingResolutions` Queue를 구현했다. Gateway·Poller를 같은 Image로 배포했고 Post #419는 Case에 기록됐다. Assistant Post #420과 최종 KB Post #421이 공개됐으며 Pending Queue는 0건으로 복귀했다.

## 2. 장애 흐름

1. Poller는 Discussion #176을 최신 토론 1번째로 발견하고 Post #419를 정상 수집했다.
2. Activepieces Webhook은 Post #419를 두 차례 HTTP 200으로 수락하고 Flow를 실행했다.
3. Gateway는 9개 Source Profile Embedding을 완료했다.
4. “문제가 더 이상 발생하지 않는다”는 성공 결과에는 새 Source 근거가 없어 생성이 `ABSTAINED`됐다.
5. 반복 답변 방지 장치가 진행되지 않는 답변을 두 차례 거부하고 HTTP 503을 반환했다.
6. Activepieces Webhook은 비동기이므로 Downstream 503과 무관하게 Poller에 HTTP 200을 반환했다.
7. Poller는 Gateway Case가 갱신되기를 1초마다 최대 600초 기다리며 다른 Discussion 탐색을 멈췄다.
8. 프로세스는 살아 있었지만 Poll 주기가 10분씩 멈춰 사용자에게는 서비스가 죽은 것처럼 보였다.

## 3. 구현

### 해결 결과 처리

- “더 이상 발생하지 않는다”, “해결됐다”, “조치 후 정상”을 해결 진행 상태로 식별
- 새 RAG 호출 없이 성공 결과를 Case Turn으로 기록
- 확인된 해결 조건, 재발 방지와 해결 답변 선택 안내를 결정적으로 게시
- 실제 해결 답변 선택 전까지 `WAITING_RESOLUTION` 유지

### Poller 비차단 처리

- Activepieces 수락 Post를 상태 파일 `pendingPosts`에 원자적으로 저장
- Gateway 확인을 현재 Poll과 분리하고 다음 주기에 확인
- 한 Post가 처리 중이어도 다른 Discussion 탐색·제출 계속
- 확인 상한 초과 시 최대 15분 범위의 지수 재제출
- Gateway Case 확인 뒤에만 `seenPosts`와 Discussion Snapshot 갱신
- Pending이 남은 동안 정상 복구 알림을 잘못 보내지 않음
- 해결 선택 Event도 KB 게시·최종 솔루션 선택까지 `pendingResolutions`에서 확인
- 보존기간이 끝난 Artifact는 기존 대화와 답변 근거로 대체해 KB 생성을 계속

### 운영 관측과 시작 순서

- Gateway 확인 기본 상한 600초에서 180초로 축소
- Poller 상태 파일 수정 시간이 120초 이내인지 Healthcheck 추가
- Poller Metric에 실행 버전 표시
- Poller는 Gateway Health가 정상인 뒤 시작하도록 Compose 의존성 추가
- Gateway·Poller를 동일 0.16.3 Image로 배포

## 4. Discussion #176 복구

Post #419의 “물리 네트워크 태그와 네트워크 오퍼링 태그를 맞춘 뒤 문제가 발생하지 않는다”는 결과를 자동 인식했다. Post #420은 태그 불일치가 대상 물리 네트워크에 사용할 오퍼링 조회를 막은 설정 문제였음을 정리하고 다음 재발 방지 절차를 안내한다.

- 물리 네트워크와 네트워크 오퍼링 태그를 동일하게 관리
- 생성 전 두 태그 대조
- 정상 설정값을 운영 기준으로 기록
- 해결에 기여한 답변을 해결 답변으로 선택해 KB 생성

질문자가 Post #420을 해결 답변으로 선택한 뒤, 최초 이미지 2건은 24시간 보존기간이 끝난 상태였다. Gateway는 만료 Artifact를 안전하게 제외하고 전체 대화와 선택된 해결 답변으로 KB Post #421을 생성했다. Post #421은 최종 솔루션으로 자동 지정됐다.

## 5. 검증 결과

| 항목 | 결과 |
|---|---|
| Repository 테스트 | 301건 통과 |
| Gateway·Poller Image | `techflow/ai-gateway:issue103-0.16.3-92920f6` |
| Gateway Health | Healthy, Restart 0 |
| Poller Health | Healthy, Restart 0 |
| Post #419 | Case·Checkpoint 기록 완료 |
| Assistant Post | #420 공개 완료 |
| Pending 전환 | 1 → 1 → 0 |
| 최종 Seen Post | #419·#420 |
| Discussion Snapshot | 댓글 7건 |
| KB·최종 솔루션 | Post #421 / Version 1 / 선택 완료 |
| Case | `PUBLISHED` / `ANSWERED` / `RESOLVED` |
| 10분 안정 구간 | Poll 실패 0, Delivery 실패 0 |
| Community·Chat·Activepieces | HTTP 200 |
| 보호 서비스 변경 | 0건 |

## 6. 배포 중 추가 발견과 복구

첫 0.16.3 Poller Image에서 버전 표시를 위해 추가한 Python import가 스크립트 실행 경로에서 실패했다. 새 Healthcheck가 즉시 `unhealthy`로 검출했으며, 앱 패키지 Import 대신 배포된 버전 파일을 직접 읽도록 수정했다. 최종 Image에서 Gateway·Poller 모두 Healthy이고 Restart Count는 0이다.

이 실패는 새 Healthcheck가 실제 배포 결함을 탐지한 증적이며 최종 안정 구간에는 포함되지 않는다.

## 7. 배포·롤백

- 배포 전 Gateway Source·Compose·Poller State·Community 관련 DB Table 백업
- 백업: `/home/ablecloud/techflow-backups/issue103-20260827T074530Z`
- Gateway·Poller만 교체
- Source Reconciler·GitHub→Chat Event Gateway·Activepieces App·Worker 재기동 없음
- 롤백은 백업 Source·Compose·Poller State와 이전 Gateway·Poller Image를 함께 복원

## 8. 관련 자산

- Issue #103
- PR #101
- `docs/evidence/issue-103/discussion-176-poller-reliability.json`
- `docs/runbooks/epic4-service-continuity.md`
