# Issue #102 일반 게스트 OS 공식 자료 답변 개선 보고서

## 1. 결론

일반 가상머신 운영체제 질문을 ABLESTACK 제품 장애와 구분하도록 AI Gateway 0.16.2를 보완했다. Windows·Ubuntu·RHEL 계열의 설정·운영 질문은 운영체제와 작업 주제를 함께 식별하고, 정확히 일치하는 승인 공식 자료 또는 해당 운영체제의 제한된 공식 도메인 검색 결과로 답한다.

Windows Server 2022 NTP 질문은 Microsoft Learn의 W32Time 자료를 근거로 `ANSWERED` 처리됐다. 기존의 제품 버전·발생 시각·관리 서버 로그 요청은 제거했으며 같은 Chat 대화에 교정 답변을 전송했다.

## 2. 최초 답변이 실패한 이유

1. 공식 외부 자료 검색 대상이 사실상 QEMU Guest Agent 설치 질문으로 제한됐다.
2. Windows 일반 운영 질문은 `WINDOWS`로 분류됐지만 공식 플랫폼 지원 질문으로 판정되지 않았다.
3. Windows Guest Agent 자료가 NTP처럼 다른 Windows 주제에도 가족 단위 근거로 오인될 수 있었다.
4. Chat 지침이 게스트 운영체제 절차와 ABLESTACK 제품 장애를 구분하지 않아 Diplo 버전·호스트 로그를 먼저 요청했다.

## 3. 구현

- Windows·Ubuntu·RHEL 계열 일반 게스트 OS 설정·운영 질문까지 공식 근거 범위 확대
- `WINDOWS`, `TIME_SYNC`와 같은 운영체제·주제 이중 분류
- 승인 자료에 `requiredTermGroups`를 적용해 운영체제와 작업 주제가 모두 일치할 때만 사용
- Windows 일반 운영 Live Web Fallback은 `learn.microsoft.com`으로 제한
- Microsoft W32Time 승인 Snapshot 추가
- Windows 시간 질문 Retrieval에 `w32tm`, `W32Time`, `manualpeerlist`, `DOMHIER`, `resync`, `stripchart` 검색어 추가
- Chat Prompt에서 게스트 절차를 제품 버전·관리 서버·호스트 로그보다 먼저 답하도록 강제
- PowerShell 명령 블록과 불완전한 `stripchart` 명령 보정

## 4. 제공되는 Windows Server 2022 절차

먼저 관리자 PowerShell에서 현재 상태를 확인한다.

```powershell
Get-TimeZone
Get-Date
Get-Service W32Time
w32tm /query /source
w32tm /query /status
w32tm /query /configuration
```

도메인에 가입한 일반 멤버 서버는 도메인 시간 계층을 사용한다.

```powershell
w32tm /config /syncfromflags:domhier /update
Restart-Service W32Time
w32tm /resync /rediscover
```

Workgroup 또는 독립 서버는 `<NTP_SERVER>`를 승인된 NTP 서버로 바꿔 설정한다.

```powershell
w32tm /config /manualpeerlist:"<NTP_SERVER>,0x8" /syncfromflags:manual /update
Restart-Service W32Time
w32tm /resync /rediscover
w32tm /stripchart /computer:<NTP_SERVER> /dataonly /samples:5
w32tm /query /source
w32tm /query /status
```

`Source`가 `Local CMOS Clock`이 아닌 의도한 원본이고 `Last Successful Sync Time`이 갱신되면 정상이다. NTP는 UDP 123을 사용하므로 TCP 검사만으로 판정하지 않는다. 도메인 컨트롤러는 조직의 도메인 시간 정책을 먼저 확인한다.

## 5. 검증 결과

| 항목 | 결과 |
|---|---|
| Repository 테스트 | 296건 통과 |
| 분류 | `WINDOWS` / `TIME_SYNC` |
| 공식 근거 | Microsoft Learn W32Time |
| 공개 답변 상태 | `ANSWERED` |
| Provider | `OPENAI_RAG_ESCALATION_V1` |
| 관리자 PowerShell 명령 | 포함 |
| 도메인·독립 서버 분기 | 포함 |
| 강제 동기화·검증 | 포함 |
| 기존 Diplo 버전 선요청 | 제거 |
| Chat 교정 답변 | 전송 성공 |
| Community·Chat·Activepieces | HTTP 200 |
| 보호 서비스 변경 | 0건 |

## 6. 배포·연속성

- 배포 전 Gateway Source·Compose 환경·Database 전체 Dump 백업
- Database Dump 복원 목록 223건 검증
- Gateway만 빌드·교체
- Community Poller·Source Reconciler·GitHub→Chat Event Gateway·Activepieces App/Worker 재기동 없음
- 백업: `/home/ablecloud/techflow-backups/issue102-20260826T025056Z`

Gateway 교체 중 Poller가 일시 연결 오류를 기록했지만 상태를 잃거나 재기동하지 않았고 이후 정상 Poll로 복구했다.

## 7. 관련 자산

- Issue #102
- PR #101
- `docs/evidence/issue-102/windows-server-time-chat-validation.json`
- `docs/runbooks/versioned-safe-answer.md`
