# Discussion #164 복구 보고 자산

```powershell
$runtimePython = 'C:\Users\ablecloud\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$runtimeNode = 'C:\Users\ablecloud\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$env:NODE_PATH = 'C:\Users\ablecloud\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'

& $runtimePython tools/artifacts/discussion-164/build_report.py
& $runtimeNode tools/artifacts/discussion-164/build_presentation.mjs (Get-Location).Path
& $runtimePython tools/artifacts/discussion-164/build_presentation_pdf.py
& $runtimePython tools/artifacts/discussion-164/build_manifest.py
& $runtimePython tools/artifacts/discussion-164/validate_artifacts.py
```

발표자료는 Artifact Tool로 생성하고 모든 슬라이드 PNG 및 Layout JSON을 `tmp/artifacts/discussion-164/qa`에 렌더링해 검수한다.
