# 기능·소스 분석 기반 Diplo 현재판·Europa 프리뷰 안전 답변 Runbook

## 답변 절차

모든 사용자 질문은 다음 순서를 지킨다.

1. 질문에서 제품 기능, API 명령, UI 컴포넌트와 Source Symbol을 식별한다.
2. ABLESTACK 문서, 현재 Diplo와 관련 제품 코드, Europa Preview, 공식 플랫폼 자료 순으로 검토한다.
3. 첨부 화면·로그·압축파일이 있으면 상태 코드, API 명령, 컴포넌트, 오류 문구를 실제 Artifact에서 읽는다.
4. 첨부 관찰 내용과 Source 동작을 연결하되, 배경 요청 실패와 사용자가 실행한 작업 실패를 구분한다.
5. 정확한 원인이 미확정이어도 Source에서 확인한 실패 조건, 가능성이 높은 원인과 안전한 첫 점검을 기초 답변으로 먼저 제공한다.
6. 추가 자료는 기초 답변 뒤에만 요청한다. 이미 제공된 버전·이미지·시각·로그를 다시 요구하지 않고, 다음 분기를 판정하는 정확한 API 응답·명령 결과·로그만 요청한다.
7. 후속 질문은 해결 표시 전까지 같은 Case의 최근 Artifact를 최대 5건 재사용한다.
8. 후속 결과가 다시 `ABSTAINED`이면 같은 정보 요청을 게시하지 않고 한 번 재작성한다. 재작성도 진행되지 않으면 게시를 중단하고 재시도 대상으로 남긴다.

## 일반 게스트 운영체제 질문

Windows·Ubuntu·RHEL·Debian·SUSE·Fedora·Oracle Linux·FreeBSD·Alpine·Arch·Amazon Linux·Kali·Solaris·AIX·macOS 가상머신 내부의 설정·운영 질문은 ABLESTACK 제품 장애와 구분한다. 목록에 없는 Linux 배포판도 `GENERIC_LINUX`로 처리한다.

1. 운영체제와 작업 주제를 함께 판정한다. 운영체제 이름만 일치하는 다른 주제의 자료는 사용하지 않는다.
2. 정확한 승인 Snapshot이 있으면 공식 외부 문서 근거로 사용한다.
3. 정확한 Snapshot이 없거나 갱신 기한을 넘겼으면 해당 운영체제의 공식 도메인만 Live Web으로 조회한다.
4. Windows 일반 운영 질문은 Microsoft Learn, Ubuntu는 Ubuntu 공식 문서, RHEL 계열은 Red Hat·Rocky Linux 공식 문서로 제한한다.
   Debian은 Debian 공식 문서·Manpage, SUSE는 SUSE 공식 문서, Fedora는 Fedora 공식 문서, Oracle Linux는 Oracle 공식 문서, FreeBSD는 FreeBSD 공식 문서·Manpage만 허용한다.
5. 게스트 안에서 완료할 수 있는 절차는 ABLESTACK 버전·관리 서버 로그·호스트 로그를 요구하기 전에 명령과 성공 기준을 답한다.
6. 제품 계층 확인은 공식 게스트 절차가 실패하고 하이퍼바이저 연동이 의심될 때만 다음 단계로 제시한다.
7. 정확한 공식 자료가 필요한데 Gateway의 공식 검색이 비활성·실패·무결과이면 일반 환경 정보 요청으로 대체하지 않는다. 요청을 실패 상태로 유지해 재시도하고 운영자가 `/healthz`의 `officialWebSearch=enabled`를 확인한다.
8. 등록되지 않은 Linux 배포판은 전체 인터넷이 아니라 승인된 공식 OS 도메인 Catalog 안에서만 검색한다. 질문에서 정확한 OS와 버전을 식별할 수 없으면 제품 로그를 요구하거나 절차를 추측하지 않고 OS·버전만 구체적으로 요청한다.

Windows Server 시간 질문은 다음 순서를 사용한다.

- `Get-TimeZone`, `Get-Date`, `Get-Service W32Time`, `w32tm /query`로 현재 상태 확인
- 도메인 일반 멤버는 `syncfromflags:domhier`
- Workgroup·독립 서버는 승인된 `<NTP_SERVER>,0x8`과 `syncfromflags:manual`
- `Restart-Service W32Time`, `w32tm /resync /rediscover`로 강제 동기화
- `w32tm /stripchart /computer:<NTP_SERVER> /dataonly /samples:5`로 응답과 오차 확인
- `Source`와 `Last Successful Sync Time`으로 성공 판정
- NTP는 UDP 123을 사용하므로 TCP 포트 검사만으로 정상 판정 금지
- 도메인 컨트롤러는 일반 멤버 서버 절차를 그대로 적용하지 않고 도메인 시간 정책 확인

## 배포 전

1. `main...upstream/main`이 `0 0`인지 확인한다.
2. 전체 AI Gateway 단위 시험과 OpenAPI 생성을 수행한다.
3. `protected_service_guard.py`로 `github-chat-v1 state=frozen guard=passed`를 확인한다.
4. 시험 서버 `/` 용량과 AI Gateway·Community Poller 상태를 확인한다.
5. `services/ai-gateway`, Compose 설정, 현재 Gateway Image Inspect를 UTC 시각 백업 경로에 복사한다.

## 배포

시험 서버 작업 루트는 `/home/ablecloud/techflow-ai-gateway`다. Secret 파일과 `.env`는 기존 서버 파일을 그대로 사용하고 배포 묶음에 포함하지 않는다. 변경된 서비스만 명시적으로 빌드·교체한다. 답변 검색·생성 코드만 바뀐 경우 Gateway만 대상이다.

