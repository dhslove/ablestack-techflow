# Issue #76 게스트 OS 및 공식 플랫폼 근거 보강 검증 보고서

## 1. 결론

TechFlow AI Gateway 0.14.7은 ABLESTACK 문서와 모든 지정 Source Profile을 우선 검토한 뒤, 로컬 공식 자료가 없거나 갱신 기한을 넘긴 경우에만 제품별 공식 도메인을 검색한다. Ubuntu·RHEL/Rocky·Windows의 QEMU Guest Agent 절차를 로컬 승인 자료로 보강했으며, Mold는 CloudStack과 필요 시 libvirt/QEMU/KVM, Glue·Koral·Wall은 각각 Ceph·Kubernetes·Grafana 공식 문서로 제한 보완한다.

Discussion #168의 잘못된 위임형 답변은 Ubuntu 가상머신 안에서 직접 실행할 설치·시작·검증 명령과 실패 시 다음 진단을 제공하는 답변으로 교정했다. 기존 Post #388을 그대로 갱신해 대화와 멱등성 표식을 보존했고, Community DB의 초안과 응답 이력도 같은 본문으로 맞췄다.

## 2. 원인 분석

Discussion #168 Post #387에는 `qemu-guest-agent.service could not be found`와 Ubuntu 24.04가 명시돼 있었다. 기존 승인 자료에는 ABLESTACK, QEMU/libvirt와 파일시스템 동결 자료만 있었고 Ubuntu 패키지 설치 절차가 없었다. 생성 정책은 근거 없는 명령 생성을 금지하므로 모델은 `apt` 명령을 만들지 않고 시스템 관리자에게 위임했다.

문제는 사용자의 권한이 아니라 근거 세트의 공백이었다. 질문자는 가상머신 관리자이고, Ubuntu 공식 저장소에 패키지가 존재하므로 정확한 설치 방법과 정상 판정 기준을 먼저 제시해야 한다.

## 3. 구현 결과

### 3.1 로컬 공식 자료

- Ubuntu 24.04: `apt update`, `apt install`, 서비스 시작·상태·버전 확인
- RHEL/Rocky: `dnf install`, 서비스 자동 시작·상태 확인
- Windows: 승인된 virtio-win 설치 미디어, MSI 설치, PowerShell 서비스 확인
- 통신 채널이 없을 때 `/dev/virtio-ports/org.qemu.guest_agent.0`과 서비스 로그 확인

### 3.2 공식 웹 보완

| 사용자 영역 | 공개 이름 | 내부 공식 보완 |
| --- | --- | --- |
| 클라우드 관리·가상화 | Mold | Apache CloudStack, 필요 시 libvirt/QEMU/KVM 공식 문서 |
| 분산 저장소 | Glue | Ceph 공식 문서 |
| 컨테이너 플랫폼 | Koral | Kubernetes 공식 문서 |
| 모니터링 | Wall | Grafana 공식 문서 |
| 게스트 OS | OS 배포판 이름 | Ubuntu, Red Hat/Rocky, Microsoft 공식 문서 |

검색은 질문별로 필요한 경우에만 실행된다. 허용 도메인 필터, 실제 도구 Source URL 대조, HTTPS 검사와 수집 시각 기록을 모두 통과해야 Context가 된다. 공개 답변은 내부 URL과 Citation을 제거한다.

### 3.3 안전 경계

- Provider가 OpenAI가 아니면 웹 검색 기능을 활성화할 수 없다.
- 외부 검색 전 URL, 이메일, IP, Password·Token·Secret·API Key 형태를 제거한다.
- 첨부파일과 로그 내용은 외부 검색 입력에 포함하지 않는다.
- 웹 검색 실패는 로컬 RAG 실패로 전파하지 않는다.
- ABLESTACK 근거와 공식 기반 기술 자료가 충돌하면 ABLESTACK 근거를 우선한다.

## 4. Discussion #168 기대 답변

`service could not be found`는 Ubuntu 가상머신에 패키지가 아직 설치되지 않았다는 뜻이다. 사용자는 Ubuntu VM의 콘솔이나 SSH에서 다음 순서로 직접 설치한다.

```bash
sudo apt update
sudo apt install -y qemu-guest-agent
sudo systemctl start qemu-guest-agent
sudo systemctl status qemu-guest-agent --no-pager
qemu-ga --version
```

`Active: active (running)`이면 게스트 안의 서비스는 정상이다. Mold 표시는 1–2분 뒤 다시 확인한다. 서비스가 시작되지 않거나 표시가 계속 같을 때만 다음 결과를 추가로 확인한다.

```bash
ls -l /dev/virtio-ports/org.qemu.guest_agent.0
sudo journalctl -u qemu-guest-agent --since '-15 min' --no-pager
```

