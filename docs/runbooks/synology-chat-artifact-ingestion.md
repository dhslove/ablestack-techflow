# Synology Chat 첨부자료 수집·분석 Runbook

## 목적

TechFlowAssist Bot에 이미지·로그·압축 로그를 보내면 Synology Chat 게시물의 `post_id`를 기준으로 파일을 안전하게 내려받아 AI Gateway Artifact로 등록하고, 현재 질문과 같은 미해결 대화의 후속 질문에 활용한다.

## 처리 흐름

1. Bot Outgoing URL이 `token`, `user_id`, `username`, `post_id`, `text`를 Gateway에 전달한다.
2. Gateway는 접수 응답을 즉시 반환하고 지속 Chat Job을 생성한다.
3. Job은 Bot Secret으로 Synology `post_file_get`을 호출한다. 사용자 제공 URL은 사용하지 않는다.
4. 응답은 Artifact Volume의 비공개 임시 파일로 1 MiB 단위 Streaming한다.
5. 파일명, MIME, Magic Byte, 실제 크기와 압축 안전 경계를 검증한다.
6. 검증된 파일은 ArtifactStore에 등록하고 Chat Turn에는 `artifactIds`만 저장한다.
7. 현재 질문의 Artifact는 반드시 분석한다. 이전 Turn의 Artifact는 최신 질문과 관련될 때 최대 5개까지 재사용한다.
8. 지원하지 않거나 손상된 파일은 원인을 한국어로 안내하고 원본을 분석했다고 주장하지 않는다.

## 지원 형식

- 이미지: PNG, JPEG, WebP
- 로그: LOG, TXT, OUT, ERR, JSON, JSONL, NDJSON, CSV, TSV, CONF 및 알려진 시스템 로그명
- 압축 로그: ZIP, GZIP, TGZ, TAR.GZ

PDF, DOCX, 실행파일과 일반 바이너리는 현재 분석 대상이 아니다. 지원하지 않는 파일은 Artifact를 생성하지 않고 경고를 Chat Turn에 기록한다.

## 안전 경계

- 일반 Artifact 최대 1 GiB, 압축 Artifact 최대 10 GiB
- 실제 Chat 전송 한계가 더 작으면 Synology Chat의 제한을 우선 적용
- 이미지 최대 12,000×12,000, 총 4천만 Pixel
- 압축 항목 기본 최대 100개
- 압축 해제 합계 최대 100 GiB, 압축률 기본 최대 20배
- 경로 탈출, Link·특수파일, 중첩 압축, 암호화 압축, 바이너리 위장 차단
- 로그의 Password·Token·API Key를 모델 전달 전에 마스킹
- D0 Artifact 기본 보존 24시간, 만료된 이전 첨부는 후속 질문에서 제외

## 장애 확인

1. Gateway `/healthz`의 Process·Database·Vector·Provider 상태를 확인한다.
2. `chat_assist_job`의 `state`, `attempt_count`, `last_error_type`을 확인한다.
3. 같은 `post_id`의 사용자 Turn에서 `artifact_checked=true`인지 확인한다.
4. 성공 파일은 `artifact_ids`가 1개, 제외 파일은 `artifact_warnings`가 1개 이상이어야 한다.
5. 다운로드 장애는 Job 재시도 대상이며, 형식·크기·안전 경계 위반은 사용자 경고로 완료한다.
6. 원본 파일은 DB나 로그에 기록하지 않는다.

## 롤백

AI Gateway 0.16.5에서 추가한 DB 열은 기존 Gateway가 무시할 수 있는 Additive Schema다. 우선 `.env`의 `TECHFLOW_RAG_RELEASE`를 이전 Image로 되돌리고 Gateway·Community Poller만 재생성한다. 데이터 복원이 필요한 경우에만 배포 전 `chat-assist.sql`을 사용한다. GitHub→Chat Event Gateway와 Activepieces 서비스는 롤백 대상에 포함하지 않는다.
