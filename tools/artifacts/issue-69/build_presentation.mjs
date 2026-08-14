import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile, layers, shape, text } from "@oai/artifact-tool";

const ROOT = path.resolve(process.argv[2] ?? process.cwd());
const OUT_DIR = path.join(ROOT, "output", "presentation");
const QA_DIR = path.join(ROOT, "tmp", "artifacts", "issue-69", "qa");
const PPTX = path.join(OUT_DIR, "techflow-community-auto-publish-kb.pptx");
const FONT = "Malgun Gothic";
const C = { ink: "#0F172A", blue: "#2563EB", cyan: "#38BDF8", green: "#15803D", amber: "#B45309", red: "#B91C1C", white: "#FFFFFF", pale: "#F1F5F9", rule: "#CBD5E1", gray: "#475569" };

function para(value, size = 20, bold = false, color = C.ink, align = "left") {
  return { runs: [{ run: value, textStyle: { fontSize: `${size}px`, typeface: FONT, bold, color } }], paragraphStyle: { lineSpacingPercent: 108000, alignment: align } };
}
function textbox(value, x, y, w, h, size = 20, bold = false, color = C.ink, align = "left", name = "text") {
  return text([para(value, size, bold, color, align)], { name, position: { left: x, top: y }, width: w, height: h, style: { fontSize: `${size}px`, typeface: FONT, color, alignment: align, verticalAlignment: "middle", autoFit: "shrinkText", insets: { top: 4, right: 8, bottom: 4, left: 8 } } });
}
function rect(x, y, w, h, fill, name, line = "none") {
  return shape({ name, geometry: "rect", fill, line: line === "none" ? { fill: "none" } : { fill: line, width: 1 }, position: { left: x, top: y }, width: w, height: h });
}
function arrow(x, y, w) {
  return shape({ name: `arrow-${x}-${y}`, geometry: "straightConnector1", fill: "none", line: { fill: C.blue, width: 3, endArrowType: "triangle" }, position: { left: x, top: y }, width: w, height: 1 });
}
function header(title, number) {
  return [textbox(title, 54, 34, 1110, 82, 36, true), rect(54, 126, 1172, 2, C.rule, "rule"), textbox(String(number).padStart(2, "0"), 1170, 650, 56, 24, 16, false, C.gray, "right", "page")];
}
function note(slide, sources) {
  slide.speakerNotes.textFrame.setText(`[Sources]\n${sources.map((s) => `- ${s}`).join("\n")}`);
}
function addSlide(items, sources) {
  const slide = deck.slides.add();
  slide.compose(layers({ name: "issue-69", width: "fill", height: "fill" }, [rect(0, 0, 1280, 720, C.white, "background"), ...items]), { frame: { left: 0, top: 0, width: 1280, height: 720 }, baseUnit: 1 });
  note(slide, sources);
  return slide;
}

const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });

addSlide([
  rect(0, 0, 1280, 720, C.ink, "cover"),
  textbox("ABLESTACK TECHFLOW", 64, 62, 640, 42, 24, true, C.cyan),
  textbox("Community 자동 답변과\n최종 솔루션 Knowledge Base", 64, 150, 1100, 192, 58, true, C.white),
  textbox("승인 대기 제거 · 쉬운 대화 · KB 최종 솔루션", 70, 388, 1030, 52, 28, false, "#CBD5E1"),
  rect(70, 506, 440, 78, C.blue, "result"),
  textbox("AI Gateway 0.14.4", 88, 518, 404, 52, 26, true, C.white, "center"),
  textbox("Issue #69 · 2026-08-14", 824, 642, 390, 28, 17, false, "#94A3B8", "right"),
], ["docs/reports/issue-69-community-auto-publish-kb-validation.md"]);

addSlide([
  ...header("진행 답변과 최종 지식 문서를 분리했습니다", 2),
  rect(62, 174, 330, 330, "#FEE2E2", "before", C.rule),
  textbox("이전", 86, 196, 282, 42, 27, true, C.red, "center"),
  textbox("고정 5개 섹션\n관리자 승인 대기\nChat 승인 명령\n답변 지연", 86, 260, 282, 184, 23, false, C.ink, "center"),
  arrow(418, 340, 92),
  rect(536, 174, 330, 330, "#E0F2FE", "ongoing", C.rule),
  textbox("진행 중", 560, 196, 282, 42, 27, true, C.blue, "center"),
  textbox("해결책과 CLI 우선\n명령은 코드 블록\n모든 사람의 후속 질문\n반복 답변 게시 차단", 560, 260, 282, 184, 23, false, C.ink, "center"),
  arrow(892, 340, 92),
  rect(1010, 174, 208, 330, "#DCFCE7", "final", C.rule),
  textbox("해결 후", 1024, 196, 180, 42, 27, true, C.green, "center"),
  textbox("선택 답변 중심\nKnowledge Base\n최종 솔루션 지정", 1024, 278, 180, 142, 22, false, C.ink, "center"),
  textbox("Chat은 게시·실패·KB 최종 지정 상태를 관찰합니다", 124, 548, 1032, 54, 25, true, C.blue, "center"),
], ["docs/adr/0010-community-auto-publish-knowledge-base.md", "docs/plans/issue-69-community-auto-publish-kb-design.md"]);