## 5. 자동 시험

| 검증 | 결과 |
| --- | --- |
| 로컬 전체 Python 회귀시험 | 243건 통과 |
| 배포 이미지 회귀시험 | 243건 통과 |
| Versioned Golden Set | 15건, Ubuntu·Rocky·Windows·Mold·Glue·Koral·Wall 포함 |
| 웹 검색 계약 | 질문별 최소 도메인, HTTPS, 실제 Tool Source URL 대조, 수집 시각, 비밀정보 제거 시험 통과 |
| Glue 실검색 | `docs.ceph.com`에서 6건, `OFFICIAL_LIVE_WEB_DOCUMENTATION`, 수집 시각 포함 |
| Mold 가상화 실검색 | 5건, `docs.cloudstack.apache.org`·`libvirt.org` 계열만 수용; QEMU 공식 도메인도 허용 경로 시험 통과 |
| Discussion #168 외부 조회 | HTTP 200, Post #388, Assistant User 40, 승인 상태 |
| Discussion #168 본문 | `apt install`, 서비스 상태, 로그, Guest Agent 통신 채널 명령 포함 |
| Community 일관성 | Post 본문과 Case `draftAnswer` 일치, 상태 `PUBLISHED`, 대화 `WAITING_RESOLUTION` |

공개 Post에는 설치 명령과 `/dev/virtio-ports/org.qemu.guest_agent.0`이 그대로 표시된다. 기존의 “시스템 관리자에게 설치 요청” 문구, `제품 내부 경로` 치환, Flarum의 잘못된 아래첨자 표시는 모두 제거됐다.

## 6. 시험 서버 배포 및 운영 증적

- 배포 시각: 2026-08-14 KST
- 배포 대상: Gateway와 Community Poller만 재생성
- Release: `issue-76-official-platform-evidence`
- Image ID: `sha256:c307a1289b1a537793ef3ce7e4f366a9c89fea72d3431a06ad85495515d0de53`
- Gateway: `5691747b5d4d`, Healthy, Provider `openai`, Version `0.14.7`
- Community Poller: `73c79ee2aacd`, 최근 반복 실행 `failed=0`
- Health: Process·Database·Vector 모두 `ready`
- 사전 백업: `/home/ablecloud/techflow-ai-gateway/backups/issue76-predeploy-20260814T062919Z`
  - Source/Compose: 816 KiB
  - PostgreSQL custom dump: 1.4 GiB, `pg_restore -l` 검증 통과
- 루트 볼륨: 1005 GiB 중 917 GiB 여유, 사용률 5%
- Discussion: [#168 Post #388](https://community.ablecloud.io/d/168/388)

OpenAI 시험 서버의 재생성 명령에는 반드시 두 Compose 파일을 함께 지정한다.

```bash
docker compose -f compose.yml -f compose.openai.override.yml up -d --no-deps --force-recreate gateway
```

검증 중 기본 `compose.yml`만 사용한 한 차례 재생성에서 Gateway가 안전 기본값인 Mock Provider로 기동하는 것을 즉시 발견했다. Community 처리가 진행되기 전에 OpenAI Override를 포함해 Gateway를 복구했고, 최종 Health에서 `provider=openai`를 재확인했다. 이 조건은 운영 Runbook의 필수 절차로 명시돼 있다.

GitHub-to-Chat 보호 서비스는 배포 대상에서 제외했다. 배포 전후 값은 다음과 같이 동일하다.

- Container ID: `bf5c76824dbf8b0513431e4d067043d0ff46fa82553512c41239e5f622804b4c`
- Image ID: `sha256:ae33662eb227c9826563e94236272547f586437082f65d4d385837793e63670e`
- Restart Count: `0`

## 7. 공식 자료

- Ubuntu 패키지와 APT: `packages.ubuntu.com`, `documentation.ubuntu.com`
- RHEL Linux·Windows Guest Agent: `docs.redhat.com`
- Rocky 패키지 저장소: `download.rockylinux.org`
- Glue 기반 기술: `docs.ceph.com`
- Koral 기반 기술: `kubernetes.io`
- Wall 기반 기술: `grafana.com/docs`
- Mold 기반 기술: `docs.cloudstack.apache.org`, `cloudstack.apache.org`, `libvirt.org`, `qemu.org`
- OpenAI 웹 검색 계약: OpenAI Developers 공식 문서

## 8. 롤백

웹 검색만 문제가 있으면 환경 변수로 즉시 비활성화한다. 생성 정책 문제가 있으면 Gateway와 Poller만 0.14.6 이미지로 되돌리며 DB와 Activepieces Flow는 변경하지 않는다. GitHub-to-Chat 보호 서비스는 배포와 롤백 모두에서 대상에서 제외한다.
