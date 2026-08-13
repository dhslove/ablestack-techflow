import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile, layers, shape, text } from "file:///C:/Users/ablecloud/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const ROOT = path.resolve(process.argv[2] ?? process.cwd());
const OUT_DIR = path.join(ROOT, "output", "presentation");
const QA_DIR = path.join(ROOT, "tmp", "artifacts", "issue-64", "qa");
const PPTX = path.join(OUT_DIR, "techflow-issue-64-answer-clarity.pptx");
const FONT = "Malgun Gothic";
const C = { navy: "#0F172A", blue: "#2563EB", sky: "#E0F2FE", green: "#15803D", mint: "#DCFCE7", amber: "#B45309", sand: "#FEF3C7", red: "#B91C1C", rose: "#FEE2E2", gray: "#475569", light: "#F8FAFC", line: "#CBD5E1", white: "#FFFFFF" };

function para(value, size = 22, bold = false, color = C.navy, align = "left") {
  return { runs: [{ run: value, textStyle: { fontSize: `${size}px`, typeface: FONT, bold, color } }], paragraphStyle: { lineSpacingPercent: 108000, alignment: align } };
}

function textbox(value, x, y, w, h, size = 22, bold = false, color = C.navy, align = "left", name = "text") {
  return text([para(value, size, bold, color, align)], { name, position: { left: x, top: y }, width: w, height: h, style: { fontSize: `${size}px`, typeface: FONT, color, alignment: align, verticalAlignment: "middle", autoFit: "shrinkText", insets: { top: 4, right: 8, bottom: 4, left: 8 } } });
}

function rect(x, y, w, h, fill, name, radius = false, line = "none") {
  return shape({ name, geometry: radius ? "roundRect" : "rect", fill, line: line === "none" ? { fill: "none" } : { fill: line, width: 1 }, position: { left: x, top: y }, width: w, height: h });
}

function header(title, number) {
  return [
    textbox(title, 54, 36, 1120, 76, 34, true, C.navy, "left", "title"),
    textbox(String(number).padStart(2, "0"), 1170, 646, 56, 28, 13, false, C.gray, "right", "page"),
  ];
}

function note(slide, sources) {
  slide.speakerNotes.textFrame.setText(`[Sources]\n${sources.map((s) => `- ${s}`).join("\n")}`);
}

function addSlide(items, sources) {
  const slide = deck.slides.add();
  slide.compose(layers({ name: "issue64", width: "fill", height: "fill" }, [rect(0, 0, 1280, 720, C.white, "background"), ...items]));
  note(slide, sources);
  return slide;
}

function card(x, y, w, h, title, body, fill = C.light, accent = C.blue) {
  return [rect(x, y, w, h, fill, `${title}-card`, true, C.line), rect(x, y, 8, h, accent, `${title}-accent`, true), textbox(title, x + 24, y + 16, w - 40, 34, 20, true, accent), textbox(body, x + 24, y + 56, w - 40, h - 72, 17, false, C.navy)];
}

const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });

addSlide([
  rect(0, 0, 1280, 720, C.navy, "cover"),
  textbox("ABLESTACK TECHFLOW · ISSUE #64", 62, 72, 900, 42, 22, true, "#93C5FD"),
  textbox("잘리지 않는 AI 답변,\nCommunity 원문에서 승인", 62, 164, 1040, 190, 58, true, C.white),
  textbox("텍스트 · 이미지 · 로그 압축까지 하나의 검토 경로", 68, 402, 960, 48, 25, false, "#CBD5E1"),
  rect(68, 510, 346, 82, C.blue, "result", true),
  textbox("시험 서버 E2E 완료", 88, 526, 306, 48, 24, true, C.white, "center"),
  textbox("2026-08-13", 1020, 642, 186, 30, 16, false, "#94A3B8", "right"),
], ["docs/reports/issue-64-answer-clarity-validation.md", "docs/plans/issue-64-answer-clarity-community-review-design.md"]);

