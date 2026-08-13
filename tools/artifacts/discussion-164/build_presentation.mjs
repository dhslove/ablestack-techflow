import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile, layers, shape, text } from "@oai/artifact-tool";

const ROOT = path.resolve(process.argv[2] ?? process.cwd());
const OUT_DIR = path.join(ROOT, "output", "presentation");
const QA_DIR = path.join(ROOT, "tmp", "artifacts", "discussion-164", "qa");
const PPTX = path.join(OUT_DIR, "techflow-community-discussion-164-recovery.pptx");
const FONT = "Malgun Gothic";
const C = { ink: "#0F172A", blue: "#2563EB", accent: "#6DCBF4", pale: "#EDEDED", rule: "#B8BCC4", green: "#15803D", amber: "#B45309", red: "#B91C1C", white: "#FFFFFF", gray: "#475569" };

function para(value, size = 20, bold = false, color = C.ink, align = "left") {
  return { runs: [{ run: value, textStyle: { fontSize: `${size}px`, typeface: FONT, bold, color } }], paragraphStyle: { lineSpacingPercent: 108000, alignment: align } };
}

function textbox(value, x, y, w, h, size = 20, bold = false, color = C.ink, align = "left", name = "text") {
  return text([para(value, size, bold, color, align)], { name, position: { left: x, top: y }, width: w, height: h, style: { fontSize: `${size}px`, typeface: FONT, color, alignment: align, verticalAlignment: "middle", autoFit: "shrinkText", insets: { top: 4, right: 8, bottom: 4, left: 8 } } });
}

function rect(x, y, w, h, fill, name, line = "none") {
  return shape({ name, geometry: "rect", fill, line: line === "none" ? { fill: "none" } : { fill: line, width: 1 }, position: { left: x, top: y }, width: w, height: h });
}

function connector(x, y, w) {
  return shape({ name: `arrow-${x}`, geometry: "straightConnector1", fill: "none", line: { fill: C.blue, width: 3, endArrowType: "triangle" }, position: { left: x, top: y }, width: w, height: 1 });
}

function header(title, number) {
  return [textbox(title, 54, 34, 1110, 82, 36, true, C.ink, "left", "title"), rect(54, 126, 1172, 2, C.rule, "rule"), textbox(String(number).padStart(2, "0"), 1170, 650, 56, 24, 16, false, C.gray, "right", "page")];
}

function note(slide, sources) {
  slide.speakerNotes.textFrame.setText(`[Sources]\n${sources.map((s) => `- ${s}`).join("\n")}`);
}

function addSlide(items, sources) {
  const slide = deck.slides.add();
  slide.compose(layers({ name: "discussion-164", width: "fill", height: "fill" }, [rect(0, 0, 1280, 720, C.white, "background"), ...items]), { frame: { left: 0, top: 0, width: 1280, height: 720 }, baseUnit: 1 });
  note(slide, sources);
  return slide;
}

const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });

addSlide([
  rect(0, 0, 1280, 720, C.ink, "cover"),
  textbox("ABLESTACK TECHFLOW", 60, 64, 620, 44, 24, true, C.accent),
  textbox("Discussion #164\n후속 답변 장애 복구", 60, 164, 1100, 182, 62, true, C.white),
  textbox("로그 ZIP 수집부터 검토용 답변 생성까지 복구 완료", 66, 398, 980, 52, 28, false, "#CBD5E1"),
  rect(66, 518, 420, 74, C.blue, "result"),
  textbox("Post #362 승인 대기", 82, 530, 388, 50, 25, true, C.white, "center"),
  textbox("2026-08-13 · AI Gateway 0.13.2", 824, 642, 390, 28, 17, false, "#94A3B8", "right"),
], ["docs/reports/discussion-164-community-followup-recovery.md"]);

const cause = [...header("한 개의 macOS 메타데이터가 전체 후속 처리 경로를 막았습니다", 2)];
const xs = [54, 352, 650, 948];
const titles = ["정상 ZIP 다운로드", "AppleDouble 거부", "상태 저장 중단", "답변 미생성"];
const bodies = ["Post #358\nTXT 로그 2개", "__MACOSX/._*\n바이너리 메타데이터", "HTTP 400 반복\n같은 구간 재처리", "검토 Post 없음\n뒤 이벤트도 지연"];
for (let i = 0; i < xs.length; i++) {
  if (i < xs.length - 1) cause.push(connector(xs[i] + 230, 348, 56));
  cause.push(rect(xs[i], 224, 238, 250, i === 1 ? "#FEE2E2" : C.pale, `cause-${i}`, C.rule));
  cause.push(textbox(titles[i], xs[i] + 16, 246, 206, 58, 24, true, i === 1 ? C.red : C.blue, "center"));
  cause.push(textbox(bodies[i], xs[i] + 16, 326, 206, 112, 19, false, C.ink, "center"));
}
cause.push(textbox("실제 로그가 아니라 Finder 메타데이터를 로그로 처리한 것이 근본 원인입니다", 166, 528, 948, 54, 26, true, C.red, "center"));
addSlide(cause, ["services/ai-gateway/app/log_artifacts.py", "services/ai-gateway/scripts/poll_flarum.py"]);

