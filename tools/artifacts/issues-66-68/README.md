# Issues #66-#68 산출물 재생성

Community 지속 대화 구현 보고서와 검토 자료를 같은 입력 문서에서 다시 생성하고 검증한다.

```powershell
$python = 'C:\Users\ablecloud\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $python tools\artifacts\issues-66-68\build_report.py
& $python tools\artifacts\issues-66-68\build_presentation_pdf.py
& $python tools\artifacts\issues-66-68\build_manifest.py
& $python tools\artifacts\issues-66-68\validate_artifacts.py
```

PPTX는 `@oai/artifact-tool`로 생성한 뒤 `build_presentation_pdf.py`가 렌더 이미지를 PDF로 묶는다. `validate_artifacts.py`는 보고서 페이지·본문, 발표자료 페이지, PPTX 슬라이드·발표자 노트, Manifest의 SHA-256 대상을 함께 확인한다.

결과 파일은 다음 위치에 유지한다.

- `output/pdf/techflow-community-conversation-report.pdf`
- `output/pdf/techflow-community-conversation-presentation.pdf`
- `output/presentation/techflow-community-conversation.pptx`
- `output/issues-66-68-artifact-manifest.json`
