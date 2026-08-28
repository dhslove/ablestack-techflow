# Issue #105 Synology Chat 첨부자료 수집·분석 완료 보고서

## 결론

Synology Chat에서 TechFlowAssist Bot에 올린 이미지·로그·압축 로그가 AI Gateway 0.16.5의 실제 분석 입력으로 전달되도록 구현하고 운영 배포했다. 파일만 전송한 게시물도 질문으로 접수되며, 같은 미해결 대화의 이전 첨부는 관련 후속 질문에서 재사용된다.

## 최초 결함

- Chat Event는 `text`만 저장했다.
- `post_id`가 있어도 Synology `post_file_get`을 호출하지 않았다.
- Chat Turn과 AI 요청에 `artifactIds`가 없었다.
- 파일만 전송하면 도움말 명령으로 처리될 수 있었다.
- Community의 Artifact 보안·분석 기능이 Chat에는 연결되지 않았다.

## 구현

- Bot Token과 `post_id`를 사용하는 `post_file_get` Streaming Client
- UTF-8 Content-Disposition, MIME, Content-Length, Magic Byte 검증
- ArtifactStore의 파일 경로 소비 방식 추가
- `chat_assist_turn.artifact_ids`, `artifact_warnings`, `artifact_checked` Additive Migration
- 이미지·로그·ZIP·GZIP·TAR.GZ 분석과 Secret Redaction 재사용
- 파일만 전송하는 메시지용 기본 질문 생성
- 현재 첨부는 분석 필수, 이전 대화 첨부는 관련 시 선택적으로 재사용하는 Provider 계약
- 손상·지원 제외·크기 초과 파일의 구체적인 한국어 경고
- 긴 대화에서도 이전 대화 앞부분보다 최신 질문을 반드시 보존

## 자동화 시험

- Windows Repository 전체 시험: 320건 통과
- 이미지 + 질문
- 단일 로그 + 질문
- ZIP 및 TAR.GZ 로그
- 파일만 전송
- 연속 이미지·로그와 대화 맥락 재사용
- Synology UTF-8 파일명
- Chat 파일이 없는 일반 텍스트 게시물의 404 경계
- 손상 이미지, 지원하지 않는 PDF, 크기 초과
- 압축 폭탄, 경로 탈출, 중첩·암호화 압축, 비밀정보 마스킹 회귀시험

## 운영 E2E

| Post | 입력 | 결과 |
|---|---|---|
| `1945620185255` | ABLESTACK 요청 실패 JPG + 질문 | `COMPLETED`, IMAGE Artifact 1개, 화면의 요청 실패 알림 2회 판독 |
| `1945620185257` | JSON 로그 + 같은 문제 후속 질문 | `COMPLETED`, LOG Artifact 1개, 실제 로그가 아닌 시험 자료임을 판정하고 이전 화면 맥락 재사용 |
| `1945620185259` | 설명 없는 JPG 파일 | `COMPLETED`, IMAGE Artifact 1개, 파일만 전송한 질문 분석 |
| `1945620185265` | 지원하지 않는 PDF | `COMPLETED`, Artifact 0개·경고 1개, 지원 형식을 구체적으로 안내 |

중간 PDF 시험에서 이전 대화 Artifact 전체가 현재 답변의 필수 근거로 취급되어 Provider 계약이 실패하는 문제를 발견했다. 현재 첨부와 이전 대화 첨부의 의무를 분리하고, 지원 제외 파일은 결정적 경고로 완료하도록 보완한 뒤 최종 시험은 1회에 완료됐다.

## 운영 상태

- Runtime Image: `techflow/ai-gateway:issue105-0.16.5-93152e6`
- Gateway: Healthy, Restart 0, OOM false
- Community Poller: Healthy, Restart 0, OOM false
- Schema: 28 Tables, Issue #105 Columns 3개 검증
- Community·Chat·TechFlow: HTTPS 200
- 최근 Gateway Dead Letter·Traceback: 0
- 최근 Poller 실패·Traceback: 0
- Source Reconciler·GitHub→Chat Event Gateway·Activepieces App·Worker Container ID 변경 없음

## 백업·롤백

- 백업: `/home/ablecloud/techflow-backups/issue105-20260828T085032Z`
- Gateway Source·Compose, Chat DB Table, 배포 전 Container 목록 보관
- Gateway·Poller만 제한 배포
- Additive DB 열은 이전 Gateway와 호환되므로 Image Release만 되돌리는 저위험 롤백 가능

## 관련 자산

- Issue #105
- PR #101
- `docs/runbooks/synology-chat-artifact-ingestion.md`
- `docs/evidence/issue-105/synology-chat-artifact-ingestion-validation.json`