addSlide([
  ...header("파서, 재시도, 체크포인트, 실행 시간을 함께 보완했습니다", 3),
  textbox("입력 경계", 70, 178, 320, 42, 26, true, C.blue),
  textbox("macOS 메타데이터만 제외\n실제 로그 보안 검사는 유지\n영구 오류는 안전 안내로 전환", 70, 232, 330, 178, 19, false, C.ink),
  rect(426, 166, 2, 344, C.rule, "divider-1"),
  textbox("처리 경계", 474, 178, 320, 42, 26, true, C.green),
  textbox("성공 Post 즉시 체크포인트\n임시 파일 후 원자적 교체\n실패 Discussion과 나머지 큐 격리", 474, 232, 330, 178, 19, false, C.ink),
  rect(830, 166, 2, 344, C.rule, "divider-2"),
  textbox("실행 경계", 878, 178, 320, 42, 26, true, C.amber),
  textbox("Community Draft만 300초\n네트워크 장애는 재시도\n공개는 관리자 승인 유지", 878, 232, 330, 178, 19, false, C.ink),
  rect(70, 520, 1138, 74, "#E0F2FE", "version"),
  textbox("AI Gateway 0.13.2 · Activepieces Flow 3개 ENABLED", 94, 532, 1090, 50, 25, true, C.blue, "center"),
], ["services/ai-gateway/app/log_artifacts.py", "services/ai-gateway/scripts/poll_flarum.py", "deploy/compose/activepieces/flows/community-assist-v1.json"]);

addSlide([
  ...header("Discussion #164는 검토 가능한 정상 승인 대기 상태로 복구됐습니다", 4),
  textbox("1", 72, 188, 260, 104, 68, true, C.blue, "center"),
  textbox("Artifact 등록", 72, 300, 260, 44, 22, true, C.ink, "center"),
  textbox("#362", 510, 188, 260, 104, 58, true, C.green, "center"),
  textbox("검토용 답변 Post", 510, 300, 260, 44, 22, true, C.ink, "center"),
  textbox("0", 948, 188, 260, 104, 68, true, C.amber, "center"),
  textbox("Poller failed", 948, 300, 260, 44, 22, true, C.ink, "center"),
  rect(72, 402, 1136, 2, C.rule, "metrics-rule"),
  textbox("DRAFT_PENDING / WAITING_REVIEW", 96, 438, 1088, 62, 31, true, C.blue, "center"),
  textbox("Chat 담당자 1명에게 첫 시도에 원문 검토 링크 전송", 96, 516, 1088, 44, 22, false, C.ink, "center"),
], ["docs/reports/discussion-164-community-followup-recovery.md#4", "https://community.ablecloud.io/d/164-gasangmeosin-sijag-mic-maigeureisyeon-oryu"]);

addSlide([
  rect(0, 0, 1280, 720, C.ink, "closing"),
  textbox("복구 완료", 64, 72, 450, 62, 28, true, C.accent),
  textbox("이제 담당자가 답변 원문을\n검토하고 승인하면 됩니다", 64, 170, 1090, 158, 56, true, C.white),
  rect(68, 412, 2, 170, C.accent, "left-rule"),
  textbox("Chat 알림의 Community 링크 열기", 96, 410, 1000, 46, 25, true, C.white),
  textbox("Post #362의 질문·로그 분석·해결 절차 확인", 96, 466, 1000, 46, 21, false, "#CBD5E1"),
  textbox("승인 · 수정 승인 · 반려 중 선택", 96, 522, 1000, 46, 21, false, "#CBD5E1"),
  textbox("GitHub→Chat 보호 서비스는 변경하지 않았습니다", 688, 642, 526, 28, 17, false, "#94A3B8", "right"),
], ["docs/runbooks/community-conversation.md#7", "docs/reports/discussion-164-community-followup-recovery.md#7"]);

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
const inspection = await deck.inspect({ kind: "slide,textbox,shape,notes", maxChars: 100000 });
await fs.writeFile(path.join(QA_DIR, "inspect.ndjson"), inspection.ndjson, "utf8");
const pptx = await PresentationFile.exportPptx(deck);
await pptx.save(PPTX);
console.log(JSON.stringify({ pptx: PPTX, slides: deck.slides.items.length, qa: QA_DIR }));