addSlide([
  ...header("Chat의 역할을 알림으로 좁히고, 원문 검토를 복원했습니다", 2),
  ...card(64, 158, 344, 392, "이전", "긴 답변이 Chat 길이 제한에 걸려 문장이 잘림\n\n근거가 먼저 노출돼 일반 사용자 정보 경계가 불명확\n\n이미지·로그 분석 결과를 짧은 메시지에서 검증하기 어려움", C.rose, C.red),
  textbox("→", 438, 312, 84, 70, 48, true, C.blue, "center"),
  ...card(550, 158, 646, 392, "현재", "Chat: 새 검토 건과 Community 링크만 전달\n\nCommunity: 일반 AI 계정의 전체 답변을 승인 대기로 보관\n\n관리자: 원문·이미지·로그 분석을 한 화면에서 검토 후 승인\n\n일반 사용자: 승인된 답변만 열람", C.mint, C.green),
], ["docs/plans/issue-64-answer-clarity-community-review-design.md#2", "services/ai-gateway/app/chat_assist.py"]);

const flowXs = [48, 242, 436, 630, 824, 1018];
const flowTitles = ["질문", "첨부 정규화", "종합 분석", "미승인 원문", "Chat 링크", "관리자 승인"];
const flowBodies = ["본문·태그", "이미지·ZIP", "문서·코드·플랫폼", "일반 AI 계정", "전체 답변 없음", "Flarum 공개"];
const flowItems = [...header("전체 답변의 단일 원본은 Community입니다", 3)];
for (let i = 0; i < flowXs.length; i++) {
  if (i < flowXs.length - 1) flowItems.push(shape({ name: `arrow-${i}`, geometry: "straightConnector1", fill: "none", line: { fill: C.blue, width: 3, endArrowType: "triangle" }, position: { left: flowXs[i] + 152, top: 323 }, width: 42, height: 1 }));
  flowItems.push(rect(flowXs[i], 246, 152, 154, i === 3 ? C.sand : C.sky, `flow-${i}`, true, C.line));
  flowItems.push(textbox(flowTitles[i], flowXs[i] + 10, 264, 132, 42, 18, true, i === 3 ? C.amber : C.blue, "center"));
  flowItems.push(textbox(flowBodies[i], flowXs[i] + 10, 318, 132, 62, 15, false, C.navy, "center"));
}
flowItems.push(textbox("공개 권한은 AI가 아니라 Flarum 관리자에게 남습니다", 182, 475, 916, 54, 25, true, C.green, "center"));
addSlide(flowItems, ["docs/plans/issue-64-answer-clarity-community-review-design.md#2", "services/ai-gateway/app/community.py"]);

addSlide([
  ...header("답변은 전체 자료를 검토하되, 사용자에게는 필요한 내용만 보입니다", 4),
  ...card(64, 154, 544, 424, "내부 분석 순서", "1  ABLESTACK 문서\n\n2  Diplo 현재 코드 + 관련 제품 코드\n\n3  Europa 미출시 개선 Preview\n\n4  libvirt · QEMU · KVM 공식 자료\n\n5  승인된 기타 외부 자료", C.sky, C.blue),
  ...card(674, 154, 522, 198, "사용자 답변", "증상 · 원인 · 해결 방법\n추가 고려사항 · 적용 버전\n\n쉽고 짧은 문장, Citation 비노출", C.mint, C.green),
  ...card(674, 380, 522, 198, "내부 검토", "Evidence Ledger와 코드 위치 보존\n\n허용 Reviewer가 ‘근거 <ID>’를 명시할 때만 조회", C.sand, C.amber),
], ["docs/plans/issue-64-answer-clarity-community-review-design.md#4", "https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html", "https://www.libvirt.org/manpages/virsh.html"]);

addSlide([
  ...header("일반 AI 계정과 Flarum Approval이 공개 전 안전장치입니다", 5),
  ...card(58, 158, 358, 378, "계정", "TechFlow-Assistant\n\n관리자 권한 없음\n일반 Member만 보유\n비밀번호·키는 GitHub Secret과 서버 Secret으로 관리", C.sky, C.blue),
  ...card(461, 158, 358, 378, "강제 검증", "작성자 ID 확인\n\nisApproved=false 확인\n미승인 Post는 Assistant 문맥으로 조회\n조건 불일치 시 Chat 알림도 중단", C.sand, C.amber),
  ...card(864, 158, 358, 378, "승인", "Community 관리자만 공개\n\n승인 감지 후 Case PUBLISHED\n원본 삭제는 REJECTED\n중복 이벤트는 멱등 처리", C.mint, C.green),
], ["services/ai-gateway/app/community.py", "services/ai-gateway/app/main.py", "services/ai-gateway/migrations/0010_flarum_review_post_up.sql"]);

