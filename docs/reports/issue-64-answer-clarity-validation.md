# Issue #64 Community 원문 승인형 AI 답변 완료 보고서

- 검증일: 2026-08-13
- 환경: TechFlow 시험 서버 + ABLESTACK Community
- 결론: 별도 일반 AI 계정이 전체 답변을 미승인으로 등록하고, Chat 링크를 통해 관리자가 원문과 첨부 분석을 검토·승인하는 경로를 구현했다.

## 1. 완료 범위

- `TechFlow-Assistant` 일반 Member 계정 생성과 런타임 Secret 연결
- Flarum Approval을 이용한 전체 AI 답변 사전 검토
- Chat 메시지를 제목·Case·검토 링크 중심으로 축소
- 사용자 출력에서 Citation과 소스 경로 제거, 내부 Evidence Ledger 유지
- `증상·원인·해결 방법·추가 고려사항·적용 버전` 트러블슈팅 형식 고정
- DOC → Diplo/관련 소스 → Europa Preview → 공식 libvirt/QEMU/KVM → 승인 외부 자료의 검토 순서 적용
- 본문 텍스트, 실제 이미지, FoF Upload ZIP 로그 수집·분석
- 미승인 Post 복구, 승인 상태 동기화, 삭제 원본 Case 종료
- 시험 서버 배포·회귀 시험·롤백 자산화

## 2. 최종 아키텍처 판정

| 단계 | 책임 | 산출물 |
| --- | --- | --- |
| 수집 | Community Poller | 질문 본문과 첨부 URL |
| 정규화 | Artifact Store | 검증된 이미지 또는 안전하게 추출·마스킹한 로그 |
| 실행 | Activepieces | 멱등성을 유지한 Gateway 호출 |
| 종합 분석 | AI Gateway | 문서·코드·플랫폼 근거를 결합한 전체 답변 |
| 사전 검토 | TechFlow-Assistant + Flarum Approval | 일반 사용자에게 보이지 않는 승인 대기 원문 |
| 알림·승인 | Chat + Community 관리자 | 검토 링크, 승인 후 공개 답변 |

판정은 적합이다. Chat 길이 제한은 원문 손실 없이 우회되고, 공개 권한은 Flarum 관리자에게 남는다. Activepieces는 전달과 실행을 담당하며 계정 권한, 답변 상태, 근거 정책과 승인 판정은 Gateway와 Flarum이 소유한다.

## 3. 구현 중 발견한 문제와 보완

### 3.1 API 키 사용자 바인딩

기존 Flarum API 키가 관리자 계정에 바인딩돼 `userId`를 지정해도 관리자 작성 답변이 생성됐다. 이는 승인 확장을 우회해 곧바로 공개되는 위험이 있었다.

조치:

- 사용자 미바인딩 API 키와 별도 Assistant User ID 조합으로 교체
- 작성 직후 Author ID와 `isApproved=false`를 검증
- 조건을 만족하지 않으면 Case 연결과 Chat 알림을 중단하는 fail-closed 처리

### 3.2 미승인 답변 조회

익명 또는 사용자 미지정 API 조회는 미승인 Post를 찾을 수 없었다.

조치:

- 생성, 조회, 승인 여부 확인 모두 Assistant 사용자 문맥을 사용
- `DRAFT_PENDING`인데 Review Post ID가 없는 기존 Case를 reconcile로 복구

### 3.3 Flarum 첨부 표현

이미지는 `<img src>`로, FoF Upload 파일은 일반 링크가 아닌 `data-fof-upload-download-uuid`로 표현됐다. ZIP 다운로드 응답은 `application/force-download`였다.

조치:

- 링크·이미지·FoF Upload UUID를 모두 수집
- UUID를 Flarum 다운로드 API로 변환
- `Content-Disposition`에서 원래 파일명 복원
- 허용된 확장자와 바이트 검증을 조합해 ZIP·GZIP·TAR.GZ 판별

## 4. 실제 E2E 검증

