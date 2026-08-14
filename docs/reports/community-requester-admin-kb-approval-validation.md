# Community 질문자·관리자 Knowledge Base 승인 변경 보고서

- 변경일: 2026-08-14
- 구현 버전: TechFlow AI Gateway 0.14.8
- 대상: Community 해결 판정과 Knowledge Base 자동 생성
- PR: #65

## 1. 변경 목적

기존 정책은 최초 질문자가 직접 Best Answer를 선택해야만 Knowledge Base가 생성됐다. 질문자가 장기간 접속하지 않거나 기술지원 담당자가 이미 해결 결과를 확인한 경우에도 처리를 끝낼 수 없어 운영 부담이 컸다.

이를 다음과 같이 변경했다.

- 최초 질문자가 해결 답변을 선택하면 기존과 같이 KB를 생성한다.
- 운영 설정에 등록된 Community 관리자가 해결 답변을 선택해도 KB를 생성한다.
- 최초 질문자도 등록 관리자도 아닌 일반 참여자의 선택은 해결 승인으로 인정하지 않는다.
- KB 게시 후 시스템이 KB Post를 최종 솔루션으로 지정하는 기존 멱등·검증 절차는 유지한다.

## 2. 신뢰 경계

Flarum 해결 이벤트는 Best Answer Post ID와 선택자 User ID를 전달한다. Gateway는 이벤트에 관리자 역할을 직접 입력받지 않는다. 선택자 User ID를 다음 운영 설정과 비교해 관리자 여부를 내부에서 결정한다.

[FoF Best Answer 공식 구현](https://github.com/FriendsOfFlarum/best-answer/blob/2.x/src/Api/DiscussionAttributes.php)도 Best Answer를 설정할 때 `best_answer_user_id`에 선택 동작을 수행한 Actor ID를 기록한다. 따라서 Poller의 `bestAnswerUserId`를 해결 답변 작성자가 아니라 해결 선택자의 ID로 사용하는 현재 계약과 일치한다.

```dotenv
TECHFLOW_FLARUM_RESOLUTION_ADMIN_USER_IDS=1,7
```

여러 관리자는 쉼표로 구분한다. 기존 `TECHFLOW_FLARUM_SOLUTION_SELECTOR_USER_ID_FILE`의 최종 KB selector User ID도 자동으로 관리자 집합에 포함된다. 따라서 현재 단일 관리자 환경은 별도 설정 없이 호환되고, 추가 관리자만 환경값에 등록하면 된다.

## 3. 상태와 감사 이벤트

| 선택자 | 상태 | 감사 이벤트 | KB 생성 |
| --- | --- | --- | --- |
| 최초 질문자 | `RESOLVED` | `RESOLVED_BY_REQUESTER` | 실행 |
| 등록 관리자 | `RESOLVED` | `RESOLVED_BY_ADMINISTRATOR` | 실행 |
| 일반 참여자 | `WAITING_RESOLUTION` | `RESOLUTION_REVIEW_REQUIRED` | 실행하지 않음 |
| 시스템이 게시한 KB Post | `RESOLVED` 유지 | `KNOWLEDGE_BASE_SOLUTION_CONFIRMED` | 기존 KB 재사용 |

감사 이벤트의 `resolutionActorRole`에는 `REQUESTER`, `ADMINISTRATOR`, `OTHER` 중 하나를 기록한다. 실제 선택자 ID는 기존 `resolved_by_user_id`와 이벤트 Actor에 보존한다.

## 4. 구현 범위

- `app/config.py`: 추가 관리자 ID 목록의 환경 설정·검증
- `app/main.py`: selector ID와 관리자 허용 목록을 이용한 내부 권한 판정
- `app/store.py`: Memory Store의 질문자·관리자 해결 상태 전이
- `app/postgres_store.py`: PostgreSQL Store의 동일 상태 전이와 감사 정보
- Compose와 환경 예제: 추가 관리자 설정 노출
- ADR, 설계, Runbook, README, 사용자 가이드: 변경 정책 반영
- 사용자 가이드 PDF: 동일 내용으로 재생성

DB Schema 변경과 Migration은 없다. 기존 Case와 해결 기록은 그대로 사용할 수 있다.

## 5. 검증

집중 단위·API 테스트에서 다음을 확인했다.

1. 최초 질문자 선택은 계속 `RESOLVED`가 된다.
2. 등록 관리자 선택은 `RESOLVED_BY_ADMINISTRATOR`와 함께 `RESOLVED`가 된다.
3. 관리자 선택자의 User ID와 선택 Post가 해결 증적으로 저장된다.
4. 설정되지 않은 일반 참여자의 선택은 `WAITING_RESOLUTION`에 남는다.
5. 외부 요청은 관리자 역할을 직접 지정할 수 없고 Gateway가 운영 설정으로 판정한다.
6. 최종 KB selector identity는 관리자 집합에 자동 포함된다.
7. 잘못된 관리자 User ID 설정은 기동 검증에서 거부된다.

구현 후 `tests.test_config`와 `tests.test_community` 집중 시험 47건, AI Gateway 전체 단위·통합 회귀시험 248건이 모두 통과했다. 사용자 가이드 PDF는 A4 6페이지로 생성했으며 텍스트 필수 항목, 암호화 여부, 페이지 크기를 자동 검사하고 전체 페이지 PNG 렌더링으로 한글 깨짐·겹침·잘림이 없음을 확인했다.

## 6. 운영 적용

추가 관리자가 없다면 기존 selector identity가 관리자로 자동 인식되므로 설정 변경이 필요 없다. 추가 관리자가 있다면 `.env`에 Flarum User ID를 등록하고 Gateway만 재생성한다.

```dotenv
TECHFLOW_FLARUM_RESOLUTION_ADMIN_USER_IDS=1,7
```

정상 판정은 관리자가 실제 해결 답변을 선택한 후 다음을 모두 만족하는 것이다.

- Case `conversationState=RESOLVED`
- 감사 이벤트 `RESOLVED_BY_ADMINISTRATOR`
- `knowledge_base_post_id` 생성
- `knowledge_base_solution_selected_at` 기록
- Flarum의 최종 Best Answer가 KB Post와 일치

기존 GitHub-to-Chat Event Gateway는 이번 변경 범위에 포함되지 않는다.
