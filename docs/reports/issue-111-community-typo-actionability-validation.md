# Issue #111 Community 오타 완화·실행 안내 검증 보고서

## 결론

Community Discussion #177에서 `kvmhapervider`를 문자 그대로 처리해 사용자가 오타 여부를 다시 설명해야 했고, 이어진 답변은 실행 서버·SSH·권한·정확한 서비스명과 로그 경로가 부족했다.

AI Gateway 0.16.7에서 단일 문맥 오타 후보를 비차단 가정으로 처리하고, Linux 운영 명령·로그 답변의 실행 가능성을 게시 전에 검사하도록 보완했다. Discussion #177의 최신 Assistant Post #431은 새 엔진으로 다시 생성해 같은 Post에서 갱신했으며 Case·Response·Assistant Turn도 동일 본문으로 동기화했다.

## 구현

- 이전 Assistant Turn의 정식 영문 식별자와 최신 댓글 비교
- 첫 세 글자 동일·길이 차이 2 이하·유사도 0.90 이상·단일 후보 조건
- 사용자 원문 보존, 교정 가정을 한 번만 표시하고 분석 계속
- 상태·IP·UUID·버전·명령·경로·로그·Citation·Artifact ID 자동 교정 금지
- 실행 대상·SSH/콘솔·권한·정확한 `.service`·정상 기준 검사
- 정확한 로그 경로 또는 `journalctl -u`, 시간 범위, 공개 마스킹 검사
- 누락 항목을 Provider 재작성 Prompt에 전달
- QEMU/VNC 근거가 있을 때만 공통 가상화 프로그램 Runtime 문구 표시
- 승인된 운영 로그 두 경로를 공개 Projection에서 보존
- 재사용 Post 교정 시 Case·Response·Turn 동시 갱신

## Diplo HA 기준

- 정상 공급자: `kvmhaprovider`
- HA 이벤트: `HA.STATE.TRANSITION`, `[VM Activity Check]`
- 관리 서버 서비스: `mold.service`
- 호스트 에이전트: `mold-agent.service`
- 관리 로그: `/var/log/cloudstack/management/management-server.log`
- 호스트 로그: `/var/log/cloudstack/agent/agent.log`
- `Degraded`는 libvirt 장애로 단정하지 않고 OOBM, Up 이웃 KVM 호스트, `kvm.ha.on.storage.heartbeat`, 관리·에이전트·libvirt 상태를 함께 확인

## 검증

- 오타·Actionability·Community·Migration 관련 시험 124건 PASS
- 서버 최종 Image 시험 124건 PASS
- 전체 AI Gateway 시험 333건 중 332건 PASS
- 나머지 1건은 작업 범위 밖 `tmp/research/activepieces-0.86.3` 기존 CRLF Shell 검사
- Versioned Golden Case 17건
- 실 OpenAI 재처리: `ANSWERED`, Actionability 누락 0, 필수 안내 누락 0, 금지 표현 0

첫 실증에서 공개 Projection이 승인된 `/var/log/cloudstack/...` 운영 로그까지 숨기는 문제를 발견해 Source 내부 경로는 계속 차단하면서 승인 로그 두 개만 보존하도록 수정했다. 실행 대상이 직전 문장에 있고 다음 행에 정확한 Unit이 있는 경우를 인식하도록 검사도 보완했다.

## Discussion #177 처리

- 대상: Post #431
- 처리 방식: 새 Post를 추가하지 않고 Assistant 소유 Post를 제자리 갱신
- 상태: 공개·승인 완료
- 답변 길이: 2,720자
- 포함 확인: `cloudstack-agent` 오류 해석, `mold-agent.service`, `mold.service`, SSH 예시, 두 로그 경로, `HA.STATE.TRANSITION`, 스토리지 Heartbeat, 마스킹
- 제외 확인: `cloudstack-management.service`, libvirt 단일 원인 확정, 근거 없는 서비스 재시작·DB 수정
- Case: `PUBLISHED`, Draft Version 5, Published/Last Seen Post 431
- Case Answer·Assistant Turn: 2,720자 동일
- 감사 이벤트: `AUTO_PUBLISHED_CORRECTED`

## 운영 배포

- Image: `techflow/ai-gateway:issue111-0.16.7-c433bbc`
- Image ID: `sha256:3aac2294f9a00996062e22da36608b95ea1fc2faf929967ae2e47182f52f7453`
- Package SHA-256: `8e971cdc99c1f1e86d6946e8264d3e685ded6cdab49d8c89542d16fcec0d8f8e`
- Backup: `/home/ablecloud/techflow-ai-gateway-backups/issue111-typo-actionability-20260902T0600Z`
- Gateway: `healthy`, Version 0.16.7, Restart 0
- Chat·Community HTTPS: 200
- Community Poller: `failed=0`
- Community Poller·Source Reconciler·GitHub→Chat Event Gateway Container ID·Image·StartedAt 불변
- DB Schema 변경 없음

## 연결

- Issue #111
- Draft PR #110
- `docs/evidence/issue-111/community-typo-actionability-validation.json`
- `docs/runbooks/community-conversation.md`