| 유형 | Discussion | 입력 | AI 검토 결과 | 사전 공개 차단 |
| --- | --- | --- | --- | --- |
| 텍스트 | [#159](https://community.ablecloud.io/d/159) | Mold 콘솔 `연결중` 질문 | QEMU/VNC 잔존 가능성, 라이브 마이그레이션 우선, Stop/Start 대안, CLI 점검을 트러블슈팅 형식으로 제시 | `DRAFT_PENDING`, Post #346 |
| 이미지 | [#160](https://community.ablecloud.io/d/160) | 질문 + 실제 PNG | 첨부가 콘솔 오류 화면이 아니라 품질 검증 슬라이드임을 식별해, 이미지로 오류를 확정하지 않음 | `DRAFT_PENDING`, Post #345 |
| ZIP 로그 | [#162](https://community.ablecloud.io/d/162/349) | 질문 + `mold-console-logs.zip` | 이전 VNC 세션 `still_open`, 새 연결 `waiting`, 게스트 서비스 `healthy`, 영향 `console_only`를 구분하고 CLI·라이브 마이그레이션·Stop/Start 순서 제시 | 승인 전 404, Post #349 승인 후 `PUBLISHED` |

이미지 시험은 단순 업로드 성공이 아니라 이미지의 실제 의미를 답변이 구분하는지 확인했다. ZIP 시험 파일의 정규화 결과는 다음과 같다.

- 파일명: `mold-console-logs.zip`
- Artifact 종류: `LOG`
- 압축 항목: 1개
- 원본 크기: 328 bytes
- 추출 로그: 408 bytes
- SHA-256: `15be9f94abc0cfc66c9738d4b77e0fe2dd180ea89374cf1c1ecb8dbcc189c7b0`
- 잘림: 없음
- 마스킹 발생: 없음

Community 원문에서 관리자가 `승인`을 누른 ZIP 검증 Case #162는 Gateway가 `PUBLISHED`, Reviewer `flarum:moderator`로 동기화했다. Post #349는 승인 전 비로그인 API에서 404, 승인 후 200이어서 사전 공개 차단과 승인 공개를 모두 확인했다.

## 5. 답변 품질 검증: Mold 콘솔 `연결중`

### 질문

> Mold에서 가상머신의 콘솔 보기를 클릭하면 콘솔 화면이 표시되지만 "연결중"이라고 표시되고, 더 이상 화면을 보여주지 않습니다. 콘솔을 보려면 어떻게 해야 하나요?

### 기대 판정

- ABLESTACK 코드 결함으로 단정하지 않는다.
- 이전 VNC 세션이 QEMU에 남아 새 연결을 받지 못하는 런타임 문제 가능성을 우선 설명한다.
- 게스트 OS와 서비스에는 영향이 없을 수 있음을 분리해 알린다.
- 서비스 무중단이 필요한 경우 라이브 마이그레이션을 우선 권장한다.
- 불가할 때 정지 후 시작으로 QEMU 프로세스와 VNC 소켓을 초기화한다.
- `virsh domstate`, `virsh domdisplay`, `virsh qemu-monitor-command ... query-vnc`, `virsh dumpxml`, `journalctl` 등 확인 명령과 결과 판정을 제공한다.
- Console Proxy 경로는 위 원인이 확인되지 않을 때의 후순위 점검으로 둔다.

### 실제 판정

텍스트·이미지·ZIP 로그 답변은 위 핵심 계약을 충족했다. 사용자 문장은 짧고 쉬운 한국어로 구성됐으며, `증상`에는 현상만, `원인`에는 가능한 원인과 첨부 로그의 직접 관찰만 배치됐다. ZIP 답변은 게스트가 정상이고 영향 범위가 콘솔로 제한된 사실도 `추가 고려사항`에서 구분했다. QEMU의 `query-vnc`는 VNC 활성화·주소·연결 Client 상태를 확인하는 공식 QMP 명령이며, libvirt `domdisplay`는 그래픽 접속 URI 확인에 사용한다. 운영 명령은 현재 환경에서 실행 결과를 확인한 뒤 적용해야 한다.

## 6. 자동화와 보안 검증

- 전체 테스트: `186 passed`, subtest `4 passed`
- Flarum 파서 집중 시험: 이미지, FoF Upload UUID, Content-Disposition, 강제 다운로드 MIME 포함
- DB: `community_case.review_post_id`, `review_post_url` 마이그레이션과 인덱스 확인
- 삭제된 원본 Discussion 3건: 감사 이력을 보존한 `REJECTED`로 종료
- Poller 재시도: `reviewRetryFailed=0`
- Artifact: D0 전용, 무결성 검사, 압축 안전 제한, 비밀정보 마스킹, 24시간 자동 폐기
- 공개 답변과 Chat 상세: Citation·코드 경로 미표시
- 내부 근거: 허용된 Reviewer의 명시적 `근거 <ID>` 요청에만 표시

## 7. 배포 및 복구 증적

- 배포 태그: `techflow/ai-gateway:issue-64-answer-clarity`
- Gateway 런타임 이미지: `sha256:26d2a4861587...`
- 첨부 Poller 이미지: `sha256:1b5b89aee4bc...`
- Gateway 버전: `0.12.0`
- Gateway Health: `ready`, Database·Vector·OpenAI Provider 정상
- 서버 루트 볼륨: 1005 GiB 중 약 3% 사용
- 사전 백업: `/home/ablecloud/techflow-ai-gateway-backups/issue64-predeploy-20260813T005423Z`
- 배포 시 기존 디렉터리 소유권 보존: `--no-overwrite-dir --no-same-owner --no-same-permissions`

보호 대상 GitHub→Chat 웹훅 컨테이너 `techflow-activepieces-event-gateway-1`은 배포 과정에서 재시작하거나 변경하지 않았다. 검증 시 Container ID는 `bf5c76824dbf8b0513431e4d067043d0ff46fa82553512c41239e5f622804b4c`, 상태는 `healthy`, 시작 시각은 `2026-08-10T07:05:05.417216322Z`로 유지됐다.

재배포 과정에서 서버 루트의 오래된 단일 Compose 파일만 사용하면 Provider가 `mock`으로 되돌아가고 Assistant User ID Secret Mount가 누락되는 위험을 확인했다. 즉시 현재 Compose와 `compose.openai.override.yml`을 함께 배포하고 `TECHFLOW_RAG_RELEASE=issue-64-answer-clarity`를 명시해 복구했다. 최종 Health는 Provider `openai`, Version `0.12.0`, Assistant Secret Mount 정상이다. 이 검증 결과를 Runbook의 필수 배포 절차로 반영했다.

## 8. 승인자가 확인할 내용

1. Chat에 전체 답변 대신 Community 검토 링크만 제공하는 정책
2. `TechFlow-Assistant`를 일반 Member로 유지하는 권한 경계
3. 사용자 답변에서 근거를 숨기고 내부 명시 명령으로만 조회하는 정책
4. Diplo는 현재 제품, Europa는 미출시 개선 예정 정보로만 쓰는 판단 방식
5. 텍스트·이미지·ZIP 로그 E2E 결과와 Community 승인 후 공개 절차

## 9. 결론

Issue #64 범위는 구현과 시험 서버 검증을 완료했다. 담당자는 Chat에서 새 검토 건을 놓치지 않으면서, 잘리지 않은 전체 답변과 첨부 분석 결과를 Community 원문에서 확인할 수 있다. 일반 사용자 공개는 Flarum 관리자 승인 전에는 일어나지 않는다.

최종 병합은 Draft PR 검토와 승인 후 수행한다.

## 10. 참고 자료

- [QEMU QMP Reference](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html)
- [QEMU VNC Security](https://www.qemu.org/docs/master/system/vnc-security.html)
- [libvirt virsh manual](https://www.libvirt.org/manpages/virsh.html)
- [Issue #64](https://github.com/ablecloud-team/ablestack-techflow/issues/64)
