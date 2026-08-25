# Issue #100 기능·소스 분석 및 기초 답변 우선 절차 완료 보고서

## 1. 결론

Community 질문은 이제 관련 제품 기능과 현재 Diplo 소스를 먼저 분석하고, 확인 가능한 기초 진단과 안전한 첫 점검을 제공한 뒤 부족한 자료만 요청한다. 후속 질문에서도 최초 댓글의 이미지·로그 Artifact를 다시 사용하며, 같은 정보 요청을 반복하는 `ABSTAINED` 답변은 게시하지 않는다.

Discussion #176의 기존 Post #418은 삭제하거나 새 답변을 중복 생성하지 않고 같은 Post에서 교정했다. Case는 `PUBLISHED`, 답변은 `ANSWERED`, 대화는 질문자의 해결 확인을 기다리는 `WAITING_RESOLUTION` 상태다.

## 2. 원인

1. 최초 이미지 2건은 Provider 입력에 포함됐지만 Source Retrieval 검색어에는 이미지의 HTTP 432, API 명령과 UI 컴포넌트가 반영되지 않았다.
2. `요청 실패`라는 일반 문구만으로는 Cloud Diplo Source 근거가 선택되지 않았다.
3. 후속 질문은 현재 댓글의 Artifact만 전달해 최초 댓글 이미지가 실제 Provider 입력에서 빠졌다.
4. 근거 부족 결과가 기초 답변 없이 제품 버전·시각·로그를 요청했다.
5. 후속 `ABSTAINED` 결과도 다시 게시할 수 있어 같은 질문이 반복됐다.

## 3. 구현

- 모든 질문에서 제품 기능·API·UI·Source Symbol을 먼저 식별
- 네트워크 요청 실패를 `createNetwork`, `CreateNetworkCmd`, `NetworkServiceImpl`, `ApiErrorCode`, `SamlDomainSwitcher` 등으로 확장
- 경로·Symbol을 직접 찾는 구현 식별자 Retrieval 채널 추가
- 첨부 화면의 상태 코드·API·컴포넌트·오류를 Source 동작과 연결
- 배경 API 실패와 사용자가 실행한 작업 실패 구분
- 정확한 원인이 미확정이어도 확인된 실패 조건과 안전한 점검을 먼저 제공
- 추가 자료는 기초 답변 뒤에 아직 제공되지 않은 정확한 항목만 요청
- 해결 전 대화의 최근 Artifact 최대 5건 재사용
- 후속 `ABSTAINED` 게시 차단과 진행성 재작성

## 4. Discussion #176 검증

첨부 화면에서 네트워크 생성 화면의 요청 실패 알림 2건과 `SamlDomainSwitcher.vue` 호출의 HTTP 432를 확인했다. 현재 Diplo의 네트워크 생성 경로는 Offering·물리 네트워크 상태, Zone 유형, Guest 유형, VLAN 지정 조건 등을 검증한다.

교정 답변은 화면의 432가 네트워크 생성 요청 자체가 아니라 별도 배경 GET 요청임을 먼저 설명한다. 이어서 Offering·물리 네트워크·Zone·VLAN 조합을 확인하는 기초 절차를 제공하고, 마지막에만 실제 생성 요청의 API 이름·상태 코드·응답 오류 문구를 요청한다. 이미 제공된 Diplo 버전과 이미지·발생 시각·일반 로그는 다시 요청하지 않는다.

## 5. 검증 결과

| 항목 | 결과 |
|---|---|
| Repository 테스트 | 290건 통과 |
| Gateway | 0.16.1, Healthy |
| 운영 Image | `techflow/ai-gateway:issue100-0.16.1-1da48eb` |
| Discussion Case | `f7c792aa-d834-4315-b576-751db9840748` |
| 교정 Post | #418, 기존 Post 유지 |
| 답변 상태 | `ANSWERED` |
| 이미지 분석 | 2건 모두 반영 |
| Provider | `OPENAI_RAG_DEFAULT_V1` |
| 기초 답변 우선 | 통과 |
| 중복 자료 요청 | 0건 |
| 공개 답변 내부 계보 노출 | 0건 |
| Community·Chat·Activepieces | HTTP 200 |
| Gateway 최종 시작 이후 오류 | 0건 |
| 보호 서비스 변경 | 0건 |

Gateway 교체 시점에 Poller가 일시적으로 연결 오류를 기록했지만, 상태를 잃거나 재기동하지 않았고 즉시 정상 Poll로 복구했다. 최종 Poll은 `failed=0`으로 연속 완료됐다.

## 6. 배포와 롤백

- 배포 전 Source·Compose 환경·Database 전체 Dump와 컨테이너 상태를 백업
- Database Dump는 `pg_restore -l`로 목록 검증
- Gateway만 빌드·교체
- Community Poller·Source Reconciler·GitHub→Chat Event Gateway·Activepieces App/Worker는 재기동하지 않음
- 백업 경로: `/home/ablecloud/techflow-backups/issue100-20260825T081722Z`
- 롤백 시 Gateway Image와 백업 Source·환경만 복구하며 Schema 롤백은 필요 없음

## 7. 관련 자산

- Issue #100
- Draft PR #101
- `docs/evidence/issue-100/discussion-176-validation.json`
- `docs/runbooks/versioned-safe-answer.md`