addSlide([
  ...header("세 가지 실제 입력을 새 Discussion으로 검증했습니다", 6),
  ...card(54, 152, 366, 408, "텍스트 · #159", "질문 전체 분석\n\nQEMU/VNC 가능성\n라이브 마이그레이션 우선\nStop/Start 대안\nCLI 확인 명령 포함\n\nPost #346 · 승인 대기", C.sky, C.blue),
  ...card(457, 152, 366, 408, "이미지 · #160", "실제 PNG 수집\n\n첨부가 콘솔 오류 화면이 아니라 품질 검증 슬라이드임을 구분\n이미지로 오류를 단정하지 않음\n\nPost #345 · 승인 대기", C.mint, C.green),
  ...card(860, 152, 366, 408, "ZIP 로그 · #162", "328 B ZIP · 로그 1개\n408 B 안전 추출\nstill_open · waiting 식별\nguest healthy 구분\n\nPost #349 · 승인·공개", C.sand, C.amber),
], ["https://community.ablecloud.io/d/159", "https://community.ablecloud.io/d/160", "https://community.ablecloud.io/d/162/349", "docs/reports/issue-64-answer-clarity-validation.md#4"]);

addSlide([
  ...header("코드·서버·운영 경계까지 함께 검증했습니다", 7),
  textbox("186", 72, 164, 260, 90, 62, true, C.blue, "center"),
  textbox("자동화 테스트 PASS", 72, 260, 260, 42, 21, true, C.navy, "center"),
  textbox("0", 510, 164, 260, 90, 62, true, C.green, "center"),
  textbox("Poller 재시도 실패", 510, 260, 260, 42, 21, true, C.navy, "center"),
  textbox("3%", 948, 164, 260, 90, 62, true, C.amber, "center"),
  textbox("1 TB 루트 볼륨 사용률", 948, 260, 260, 42, 21, true, C.navy, "center"),
  ...card(94, 374, 1092, 178, "보호 대상 확인", "GitHub→Chat event-gateway는 재시작·재배포·설정 변경 없이 동일 Container ID와 healthy 상태를 유지했습니다. Gateway·Poller만 새 이미지로 교체했고, 배포 전 소스·Compose·DB 백업을 남겼습니다.", C.light, C.blue),
], ["docs/reports/issue-64-answer-clarity-validation.md#6", "docs/runbooks/community-ai-review-post.md#8"]);

addSlide([
  rect(0, 0, 1280, 720, C.navy, "closing"),
  textbox("ISSUE #64 · REVIEW READY", 64, 68, 800, 42, 22, true, "#93C5FD"),
  textbox("전체 답변과 첨부 분석을\n공개 전에 검증할 수 있습니다", 64, 154, 1080, 168, 54, true, C.white),
  ...card(70, 406, 348, 136, "1", "Chat 링크 정책 승인", "#172554", "#60A5FA"),
  ...card(466, 406, 348, 136, "2", "일반 AI 계정 권한 승인", "#14532D", "#4ADE80"),
  ...card(862, 406, 348, 136, "3", "멀티 입력 E2E 결과 승인", "#78350F", "#FBBF24"),
], ["docs/reports/issue-64-answer-clarity-validation.md#8", "https://github.com/ablecloud-team/ablestack-techflow/issues/64"]);

async function saveBlob(target, blob) {
  await fs.writeFile(target, new Uint8Array(await blob.arrayBuffer()));
}

await fs.mkdir(OUT_DIR, { recursive: true });
await fs.mkdir(path.join(QA_DIR, "renders"), { recursive: true });
await fs.mkdir(path.join(QA_DIR, "layouts"), { recursive: true });
for (const [index, slide] of deck.slides.items.entries()) {
  const stem = `slide-${String(index + 1).padStart(2, "0")}`;
  await saveBlob(path.join(QA_DIR, "renders", `${stem}.png`), await deck.export({ slide, format: "png", scale: 2 }));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(path.join(QA_DIR, "layouts", `${stem}.json`), await layout.text(), "utf8");
}
await saveBlob(path.join(QA_DIR, "montage.webp"), await deck.export({ format: "webp", montage: true, scale: 1 }));
const inspection = await deck.inspect({ kind: "slide,textbox,shape,notes", maxChars: 120000 });
await fs.writeFile(path.join(QA_DIR, "inspect.ndjson"), inspection.ndjson, "utf8");
const pptx = await PresentationFile.exportPptx(deck);
await pptx.save(PPTX);
console.log(JSON.stringify({ pptx: PPTX, slides: deck.slides.items.length, qa: QA_DIR }));
