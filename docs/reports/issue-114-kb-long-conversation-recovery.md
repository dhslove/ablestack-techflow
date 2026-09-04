# Issue #114 긴 Community 대화 Knowledge Base 복구 보고서

## 1. 결론

Discussion #177의 Knowledge Base 변환 누락은 해결 답변이 관리자의 일반 답변이어서 발생한 것이 아니다. 질문자가 Post #441을 해결 답변으로 정상 선택했고 Gateway도 `RESOLVED_BY_REQUESTER` 이벤트를 받았지만, 긴 대화를 외부 공식 자료 검색에 전달하는 과정에서 길이 계약을 위반해 KB 생성이 중단됐다.

AI Gateway 0.16.9에서 검색 질문을 UTF-8 4,000바이트 이내로 제한하고, 계약 오류를 명시적으로 기록하며, 현재 해결 답변과 일치하지 않는 오래된 재시도 항목을 제거하도록 수정했다. 운영 Gateway·Community Poller에 제한 배포한 뒤 Discussion #177을 자동 재처리했고 최종 KB Post #445를 게시·보완한 다음 해결 답변으로 선택했다.

## 2. 확인된 원인

| 구분 | 확인 결과 |
|---|---|
| 해결 선택 | 질문자가 Post #441을 Best Answer로 선택 |
| Gateway 상태 | `RESOLVED`, KB Post 없음, KB 버전 0 |
| Poller 상태 | 현재 해결 Post #441 재시도 99회, 이전 해결 Post #444도 대기 |
| KB 종합 질문 | 10,354자, UTF-8 17,145바이트 |
| 공식 검색 계약 | 최대 UTF-8 4,000바이트 |
| 직접 원인 | 제한된 `retrieval_question` 대신 원본 질문을 공식 검색에 전달해 `ProviderContractError` 발생 |
| 외부 증상 | Activepieces에는 일반 500 오류만 반환되고 Poller가 계속 재시도 |

관리자·지원 담당자의 일반 답변에 AI가 반응하지 않도록 한 정책은 이번 장애의 원인이 아니다. 해결 이벤트는 정상 접수됐고, 그 다음 단계인 KB 자료 검색 경계에서 실패했다.

## 3. 구현

- 공식 자료 검색에는 이미 생성된 UTF-8 4,000바이트 제한 `retrieval_question` 사용
- 공식 검색과 답변 생성의 Provider 계약 오류를 `PROVIDER_CONTRACT_REJECTED`로 명시
- 현재 Best Answer와 다른 오래된 Pending Resolution 자동 제거
- 긴 한글 KB 대화의 검색 질문 경계 회귀시험 추가
- 오래된 해결 재시도 정리 시험과 컨테이너 계약 시험 추가
- AI Gateway 버전 0.16.9 및 OpenAPI 39개 Operation 재생성

## 4. 운영 복구와 게시

Gateway와 Community Poller만 `techflow/ai-gateway:issue114-0.16.9-02061eb` 이미지로 교체했다. Source Reconciler, GitHub→Chat Event Gateway, Activepieces App·Worker는 재생성하거나 재시작하지 않았다.

재처리 과정에서 최초 게시 요청의 응답 확인이 일시적으로 실패했지만 Post #445 자체는 이미 공개 상태였다. 다음 멱등 재시도는 기존 KB 표식을 찾아 같은 Post #445를 재사용했으며 중복 Post를 만들지 않고 게시·솔루션 선택을 완료했다.

자동 생성된 Post #445는 같은 Post에서 다음 내용으로 보완했다.

- 증상, 원인, 해결 방법, 추가 고려사항, 적용 버전 구분
- `kvm.ha.on.storage.heartbeat=true` 확인
- `mold-agent.service` 재시작·상태 확인 명령
- 정상 기준 `Available`, HA 공급자 `kvmhaprovider`
- Console Proxy VM 접속과 관리 서버·Agent 로그 확인 방법
- 암호·토큰 등 비밀정보 마스킹 안내
- 적용 버전 `ABLESTACK Diplo`

최종 KB Post #445는 공개·승인 상태이며 Discussion #177의 현재 해결 답변이다. Case는 KB 원본 Post #441, KB Post #445, KB 버전 2를 기록한다.

## 5. 검증 결과

| 항목 | 결과 |
|---|---|
| WSL ext4 전체 시험 | 346건 통과 |
| 변경 파일 Ruff | 통과 |
| OpenAPI | 39개 Operation |
| Gateway | 0.16.9, Healthy, Restart 0 |
| Community Poller | Healthy, Restart 0 |
| Pending Post | 0건 |
| Pending Resolution | 0건 |
| Discussion #177 KB Post | #445 |
| KB 원본 해결 Post | #441 |
| KB 버전 | 2 |
| 최종 솔루션 | Post #445 선택 완료 |
| Community·Chat | HTTP 200 |
| 보호 서비스 변경 | 0건 |

브라우저에서 Discussion #177을 직접 열어 `해결됨`, `최종 해결 가이드`, `해결된 답변` 표시와 전체 문서 내용, 명령, 해결 답변 선택 상태를 확인했다.

## 6. 배포와 복구 정보

- 배포 Commit: `02061eb`
- 배포 패키지: `ai-gateway-0.16.9-02061eb.tar.gz`
- SHA-256: `3AB72BFC9920EB5EE2137184CB1A106DE06B9931BF70EB6CEFDF07060A27B654`
- 운영 백업: `/home/ablecloud/techflow-ai-gateway-backups/issue114-kb-boundary-20260904T011509Z`
- DB Schema 변경: 없음
- 운영 임시 진단·배포 파일: 제거 완료

## 7. 관련 자산

- Issue #114
- PR #110
- `docs/evidence/issue-114/discussion-177-kb-recovery.json`

