# Community Discussion #164 후속 답변 장애 복구 보고서

- 복구일: 2026-08-13
- 대상: [Community Discussion #164](https://community.ablecloud.io/d/164-gasangmeosin-sijag-mic-maigeureisyeon-oryu)
- 관련 이슈: #67
- 구현 브랜치: `agent/issue-64-answer-clarity`
- 배포 버전: TechFlow AI Gateway 0.13.2

## 1. 결론

Discussion #164의 후속 로그 ZIP이 접수된 뒤 답변이 생성되지 않던 장애를 복구했다. 실제 원인은 macOS가 ZIP에 넣은 AppleDouble 메타데이터 파일을 로그 바이너리로 판정해 전체 압축 파일을 거부한 것이었다. 이 영구 오류가 Poller 상태 저장 전 발생하면서 같은 구간이 반복되고 뒤의 Community 이벤트도 지연됐다.

파서는 macOS 메타데이터만 제외하고 실제 로그는 기존 보안 검사를 그대로 적용하도록 수정했다. Poller는 영구 첨부 오류를 안전한 경고로 전환하고, 성공 Post를 즉시 원자적으로 체크포인트하며, 실패한 Discussion 때문에 다른 Discussion이 멈추지 않도록 보완했다. 장시간 종합 분석을 위해 Community Draft 생성 Action의 제한은 120초에서 300초로 늘렸다.

복구 결과 Post #358의 ZIP은 Artifact 1건으로 등록됐고, 전체 대화와 로그를 반영한 미승인 검토용 답변 Post #359가 생성됐다. 이후 질문자가 보완 로그 Post #361을 추가했을 때 배포 재시작과 겹친 AI 일시 실패도 확인돼, 실패 Turn을 중복 저장하지 않고 같은 맥락에서 재시도하는 경로까지 보완했다. Post #361 재실행은 128.34초에 완료돼 최신 미승인 검토용 답변 Post #362와 Chat 알림을 만들었다. 공개 답변은 기존 정책대로 담당자 승인 후 게시된다.

## 2. 장애 재현과 원인

### 2.1 관찰 결과

| 항목 | 결과 |
| --- | --- |
| 대상 Post | #358 |
| 첨부 | `log.zip` |
| 다운로드 | HTTP 200, ZIP Magic 정상 |
| 실제 로그 | TXT 2개 |
| macOS 메타데이터 | `__MACOSX/._*.txt` 2개 |
| Artifact API | HTTP 400 `INVALID_BOUNDARY` |
| Poller 영향 | 상태 저장 전 중단, 동일 구간 반복 |

### 2.2 근본 원인

AppleDouble `._*` 파일은 Finder가 파일 속성을 보존하기 위해 만드는 바이너리 메타데이터다. 질문자가 첨부한 실제 로그가 아니지만 기존 파서가 모든 압축 항목을 로그로 처리했다. 바이너리 메타데이터가 보안 경계 검사에 실패하면서 정상 TXT 로그까지 포함한 ZIP 전체가 거부됐다.

### 2.3 확대 원인

- Artifact 영구 오류와 네트워크 일시 오류를 구분하지 않았다.
- 한 Post 실패가 Poller Run 전체를 중단했다.
- 성공한 Post를 Run 종료 시점에만 저장해 앞선 성공 처리도 반복될 수 있었다.
- 로그 기반 종합 답변 생성이 123.58초 걸려 기존 Activepieces 120초 제한을 넘겼다.

## 3. 구현 변경

| 영역 | 변경 |
| --- | --- |
| ZIP/TAR.GZ 파서 | `__MACOSX`, `.DS_Store`, `._*` 메타데이터 제외 |
| 보안 경계 | 실제 로그의 크기·경로·중첩·바이너리 검사는 유지 |
| Artifact 오류 | 400/404/410/413/415/422는 안전한 처리 안내로 전환 |
| 재시도 | 네트워크·일시 장애만 다음 Poll에서 재시도 |
| 상태 저장 | 임시 파일 후 원자적 교체, 성공 Post마다 체크포인트 |
| 장애 격리 | 실패 Discussion은 보류하되 다른 Discussion 처리 계속 |
| AI 입력 | 첨부 처리 경고를 내부 분석 맥락에만 추가 |
| AI 일시 실패 | HTTP 503으로 재시도하고 이미 기록된 실패 Turn은 같은 Draft Version에서 복구 |
| Activepieces | `create_reviewable_draft` timeout 300초 적용 |
| API | `artifactWarnings` 최대 5건 계약 추가 |
| 버전 | AI Gateway 0.13.2 |

## 4. 실제 복구 증적

| 검증 | 실제 결과 | 판정 |
| --- | --- | --- |
| Post #358 첨부 등록 | Artifact 1건 | 통과 |
| 대화 Turn | #354~#358, 마지막 Requester Turn에 Artifact 1건 | 통과 |
| 1차 답변 생성 | Review Post #359 | 통과 |
| Post #361 보완 로그 | Requester Turn, Artifact 1건 | 통과 |
| 실패 Draft 재시도 | Draft Version 4 유지, 중복 Turn 0 | 통과 |
| 최신 답변 생성 | Review Post #362, 2,084자 | 통과 |
| 승인 상태 | `isApproved=false` | 정상 대기 |
| Case 상태 | `DRAFT_PENDING / WAITING_REVIEW` | 정상 대기 |
| Chat 알림 | Reviewer 1명, Attempt 1 | 통과 |
| Poller 안정화 | 반복 Run `failed=0`, 신규 중복 전송 0 | 통과 |
| Activepieces | Flow 3개 ENABLED, Draft timeout 300초 | 통과 |
| Gateway Health | Process/DB/Vector ready, OpenAI, 0.13.2 | 통과 |
| 디스크 | 1005G 중 930G 여유 | 통과 |

최신 Draft는 VM 복제 후 시작 실패와 라이브 마이그레이션 시간 초과를 분리했다. 로그에서 확인된 약 31초의 libvirt Timeout과 UEFI VM 라이브 마이그레이션 호환 가능성을 설명하고, 템플릿 ID 불일치를 단정하지 않은 채 다음 자료를 요청한다.

- VM 시작 Job의 최종 오류와 예외 전후 로그
- 원본·대상 호스트의 Agent 및 libvirt 로그
- 지정 호스트의 상태, 자원, CPU, 스토리지 접근, 태그·전용·선호도 조건
- 현재 VM 상태와 허용 가능한 서비스 중단 시간

해결 절차는 DB 직접 수정과 직접 `virsh` 마이그레이션을 금지하고, 읽기 전용 점검, 지원되는 Mold 재시도, 필요 시 중단 시간을 협의한 오프라인 조치 순으로 제시한다. 적용 버전은 `ABLESTACK Diplo`, 차기 참고는 `ABLESTACK Europa`로 표시했다.

## 5. 검증 결과

- AI Gateway Test: 201 passed
- macOS 메타데이터 ZIP 회귀 시험: 실제 로그 1건 수용
- Poller 영구 Artifact 오류 경고 전환 시험: 통과
- Poller 원자적 체크포인트 시험: 통과
- Activepieces Bundle: 3 Flow valid
- OpenAPI 3.1.0: 34 Operations
- `git diff --check`: 통과

## 6. 배포와 롤백

배포 전 `/home/ablecloud/techflow-ai-gateway-backups/discussion-164-predeploy-20260813T063042Z`에 Gateway 소스와 Poller 상태를 백업했다. `gateway`와 `community-poller`만 0.13.2 이미지로 교체하고 Activepieces Community Flow만 다시 게시했다.

롤백 시 Gateway와 Poller를 직전 이미지로 복귀하고 Activepieces Flow를 직전 Published Version으로 되돌린다. Flarum의 원문과 검토 Post는 삭제하지 않는다.

보호 대상 GitHub-to-Chat 서비스 `techflow-activepieces-event-gateway-1`은 수정, 재시작, 재배포하지 않았다. 최종 Container ID와 Image가 작업 전 기준과 동일함을 확인한다.

## 7. 현재 운영 상태와 담당자 조치

장애 복구는 완료됐다. Discussion #164에는 최신 전체 답변 Post #362가 미승인 상태로 등록돼 있으므로 담당자는 Chat으로 전달된 링크에서 내용을 검토한 뒤 다음 중 하나를 수행하면 된다.

- 승인: 공개 게시 후 질문자의 해결 표시 대기
- 수정 승인: 문구 보완 후 공개 게시
- 반려: 사유를 남기고 새 Draft 생성

자동 공개는 수행하지 않았다. 이는 구현 실패가 아니라 승인 전 사용자 노출을 막는 정상 정책이다.
