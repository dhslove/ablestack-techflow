# Issue #64 결과물 생성기

이 디렉터리는 Issue #64 완료 보고서 PDF, 승인용 프레젠테이션 PPTX/PDF, 검증 결과를 재현한다.

생성 순서:

1. `build_report.py`
2. `build_presentation.mjs`
3. `build_presentation_pdf.py`
4. `validate_artifacts.py`

PPTX 생성은 Codex workspace의 `@oai/artifact-tool` 런타임을 사용한다. 모든 산출물은 `output/` 아래에 기록한다.
