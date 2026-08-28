# Issue #104 게스트 OS 공식 외부 자료 Fallback 완료 보고서

## 1. 결론

Rocky Linux 8.10 가상머신의 SMB 마운트 질문이 답변되지 않은 원인은 OS 분류 실패나 OpenAI 장애가 아니었다. 질문은 `RHEL_FAMILY / GENERAL_OS`로 정상 분류됐고 공식 검색 필요 판정도 정상이었지만, Compose의 `TECHFLOW_OFFICIAL_WEB_SEARCH_ENABLED`가 실제 Gateway가 아니라 일회성 Migration 컨테이너에만 설정돼 있었다.

AI Gateway 0.16.4에서 설정 배선을 수정하고 게스트 OS·작업 주제별 공식 자료 Routing을 확대했다. Rocky 질문은 Red Hat 공식 문서로 `ANSWERED` 처리됐고 기존 Chat 대화에 전체 마운트 절차를 교정 전송했다. 로컬 자료가 없는 Debian 시험도 실제 제한 Web Search를 실행해 Debian `mount.cifs(8)` 공식 Manpage를 인용한 `ANSWERED` 결과를 반환했다.

## 2. 최초 실패 원인

1. `.env`에는 공식 검색이 `true`였다.
2. Compose 변수는 Migration 서비스 환경에만 연결됐다.
3. 실제 Gateway Container에는 설정이 존재하지 않아 기본값 `false`가 적용됐다.
4. Rocky SMB 질문은 로컬 승인 자료가 없었으므로 Live Fallback이 필요했다.
5. 검색이 실행되지 않아 제품 문서·코드만으로는 답할 수 없었고 기존 일반 보류 답변이 생성됐다.
6. Windows 시간 질문은 Microsoft 공식 Snapshot이 이미 로컬에 있어 이 배선 오류의 영향을 우연히 받지 않았다.

## 3. 구현

### Runtime 설정과 실패 정책

- `TECHFLOW_OFFICIAL_WEB_SEARCH_ENABLED`를 Gateway Environment로 이동
- Migration 서비스에서는 제거
- `/healthz`에 `officialWebSearch=enabled|disabled` 노출
- 공식 검색이 필수인 게스트 질문에서 검색 비활성·실패·무결과 시 일반 답변 생성 금지
- Job을 실패·재시도 상태로 유지해 잘못된 제품 버전·로그 요청 방지
- 공식 Web 구조화 계약 오류를 한 번 자동 재시도

### OS·주제 Routing

- Windows, Ubuntu, RHEL/Rocky/Alma/CentOS
- Debian, SUSE/openSUSE, Fedora, Oracle Linux, FreeBSD
- Alpine, Arch, Amazon Linux, Kali, Solaris, AIX, macOS
- 목록에 없는 Linux는 `GENERIC_LINUX`로 분류
- 미등록 Linux도 전체 인터넷이 아니라 승인 공식 OS 도메인 Catalog에서만 검색
- Chat·Community Prompt 안내문은 제외하고 실제 “현재 질문” 구간만 OS 판정

### Source 적합성

- 공식 도메인 일치만으로 근거를 승인하지 않음
- SMB 질문은 URL 경로가 `cifs` 또는 `smb` 문서인지 추가 검증
- Debian 시험에서 잘못 선택된 일반 `apt-get` URL은 거부
- 재검색 후 Debian 공식 `mount.cifs(8)` 문서를 선택

## 4. Rocky Linux SMB 답변

교정 답변에는 다음 내용이 포함됐다.

- `sudo dnf install -y cifs-utils`
- `/mnt/smb` 마운트 지점 생성
- `mount -t cifs` 일시 마운트
- 비밀번호를 명령행에 넣지 않고 프롬프트 또는 Credential 파일 사용
- Credential 파일 권한 `600`
- `/etc/fstab`의 `_netdev`, `nofail`, `vers=3.0`
- `mount -a`, `findmnt`, `mountpoint`, `ls` 검증
- `umount` 연결 해제
- SMB1 사용 금지

## 5. 검증 결과

| 항목 | 결과 |
|---|---|
| Repository 테스트 | 308건 통과 |
| Runtime | AI Gateway·Poller 0.16.4 Healthy |
| 운영 Image | `techflow/ai-gateway:issue104-0.16.4-59ca9e2` |
| `/healthz` | `officialWebSearch=enabled` |
| Rocky 분류 | `RHEL_FAMILY / SMB_MOUNT` |
| Rocky 공식 근거 | Red Hat Enterprise Linux 8 SMB Mount 문서 |
| Rocky 결과 | `ANSWERED` |
| Chat 교정 답변 | 전송·Turn 교체 완료 |
| Debian Live Fallback | `ANSWERED` |
| Debian 공식 근거 | Debian Bookworm `mount.cifs(8)` |
| 잘못된 공식 URL | Topic 검사로 거부 |
| Community·Chat·Activepieces | HTTPS 200 |
| 보호 서비스 변경 | 0건 |

## 6. 배포·롤백

- 배포 전 Gateway Source·Compose·Poller State·Chat 관련 DB Table 백업
- 백업: `/home/ablecloud/techflow-backups/issue104-20260828T074627Z`
- Gateway·Poller만 동일 0.16.4 Image로 교체
- Source Reconciler·GitHub→Chat Event Gateway·Activepieces App·Worker 변경 없음
- 롤백 시 이전 Gateway·Poller Image와 백업 Source·Compose를 함께 복원

## 7. 관련 자산

- Issue #104
- PR #101
- `docs/evidence/issue-104/guest-os-official-fallback-validation.json`
- `docs/runbooks/versioned-safe-answer.md`