const flow = [...header("질문부터 최종 솔루션까지 한 Conversation으로 이어집니다", 3)];
const xs = [62, 330, 598, 866];
const titles = ["질문·첨부", "자동 답변", "해결 선택", "KB·최종 지정"];
const bodies = ["모든 참여자\n첨부 자료", "쉬운 설명\nCLI 코드 블록", "질문자가\n답변 선택", "KB 게시 후\n솔루션 확정"];
for (let i = 0; i < xs.length; i++) {
  if (i < xs.length - 1) flow.push(arrow(xs[i] + 210, 320, 46));
  flow.push(rect(xs[i], 205, 216, 236, i === 3 ? "#DCFCE7" : C.pale, `flow-${i}`, C.rule));
  flow.push(textbox(String(i + 1), xs[i] + 70, 224, 76, 58, 38, true, i === 3 ? C.green : C.blue, "center"));
  flow.push(textbox(titles[i], xs[i] + 16, 292, 184, 44, 23, true, C.ink, "center"));
  flow.push(textbox(bodies[i], xs[i] + 16, 348, 184, 72, 19, false, C.gray, "center"));
}
flow.push(rect(146, 500, 988, 72, "#E0F2FE", "chat"));
flow.push(textbox("Chat Bot → 담당자에게 상태와 Community 원문 링크 알림", 170, 512, 940, 48, 24, true, C.blue, "center"));
addSlide(flow, ["docs/runbooks/community-conversation.md"]);

addSlide([
  ...header("Discussion #167의 후속 응답 누락과 CLI 가독성을 해결했습니다", 4),
  textbox("누락", 72, 178, 250, 82, 44, true, C.red, "center"),
  textbox("Post #380", 72, 270, 250, 38, 21, true, C.ink, "center"),
  textbox("다른 참여자를 STAFF로\n기록만 하고 응답하지 않음", 72, 342, 250, 92, 21, false, C.gray, "center"),
  rect(370, 170, 2, 360, C.rule, "divider-1"),
  textbox("연결", 420, 178, 250, 82, 44, true, C.blue, "center"),
  textbox("모든 사람 입력", 420, 270, 250, 38, 21, true, C.ink, "center"),
  textbox("REQUESTER · STAFF 응답\nAssistant 자신만 제외", 420, 334, 250, 112, 22, false, C.gray, "center"),
  rect(718, 170, 2, 360, C.rule, "divider-2"),
  textbox("표시", 768, 178, 250, 82, 44, true, C.green, "center"),
  textbox("CLI 코드 블록", 768, 270, 250, 38, 21, true, C.ink, "center"),
  textbox("설명 먼저\n복사 가능한 bash 명령\n인라인 CLI 0개", 768, 334, 250, 112, 21, false, C.gray, "center"),
  rect(1066, 170, 2, 360, C.rule, "divider-3"),
  textbox("#381", 1090, 196, 120, 74, 40, true, C.green, "center"),
  textbox("코드 블록 5개", 1078, 286, 144, 56, 19, true, C.ink, "center"),
  textbox("225", 1090, 382, 120, 62, 38, true, C.blue, "center"),
  textbox("전체 시험 통과", 1078, 458, 144, 44, 17, false, C.gray, "center"),
], ["docs/reports/issue-69-community-auto-publish-kb-validation.md#3.5", "https://community.ablecloud.io/d/167/381"]);

addSlide([
  rect(0, 0, 1280, 720, C.ink, "closing"),
  textbox("완료", 64, 70, 260, 56, 28, true, C.cyan),
  textbox("사용자는 바로 답을 받고,\n검증된 KB가 최종 솔루션이 됩니다", 64, 162, 1100, 158, 54, true, C.white),
  rect(68, 396, 2, 186, C.cyan, "left-rule"),
  textbox("AI Gateway 0.14.4 · OpenAI · 다중 참여자 후속 응답", 96, 396, 1030, 44, 24, true, C.white),
  textbox("Process · Database · Vector ready", 96, 456, 1030, 40, 21, false, "#CBD5E1"),
  textbox("전체 DB 백업 · 루트 여유 921 GB · 보호 서비스 무변경", 96, 510, 1030, 40, 21, false, "#CBD5E1"),
  textbox("PR #65는 구현 검토를 위해 Draft 상태를 유지합니다", 684, 642, 530, 28, 17, false, "#94A3B8", "right"),
], ["docs/reports/issue-69-community-auto-publish-kb-validation.md#6", "docs/reports/issue-69-community-auto-publish-kb-validation.md#7"]);

async function saveBlob(target, blob) { await fs.writeFile(target, new Uint8Array(await blob.arrayBuffer())); }
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
const inspection = await deck.inspect({ kind: "slide,textbox,shape,notes", maxChars: 100000 });
await fs.writeFile(path.join(QA_DIR, "inspect.ndjson"), inspection.ndjson, "utf8");
const pptx = await PresentationFile.exportPptx(deck);
await pptx.save(PPTX);
console.log(JSON.stringify({ pptx: PPTX, slides: deck.slides.items.length, qa: QA_DIR }));
