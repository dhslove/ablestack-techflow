# Issue #69 Community 자동 답변·Knowledge Base 구현 및 검증 보고서

- 검증일: 2026-08-14
- 환경: TechFlow 시험 서버, ABLESTACK Community, Synology Chat
- 릴리스: TechFlow AI Gateway 0.14.4
- 구현 PR: [#65](https://github.com/ablecloud-team/ablestack-techflow/pull/65)
- 실제 후속 질문: [Discussion #164](https://community.ablecloud.io/d/164-gasangmeosin-sijag-mic-maigeureisyeon-oryu)
- 자동 게시·KB E2E: [Discussion #165](https://community.ablecloud.io/d/165-techflow-knowledge-base)
- 해결 우선 후속 답변 E2E: [Discussion #166 Post #377](https://community.ablecloud.io/d/166/377)
- 다중 참여자·CLI 블록 E2E: [Discussion #167 Post #381](https://community.ablecloud.io/d/167/381)

## 1. 결론

Community Assist의 관리자 승인 단계를 제거했다. AI-Assistant는 신규 질문과 후속 질문에 바로 답변하고, Chat은 승인 대신 게시 결과와 원문 링크를 담당자에게 알려주는 관찰 채널로 동작한다.

진행 중 답변은 더 이상 매번 `증상·원인·해결 방법·추가 고려사항·적용 버전`을 강제하지 않는다. 전문 엔지니어가 플랫폼을 처음 접한 사용자에게 설명하듯 현재 판단, 안전한 확인 순서, 추가로 필요한 정보와 다음 행동을 쉬운 문장으로 안내한다. 질문자가 해결 답변을 선택한 뒤에만 해당 답변과 전체 대화를 다시 종합해 Knowledge Base 최종본을 게시하고, 게시된 KB Post를 Discussion의 최종 솔루션으로 지정한다.

0.14.3에서는 후속 답변이 같은 점검 목록을 반복하지 않도록 해결 우선 정책과 진행성 검사를 추가했다. 최신 질문에 직접 답하고 가장 가능성이 높은 안전한 해결 방법, 근거 있는 CLI, 실행 위치와 성공 기준을 먼저 제시한다. 첫 조치가 실패했을 때만 대안과 정확한 명령 출력·로그를 요청한다. 첫 생성이 직전 답변을 반복하면 한 번 재작성하며, 재작성도 새 단계가 없으면 게시하지 않고 503 재시도로 남긴다.

0.14.4에서는 최초 질문자와 다른 사람의 후속 댓글도 최신 사람 입력으로 처리한다. AI-Assistant 자신의 Post만 재응답 대상에서 제외한다. 설명과 CLI를 같은 문장에 섞지 않고, 설명 다음에 바로 복사할 수 있는 독립된 `bash` 코드 블록을 배치한다.

0.14.1에서는 `[읽기 전용]`, `[변경 없음]`, `[호스트 관리자]`, `[네트워크 관리자]`처럼 내부 실행 정책을 나타내는 접두어도 사용자 답변에서 제거했다. 안전성 판단은 내부에 유지하되, 사용자가 알아야 할 내용만 `서버 관리자는 D-Bus 상태를 확인해 주세요`, `DB의 template ID는 직접 수정하지 마세요`처럼 자연스러운 문장으로 전달한다.

## 2. 최종 동작

| 구분 | 구현 결과 |
| --- | --- |
| 신규·후속 질문 | AI-Assistant 답변 즉시 공개 |
| 다중 참여자 | 최초 질문자와 다른 사람의 댓글도 같은 Conversation 진행 |
| 후속 답변 진행 | 해결책·CLI·성공 기준 우선, 미해결 시에만 대안·로그 요청 |
| CLI 표시 | 설명 다음의 독립된 `bash` 코드 블록, 인라인 실행 명령 금지 |
| 반복 답변 | 한 번 재작성 후에도 새 단계가 없으면 게시 차단 |
| 근거 부족 | 빈 초안 대신 필요한 버전·시각·로그·화면 요청 |
| 대화 맥락 | Best Answer 선택 전까지 Discussion 단위 유지 |
| 첨부자료 | 이미지·로그·ZIP/TAR.GZ 분석 결과를 같은 맥락에 누적 |
| 해결 선택 | 질문자 Best Answer만 `RESOLVED`로 인정 |
| 최종 문서 | 선택 답변 중심 KB를 한 번만 게시 |
| Chat | 게시·KB·실패 상태와 원문 링크 알림 |
| 내부 근거 | Community에는 숨기고 `근거 <Case>`에서만 조회 |
| Ops 승인 | 인프라 변경 승인 정책은 그대로 유지 |

### 2.1 내부 작업 분류 비노출

| AI 원문 | 사용자 공개 문장 |
| --- | --- |
| `[변경 없음] DB에서 template ID를 직접 수정하지 마십시오.` | `DB에서 template ID를 직접 수정하지 마십시오.` |
| `[읽기 전용·호스트 관리자] PYHVS5에서 D-Bus 상태를 확인하십시오.` | `서버 관리자는 PYHVS5에서 D-Bus 상태를 확인하십시오.` |
| `[읽기 전용·네트워크 관리자] 원본 호스트에서 대상 포트 연결을 확인하십시오.` | `네트워크 관리자는 원본 호스트에서 대상 포트 연결을 확인하십시오.` |
| `[읽기 전용] Mold에서 호스트 상태를 확인하십시오.` | `Mold에서 호스트 상태를 확인하십시오.` |

모델 지침에서 내부 라벨 생성을 금지하고, 모델이 기존 형식으로 응답하더라도 공개 직전 변환 계층에서 제거하는 이중 방어를 적용했다. `[주의]`처럼 사용자에게 실제 의미가 있는 표시는 유지한다.

## 3. 실제 E2E

### 3.1 Discussion #164 기존 답변 전환

기존 Flarum 승인 방식으로 공개된 문서형 Post #362를 새 정책으로 한 번만 마이그레이션했다.

- 자동 공개 Post: #363
- 작성자: AI-Assistant(User 40)
- Case Reviewer: `techflow:auto`
- 상태: `PUBLISHED / WAITING_RESOLUTION`
- 제목형 Heading: 없음
- 내부 Citation·Repository·Commit: 없음
- 보이는 시스템 Marker: 없음

이후 질문자가 Diplo 빌드와 추가 질문을 Post #364로 등록하자 Poller → Activepieces → AI Gateway 경로가 자동 실행되어 Post #365를 승인 없이 공개했다. 답변은 앞서 제공된 자료를 반복 요청하지 않도록 안내하고, 안전한 확인 순서와 필요한 로그를 자연스러운 문장으로 제시했다.

### 3.2 근거 부족 답변도 자동 공개

시험 Discussion #165의 최초 질문 Post #366은 검색 근거가 충분하지 않아 AI가 `ABSTAINED`를 반환했다. 기존 구현이라면 본문이 없는 `DRAFT_PENDING`으로 남았지만, 보완 후 다음 내용을 담은 Post #367을 즉시 공개했다.

- 현재 정보만으로 원인을 안전하게 좁히기 어렵다는 설명
- ABLESTACK Diplo 버전과 발생 시각 요청
- 관리 서버·호스트 로그 또는 화면 캡처 요청
- 같은 질문 맥락에서 후속 안내를 계속한다는 설명

Post #367은 Heading, 내부 근거, 보이는 Marker가 없고 Flarum `isApproved=true`이다.

### 3.3 해결 선택 후 Knowledge Base

시험 질문자(User 1)가 Post #367을 Best Answer로 선택했다. Poller가 해결 이벤트를 전달하고 Case는 `RESOLVED`로 전환됐다. AI가 근거 부족을 유지했으므로 원인을 지어내지 않고 다음 형식의 Post #368을 공개했다.

1. 증상
2. 원인
3. 해결 방법
4. 추가 고려사항
5. 적용 버전

최종 증적:

- `resolved_post_id=367`
- `knowledge_base_post_id=368`
- `knowledge_base_source_post_id=367`
- `knowledge_base_version=1`
- `knowledge_base_solution_selected_at=2026-08-13 12:20:20 UTC`
- `knowledge_base_solution_selected_by_user_id=1`
- Flarum 최종 Best Answer: Post #368
- 적용 버전: `ABLESTACK Diplo`, `ABLESTACK Europa`
- 내부 Citation·Repository·Commit: 없음
- 같은 해결 이벤트 재실행: `resolutionChanged=false`, Post #368 재사용, Version 1 유지

### 3.4 Discussion #166 반복 답변 교정

Discussion #166의 Post #374와 #376은 모두 QEMU Guest Agent 상태, 마운트 정보, 권한과 SELinux 로그를 확인해 달라는 일반 목록을 반복했다. 질문자가 Post #375에서 “새 디스크를 연결한 뒤 발생하며 SELinux가 원인일 수 있는가”라고 범위를 좁혔지만, 두 번째 답변도 구체적인 명령이나 성공 기준 없이 같은 자료를 다시 요청했다.

0.14.3은 실제 대화 전체를 넣은 OpenAI 시험에서 `ANSWERED / INSUFFICIENT_EVIDENCE`로 응답했다. Doc·Diplo·연관 제품 코드·Europa Preview·승인된 QEMU 플랫폼 근거를 모두 검토했으며, 사용자 공개 답변은 다음 단계로 진행했다.

1. SELinux 가능성에 직접 답하되 AVC가 있어야 확정한다고 설명
2. 게스트에서 `ausearch`와 `matchpathcon` 실행
3. `virt_qemu_ga_t` 거부와 문맥 불일치가 함께 있을 때만 `restorecon`
4. Mold 스냅샷·복제 재시도와 `Permission denied` 소멸을 성공 기준으로 제시
5. 실패할 때만 `findmnt`, `ls -ldZ`, `namei`, `getfacl`, QEMU Guest Agent 로그 요청

정정 답변은 TechFlow-Assistant Post #377로 공개됐고 `isApproved=true`를 재조회했다. Poller는 이를 `ASSISTANT` Turn으로 수집해 `seenPosts=131`, `failed=0`을 기록했다. 공개 본문에는 내부 Citation·Repository·Commit·Source 경로가 없으며, SELinux 전체 비활성화, `chmod 777`, 근거 없는 `audit2allow`을 사용하지 말라는 안전 조건을 포함한다.

### 3.5 Discussion #167 다른 참여자의 후속 질문 복구

Discussion #167의 최초 질문 Post #378은 User 12가 작성했고 AI-Assistant가 Post #379로 답했다. 후속 질문 Post #380은 User 13이 작성했다. 기존 Poller는 최초 작성자만 `REQUESTER / responseRequested=true`로 처리하고 다른 사람을 `STAFF / responseRequested=false`로 저장했기 때문에 Gateway는 Post #380을 10.28ms 만에 기록만 하고 AI 분석을 시작하지 않았다. Provider, Gateway, 반복 답변 차단의 장애는 아니었다.

0.14.4는 `REQUESTER`와 `STAFF`를 모두 사람 입력으로 처리한다. Post #380은 이미 구버전 체크포인트에 저장돼 있어 전체 대화를 새 분석 경로에 한 번 다시 넣었다. 실제 OpenAI 응답은 `ANSWERED / INSUFFICIENT_EVIDENCE`, Europa 비교는 `PREVIEW_NOT_FOUND`였고 9개 Source Profile을 모두 검토했다. SELinux 가능성은 AVC와 보안 문맥 불일치가 함께 있을 때만 높다고 답하고 `ausearch`, `matchpathcon`, 조건부 `restorecon`, 권한·마운트 확인, QEMU Guest Agent 로그 순서로 진행했다.

교정 답변은 AI-Assistant Post #381로 공개됐다. Flarum API 재조회 결과 `isApproved=true`, `<pre><code class="language-bash">` 5개, 실행 명령을 담은 인라인 `<code>` 0개였다. Poller는 Post #381을 Assistant Turn으로 한 번 수집해 `seenPosts=135`, `failed=0`을 기록하고 자기 응답을 다시 만들지 않았다.

## 4. 구현 상세

### 4.1 상태와 데이터

Migration `0012`는 `community_case`에 KB Post ID·URL, 선택 답변 Post ID, 최종 본문, Version, 게시 시각 6개 열을 추가했다. Migration `0013`은 최종 솔루션 지정 시각과 지정 사용자 ID 2개 열을 추가했다. 일반 자동 답변은 `AUTO_PUBLISHED`, 최종 KB는 `KNOWLEDGE_BASE_PUBLISHED`, 최종 솔루션 지정은 `KNOWLEDGE_BASE_SOLUTION_SELECTED` 이벤트로 감사 이력을 남긴다.

### 4.2 Flarum 공개

AI-Assistant 계정으로 Post를 생성한다. Flarum Approval 확장이 Assistant 글을 보류하면 통합 권한이 방금 생성한 정확한 Post만 공개 전환한다. 사람의 승인 대기열은 사용하지 않는다.

재시도 Marker는 원문을 그대로 붙이지 않는다. Marker를 SHA-256한 0폭 링크를 사용해 중복 게시를 막고, 사용자 화면에는 시스템 식별자가 보이지 않게 했다.

KB 공개 후에는 별도 selector identity로 Discussion의 `bestAnswerPostId`를 KB Post ID로 변경한다. 이어서 `bestAnswerPost`를 재조회해 정확히 일치할 때만 완료 상태를 저장한다. 질문자가 처음 선택한 Post #367은 `resolved_post_id`와 `knowledge_base_source_post_id`로 유지하고, 최종 솔루션 Post #368과 분리했다.

### 4.3 Chat 관찰

Chat의 `승인`, `수정`, `반려` 명령은 상태를 바꾸지 않고 자동 게시 정책을 안내한다. 담당자는 다음 명령만 사용한다.

- `대기`: 미게시·실패 Case 확인
- `상세 <Case>`: 질문과 Community 원문 링크 확인
- `근거 <Case>`: 내부 Citation과 Coverage 확인
- `이력 <Case>`: 자동 게시와 KB 감사 이력 확인

### 4.4 해결 우선 생성과 진행성 검사

Conversation Prompt는 최초 질문·최신 사람 참여자의 추가 정보·직전 TechFlow 답변·최근 Turn을 구분한다. Provider 정책은 `recommendedActions`에 해결 방법을 먼저 쓰고, CLI가 근거에 있을 때 실행 위치·명령·정상 판정 기준을 함께 작성하게 한다. 설명과 명령을 분리하고 실행 명령은 독립된 `bash` 코드 블록으로 출력한다. `unknowns`는 해당 조치 후에도 실패할 때 필요한 정확한 출력에만 사용한다.

Gateway는 직전 Assistant Turn이 있는 후속 답변에서 새 CLI 또는 실제 조치가 추가됐는지 검사한다. 같은 일반 점검 목록이면 한 번 더 엄격하게 재작성한다. 두 번째 결과도 진행되지 않으면 `COMMUNITY_RESPONSE_NOT_PROGRESSING`으로 게시하지 않으며 Poller가 동일 Post를 재시도한다.

## 5. 장애·재시도 검증

삭제된 Discussion #163의 과거 해결 이력으로 KB를 생성했을 때 Flarum 404가 발생했다. TechFlow는 해결 상태를 유지하고 KB를 게시 완료로 기록하지 않은 채 HTTP 503을 반환했다. 실제 존재하는 Discussion #165로 재검증해 Post #368 게시를 완료했다.

`ABSTAINED`가 빈 초안으로 남는 문제와 HTML 주석 Marker가 사용자 화면에 보이는 문제도 E2E 중 발견했다. 각각 안전한 정보 요청 답변과 보이지 않는 해시 링크로 보완했다.

최초 KB 솔루션 지정 시 API Key만 사용한 Discussion PATCH가 Flarum의 `csrf_token_mismatch`로 거부됐다. Flarum User 1이 관리자 그룹임을 API로 검증하고, 이를 별도의 runtime-only selector identity 파일로 분리했다. 재배포 후 Post #368 지정과 재조회가 성공했으며, Poller가 변경을 다시 수집한 뒤에도 Case는 `RESOLVED`, 원본 해결 Post는 #367로 유지됐다.

## 6. 검증 결과

| 항목 | 결과 |
| --- | --- |
| Python 단위·통합 테스트 | 225건 전체 통과 |
| OpenAPI | 34 Operations |
| DB Migration | 24 Tables, KB Columns 8, 검증 통과 |
| Gateway Health | Process·Database·Vector `ready`, Provider `openai` |
| Gateway Version | 0.14.4 |
| Discussion #164 후속 자동 답변 | Post #365, 공개 완료 |
| Discussion #165 근거 부족 자동 답변 | Post #367, 공개 완료 |
| Discussion #165 KB | Post #368, Version 1, 최종 Best Answer 지정 완료 |
| Discussion #166 해결 우선 정정 답변 | Post #377, 공개·Turn 수집 완료 |
| Discussion #167 다중 참여자 후속 답변 | Post #381, 코드 블록 5개·인라인 CLI 0개·Turn 수집 완료 |
| Chat 담당자 | 자동 게시 알림 전송 확인 |
| 내부 근거·Marker 공개 | 0건 |
| 루트 디스크 | 1005G 중 44G 사용, 921G 여유 |

0.14.4 시험 서버 Health는 `provider=openai`, `version=0.14.4`, Process·Database·Vector `ready`이다. 실제 Discussion #167 교정 뒤 Poller는 `seenPosts=135`, `failed=0`을 기록했다.

## 7. 배포·복구 자산

배포 전 Gateway 소스·Migration·Compose·환경 설정과 PostgreSQL 전체 덤프를 서버 내부 권한 제한 디렉터리에 백업했다.

- 백업: `/home/ablecloud/techflow-ai-gateway/backups/issue69-predeploy-20260813T073633Z`
- DB 덤프: 1,756,637,470 bytes
- SHA-256: `9efb843ee23d1076c5da5cfc91aa6a5adcde58997a05949dd82edfac321ef565`
- 배포 이미지: `techflow/ai-gateway:issue-69-community-auto-publish-kb`

0.14.1 코드 전용 배포 전 백업은 `/home/ablecloud/techflow-ai-gateway/backups/issue69-labels-predeploy-20260813T083224Z`에 보관했다. `runtime-source.tgz` SHA-256은 `d91b59daf8a2b6a67237fa2fc645b8eabc2fc322c6c4f0612445b5282757590e`이며, 직전 Gateway Image ID와 보호 서비스 상태도 함께 기록했다. DB Schema와 데이터는 변경하지 않았다.

0.14.2 KB 최종 솔루션 배포 전 백업은 `/home/ablecloud/techflow-ai-gateway/backups/issue69-kb-solution-predeploy-20260813T120805Z`에 보관했다.

- Runtime Source SHA-256: `0f65dcf6a0e3609a804f112058529fa259b91bf44a1f5b6abbd8de3e34d32f5c`
- 실제 Compose Build Context SHA-256: `46cd15b112aabb2dcbe6fa0afb94e25c00401fca09fc11a59fe18da9bcd35b21`
- PostgreSQL 전체 Dump SHA-256: `7d5ddd9886d0b6604f460d3aaa8439284e83382c3c016cb0514bb2a1b12609c7`
- Migration: `0013_community_kb_solution_up.sql`

0.14.3 해결 우선 답변 배포 전 백업은 `/home/ablecloud/techflow-ai-gateway/backups/issue69-solution-first-predeploy-20260814T024413Z`에 보관했다.

- 실제 Build Context Source SHA-256: `ea728d57636cd3b51aa2bc843d45eed55c41a5d36ec3545b14c09a0f56edb95a`
- PostgreSQL 전체 Dump SHA-256: `d3c71b061b274197ca1331fd04484f5b10b6b0e801b5d94d4ad78fce9b8a2bc2`
- 배포 Image ID: `sha256:561755edc470d4e3c095ab97034dfe19989c8c5e907255aae2903ddf1ff833cf`
- DB Schema Migration: 없음

0.14.4 다중 참여자·CLI 블록 배포 전 백업은 `/home/ablecloud/techflow-ai-gateway/backups/issue69-participant-followup-predeploy-20260814T0337Z`에 보관했다.

- Runtime Source·Compose SHA-256: `7dda0166a9e7a13fd7d539b33bcc2efd4c96b2c0a524d2f749e7f863948efabf`
- PostgreSQL 전체 Dump SHA-256: `7eba47e7f849ed176da55908a74576e1879188a37d8ce6a6d3b95cf52de5951a`
- PostgreSQL 압축 Dump 크기: 약 1.7GB
- 배포 Image ID: `sha256:855a25eda14d758a4150604672f9df837e6c352d5725161d616edf5aabf82819`
- DB Schema Migration: 없음
- 배포 대상: Gateway·Community Poller만 재생성
- 보호 대상 Event Gateway: Container ID와 Image ID 변경 없음

첫 배포 시도에서는 서버 루트의 복사본을 갱신했지만 Compose 실제 Build Context가 `/home/ablecloud/techflow-ai-gateway/services/ai-gateway`인 것을 확인했다. 이 시도는 Docker가 기존 0.14.1 Layer를 재사용해 Schema·데이터 변경 없이 종료됐다. 실제 Build Context를 추가 백업하고 올바른 경로에서 캐시 없이 0.14.2를 빌드해 `knowledgeColumns=8`과 Health를 재검증했다.

최초 재생성 검증에서 기본 Compose만 사용해 Provider가 `mock`으로 기동한 것을 발견했다. 즉시 `compose.openai.override.yml`을 포함해 Gateway와 Poller를 다시 생성했고 최종 Health의 `provider=openai`를 확인했다. 이 재발 방지 조건을 운영 Runbook의 필수 명령으로 추가했다.

Rollback은 자동 게시 환경값을 끄고 Gateway·Poller를 이전 이미지로 되돌린 뒤, 필요할 때 Migration `0012 down`을 적용한다. 이미 공개된 Community 답변과 KB는 자동 삭제하지 않는다.

보호 대상 GitHub→Chat Event Gateway는 작업 전후 Container ID `bf5c76824dbf`, Image `ablestack-techflow/event-gateway:0.4.0`, 생성 시각이 동일하다. 변경·재배포·재시작하지 않았다.

## 8. 완료 판단

Issue #69의 완료 기준을 충족했다.

1. 진행 답변은 쉬운 대화형 문장으로 승인 없이 공개된다.
2. 근거가 부족해도 필요한 정보를 요청하는 답변이 남는다.
3. 질문자 해결 선택 전까지 같은 맥락을 유지한다.
4. 해결 선택 후에만 정형 Knowledge Base가 생성된다.
5. KB는 선택 Post와 연결되고 멱등하게 한 번만 게시된다.
6. 게시된 KB Post가 최종 Best Answer로 지정되고 API 재조회·DB 감사 상태가 일치한다.
7. 최초 질문자 선택 Post는 KB 생성 원본으로 보존된다.
8. Chat은 승인 없이 게시·솔루션 지정 상태를 관찰한다.
9. 사용자 본문에는 내부 근거와 시스템 Marker가 노출되지 않는다.
10. 내부 작업 분류는 공개되지 않고 필요한 담당자·주의사항만 자연어로 전달된다.
11. 후속 답변은 해결책·CLI·성공 기준을 먼저 제공하고, 실패한 경우에만 대안·정확한 로그를 요청한다.
12. 직전 답변을 되풀이하는 결과는 재작성하며 진행되지 않으면 공개하지 않는다.
13. 최초 질문자와 다른 사람의 후속 댓글도 같은 대화를 진행하고 Assistant 자신의 글은 재응답하지 않는다.
14. 설명과 CLI를 분리하며 실행 명령은 복사 가능한 `bash` 코드 블록으로 표시한다.
