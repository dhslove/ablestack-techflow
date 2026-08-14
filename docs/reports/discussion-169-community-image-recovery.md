# Community Discussion #169 이미지 누락 복구 보고서

- 확인일: 2026-08-14
- 대상: [Community Discussion #169](https://community.ablecloud.io/d/169-windows-gasangmeosin-iso-seolci-junge-diseukeuga-anboim)
- 관련 이슈: #77
- 구현 브랜치: `agent/issue-64-answer-clarity`
- 목표 버전: TechFlow AI Gateway 0.14.9

## 1. 결론

질문자가 첨부한 PNG 파일은 실제로 존재한다. 공개 URL과 Flarum 사설 경로 모두 HTTP 200을 반환하며, 파일 크기는 120,425바이트이고 해상도는 1,602×1,210이다. 화면에는 Windows 설치 프로그램의 디스크 선택 목록이 비어 있고 `We couldn't find any drives. To get a storage driver, click Load driver.` 문구가 표시된다.

그러나 Discussion #169 최초 처리 Run의 Webhook에는 `artifactIds=[]`, `artifactWarnings=[]`가 기록됐다. 따라서 TechFlow는 당시 이미지를 AI 분석에 전달하지 못했다. 정상적인 다운로드 실패도 아니었다. 첨부 참조가 수집 과정에서 조용히 누락됐고, 최종 KB 생성 단계가 별도의 실패 기록 없이 “첨부파일을 내려받지 못해 원래 화면은 확인할 수 없습니다”라는 문장을 만든 것이 직접 원인이다.

## 2. 확인 증적

| 항목 | 확인 결과 |
| --- | --- |
| 원문 Post | #390 |
| 첨부 URL | `/assets/files/2026-08-14/1786706101-848385-image.png` |
| 공개 다운로드 | HTTP 200, `image/png`, 120,425바이트 |
| 사설 다운로드 | HTTP 200, `image/png`, 120,425바이트 |
| 이미지 화면 | Windows 설치 대상 디스크 없음, `Load driver` 안내 표시 |
| Activepieces 최초 Run | 2026-08-14 20:16 KST, 성공 |
| Webhook Artifact | ID 0건, Warning 0건 |
| 최초 AI 답변 | Post #391 |
| 최종 KB | Post #392, 잘못된 첨부 실패 문구 포함 |

## 3. 개선 내용

### 3.1 첨부 수집 완전성

- Flarum HTML의 `img`와 FoF Upload UUID를 첨부 참조로 별도 계수한다.
- 첨부 URL은 공개 HTTPS Origin의 호스트·포트를 정규화해 검증한다.
- 각 첨부 참조는 Artifact ID 또는 사용자에게 전달할 처리 경고 중 하나로 끝나야 한다.
- 참조 수보다 Artifact와 Warning 합계가 작으면 성공으로 넘기지 않고 누락 경고를 만든다.
- Discussion #169의 실제 FoF Upload HTML을 고정 회귀 시험으로 추가했다.

### 3.2 대화와 KB 안전성

- 첨부 처리 경고는 현재 AI 분석 입력에만 사용하고 Community 질문 원문에는 저장하지 않는다.
- KB Prompt는 명시적인 실패 기록이 없으면 다운로드 실패나 화면 미확인 문장을 만들지 못하도록 제한한다.
- 출력 단계에서도 `attachmentFailureRecorded=false`이면 같은 유형의 문장을 제거한다.

## 4. 검증 기준

| 검증 | 완료 기준 |
| --- | --- |
| Discussion #169 HTML 회귀 | 인라인 PNG 1건이 Artifact ID 1건으로 변환되고 Warning 0건 |
| 누락 감지 | `img`는 있으나 사용할 URL이 없으면 Warning 1건 |
| KB 허위 문구 | 실패 기록이 없으면 다운로드 실패 문구 0건 |
| 진짜 실패 보존 | 실패 기록이 있으면 처리 안내를 생성할 수 있음 |
| 회귀 시험 | AI Gateway 전체 시험 통과 |
| 운영 보호 | GitHub-to-Chat Event Gateway Container·Image·Restart Count 불변 |

## 5. 배포와 Discussion #169 교정 절차

1. 시험 서버의 Gateway 소스, Poller 상태, Compose 정의와 현재 이미지 ID를 백업한다.
2. OpenAI Override를 포함해 `gateway`와 `community-poller`만 0.14.9로 재생성한다.
3. GitHub-to-Chat Event Gateway는 어떤 명령의 대상에도 포함하지 않는다.
4. Post #390을 동일 Event ID로 재처리해 이미지 Artifact 등록을 확인한다.
5. 실제 이미지 관찰 결과를 포함해 KB를 다시 종합하고 기존 Post #392를 제자리 교정한다.
6. Post #392가 최종 Best Answer인 상태와 Chat 알림을 재확인한다.

롤백 시 Gateway와 Poller만 직전 이미지로 되돌리고 Poller 상태는 배포 전 백업에서 복원한다. Flarum 원문 Post와 첨부는 삭제하지 않는다.

## 6. 보안과 데이터 경계

이미지 원본은 Flarum에서 Gateway의 단기 D0 Artifact 저장소로만 이동한다. Activepieces에는 Artifact ID와 처리 상태만 전달하며 이미지 바이트, API Key, 비밀번호, 인증 응답은 기록하지 않는다. 사용자용 KB에는 내부 Artifact ID, 저장 경로, Citation, Repository, Commit을 표시하지 않는다.