```bash
cd /home/ablecloud/techflow-ai-gateway/deploy/compose/ai-gateway
export TECHFLOW_RAG_RELEASE=<issue>-<version>-<commit>
docker compose --env-file .env \
  -f compose.yml -f compose.openai.override.yml \
  build gateway
docker compose --env-file .env \
  -f compose.yml -f compose.openai.override.yml \
  up -d --no-deps gateway
```

## 확인

1. `/healthz`에서 배포한 Version, Database·Vector `ready`, Provider `openai`를 확인한다.
2. 일반 Assist 질문이 Coverage 9개와 현재판·플랫폼 런타임·프리뷰 구조화 판정을 반환하는지 확인한다.
3. 일반 Chat 사용자의 기술 질문이 Reviewer 권한 없이 응답되며 내부 계보가 없는지 확인한다.
4. Community 질문이 `DRAFT_PENDING` Case를 생성하고 `ANSWERED` 또는 올바른 보류 판정을 갖는지 확인한다.
5. 승인 담당자의 Chat `상세 <Case>`에는 답변만 표시되고, `근거 <Case>`에서만 내부 Citation, 전체 Coverage, 현재판·프리뷰 판정이 표시되는지 확인한다.
6. Community 공개 Draft에서 `github.com`, Source Profile, 저장소, Commit, 경로, 라인 패턴이 0건인지 확인한다.
7. `techflow-activepieces-event-gateway-1`이 재시작 없이 기존 Image로 계속 `healthy`인지 확인한다.
8. 일반 Chat과 Community Draft에 `증상`, `원인`, `해결 방법`, `추가 고려사항`, `적용 버전`이 순서대로 모두 나타나는지 확인한다.
9. 신규 Discussion 생성 후 Poll 10초와 AI 생성 시간 내 Reviewer에게 Chat 알림이 도착하고, 알림·`상세`에는 근거가 없으며 `근거 <Case>`에서만 Ledger가 보이는지 확인한다.
10. 원 질문의 첨부가 후속 질문 분석에도 전달되고 `artifactEvidence`에 실제 Artifact ID가 유지되는지 확인한다.
11. 공개 답변에서 기초 진단과 우선 점검이 추가 자료 요청보다 먼저 표시되는지 확인한다.
12. 이미 제공된 제품 버전·첨부·로그 요청이 반복되지 않는지 확인한다.
13. 배포 전후 Poller·Source Reconciler·GitHub→Chat Event Gateway·Activepieces App/Worker 컨테이너 ID가 같은지 확인한다.

HTTP 200만으로 성공 판정하지 않는다. 구조화 상태, Coverage, 외부 Projection 검사, Reviewer Ledger, 컨테이너 Health를 모두 확인한다.

## 운영 판정

- 범용 장애 질문의 정확한 원인이 미확정이어도 Source 근거로 안전한 진단 순서를 제공할 수 있으면 `ANSWERED`와 `INSUFFICIENT_EVIDENCE`를 함께 사용한다. 추가 자료 요청만 가능한 경우에만 `ABSTAINED`를 사용한다.
- 코드 식별자나 재현 정보가 충분하면 관련 Profile 근거만 생성 컨텍스트에 포함한다.
- Europa에 동일 클래스가 존재하는 것만으로 개선으로 판정하지 않는다. 동일 원인에 대한 변경 근거가 있어야 한다.
- `PREVIEW_NOT_FOUND`는 향후 보완 검토 가이드이며 출시 계획을 대신하지 않는다.
- `적용 버전`에는 Diplo 현재 출시판과 Europa 미출시 Preview를 분리해 표시하며, 근거 없는 숫자 버전과 출시 일정을 생성하지 않는다.
- QEMU/libvirt 참조는 승인된 로컬 스냅샷만 사용한다. 30일 주기 변경 확인 후 Source Reviewer 승인으로만 활성화한다.
- 콘솔 `연결중` 단일 VM 사례는 `CURRENT_RUNTIME_ISSUE`로 분류한다. 읽기 전용 진단은 `virsh domstate`, `virsh domdisplay`, QMP `query-vnc`, `virsh dumpxml`, `journalctl` 순으로 수행한다.
- 운영 VM 조치는 Mold의 라이브 마이그레이션을 우선하고, 불가능하면 서비스 중단을 고지한 뒤 정지 후 시작한다. 직접 `virsh migrate`는 승인된 예외 절차가 아니면 실행하지 않는다.
- Mold의 일반 `요청 실패` 문구는 실제 원인을 표시하지 않는다. 브라우저 Network 탭에서 사용자가 실행한 API 명령과 응답 본문을 확인한다. `SamlDomainSwitcher` 같은 배경 호출은 대상 작업과 동일한 실패로 단정하지 않는다.

## 롤백

1. Gateway와 Community Poller만 이전 Image Tag로 되돌린다.
2. 필요하면 `/home/ablecloud/techflow-ai-gateway-backups/issue62-predeploy-<UTC>`의 소스와 Compose를 복원한다.
3. Database Migration은 추가되지 않았으므로 Schema 롤백은 필요 없다.
4. Community에 이미 게시된 답변은 자동 삭제하지 않는다.
5. 테스트용 Discussion도 자동 삭제하지 않고 E2E 증적으로 유지한다.
6. `github-chat-v1`과 Event Gateway는 롤백 대상에 포함하지 않는다.

## Secret 정책

SSH 암호, OpenAI Key·Project ID, Flarum API Key, Chat Bot Token, Activepieces Webhook URL은 서버의 기존 보호 파일 또는 실행 환경에서만 사용한다. 명령 출력·보고서·Git 저장소·배포 묶음에 값을 남기지 않는다.
