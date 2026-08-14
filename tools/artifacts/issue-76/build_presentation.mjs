import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile, layers, shape, text } from "@oai/artifact-tool";

const ROOT = path.resolve(process.argv[2] ?? process.cwd());
const OUT = path.join(ROOT, "output", "presentation");
const QA = path.join(ROOT, "tmp", "artifacts", "issue-76", "qa");
const PPTX = path.join(OUT, "techflow-guest-os-official-platform-evidence.pptx");
const FONT = "Malgun Gothic";
const C = { ink: "#0F172A", blue: "#2563EB", cyan: "#38BDF8", green: "#15803D", amber: "#B45309", white: "#FFFFFF", pale: "#F1F5F9", rule: "#CBD5E1", gray: "#475569", red: "#B91C1C" };

function para(value, size = 20, bold = false, color = C.ink, align = "left") { return { runs: [{ run: value, textStyle: { fontSize: `${size}px`, typeface: FONT, bold, color } }], paragraphStyle: { lineSpacingPercent: 108000, alignment: align } }; }
function textbox(value, x, y, w, h, size = 20, bold = false, color = C.ink, align = "left", name = "text") { return text([para(value, size, bold, color, align)], { name, position: { left: x, top: y }, width: w, height: h, style: { fontSize: `${size}px`, typeface: FONT, color, alignment: align, verticalAlignment: "middle", autoFit: "shrinkText", insets: { top: 4, right: 8, bottom: 4, left: 8 } } }); }
function rect(x, y, w, h, fill, name, line = "none") { return shape({ name, geometry: "rect", fill, line: line === "none" ? { fill: "none" } : { fill: line, width: 1 }, position: { left: x, top: y }, width: w, height: h }); }
function arrow(x, y, w) { return shape({ name: `arrow-${x}-${y}`, geometry: "straightConnector1", fill: "none", line: { fill: C.blue, width: 3, endArrowType: "triangle" }, position: { left: x, top: y }, width: w, height: 1 }); }
function header(title, number) { return [textbox(title, 54, 34, 1110, 82, 36, true), rect(54, 126, 1172, 2, C.rule, "rule"), textbox(String(number).padStart(2, "0"), 1170, 650, 56, 24, 16, false, C.gray, "right", "page")]; }
function addSlide(items, sources) { const slide = deck.slides.add(); slide.compose(layers({ name: "issue-76", width: "fill", height: "fill" }, [rect(0, 0, 1280, 720, C.white, "background"), ...items]), { frame: { left: 0, top: 0, width: 1280, height: 720 }, baseUnit: 1 }); slide.speakerNotes.textFrame.setText(`[Sources]\n${sources.map((s) => `- ${s}`).join("\n")}`); return slide; }

const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });

addSlide([
  rect(0, 0, 1280, 720, C.ink, "cover"), textbox("ABLESTACK TECHFLOW", 64, 62, 640, 42, 24, true, C.cyan),
  textbox("게스트 OS와 공식 플랫폼 근거 보강", 64, 160, 1100, 90, 56, true, C.white),
  textbox("로컬 우선 · 공식 도메인 제한 · 쉬운 해결 명령", 70, 302, 1040, 52, 28, false, "#CBD5E1"),
  rect(70, 454, 440, 78, C.blue, "release"), textbox("AI Gateway 0.14.7", 88, 466, 404, 52, 26, true, C.white, "center"),
  textbox("Issue #76 · 2026-08-14", 824, 642, 390, 28, 17, false, "#94A3B8", "right"),
], ["docs/reports/issue-76-guest-os-official-platform-evidence-validation.md"]);

addSlide([
  ...header("#168의 문제는 권한이 아니라 지식 공백이었습니다", 2),
  rect(64, 180, 330, 330, "#FEE2E2", "failure", C.rule), textbox("기존 답변", 88, 202, 282, 44, 27, true, C.red, "center"),
  textbox("서비스가 없음\n설치 명령도 없음\n시스템 관리자에게 요청", 88, 276, 282, 156, 23, false, C.ink, "center"),
  arrow(424, 340, 98),
  rect(552, 180, 330, 330, "#E0F2FE", "fix", C.rule), textbox("보강", 576, 202, 282, 44, 27, true, C.blue, "center"),
  textbox("Ubuntu · Rocky · Windows\n공식 설치 절차\n복사 가능한 CLI", 576, 276, 282, 156, 21, false, C.ink, "center"),
  arrow(912, 340, 98),
  rect(1040, 180, 176, 330, "#DCFCE7", "outcome", C.rule), textbox("결과", 1054, 202, 148, 44, 27, true, C.green, "center"),
  textbox("사용자가\nVM 안에서\n직접 해결", 1054, 286, 148, 132, 23, true, C.ink, "center"),
  textbox("해결책 → 정상 기준 → 실패 시 다음 진단", 140, 550, 1000, 50, 25, true, C.blue, "center"),
], ["https://community.ablecloud.io/d/168", "https://packages.ubuntu.com/noble/qemu-guest-agent", "https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/configuring_and_managing_virtualization/"]);

const flow = [...header("공식 웹은 로컬 분석의 대체가 아니라 마지막 보완 단계입니다", 3)];
const xs = [58, 304, 550, 796, 1042];
const labels = ["질문", "ABLESTACK\n문서·코드", "로컬 공식\n스냅샷", "공식 도메인\n제한 검색", "쉬운 답변\n내부 감사"];
for (let i = 0; i < xs.length; i++) { if (i < xs.length - 1) flow.push(arrow(xs[i] + 178, 330, 54)); flow.push(rect(xs[i], 214, 178, 230, i === 4 ? "#DCFCE7" : C.pale, `step-${i}`, C.rule)); flow.push(textbox(String(i + 1), xs[i] + 57, 232, 64, 52, 34, true, i === 4 ? C.green : C.blue, "center")); flow.push(textbox(labels[i], xs[i] + 12, 306, 154, 98, 21, true, C.ink, "center")); }
flow.push(textbox("URL · 이메일 · IP · 비밀정보 제거 | 실제 Tool Source URL 재검증 | 공개 URL 비노출", 108, 520, 1064, 62, 23, true, C.blue, "center"));
addSlide(flow, ["docs/plans/issue-76-guest-os-official-platform-evidence-design.md", "https://developers.openai.com/api/docs/guides/tools-web-search"]);

addSlide([
  ...header("제품 이름은 유지하고 공식 기반 기술만 내부에서 확장합니다", 4),
  textbox("Mold", 74, 190, 180, 58, 32, true, C.blue, "center"), textbox("CloudStack + libvirt/QEMU", 270, 190, 390, 58, 23, false, C.gray),
  textbox("Glue", 74, 282, 180, 58, 32, true, C.blue, "center"), textbox("Ceph 공식 문서", 270, 282, 390, 58, 23, false, C.gray),
  textbox("Koral", 74, 374, 180, 58, 32, true, C.blue, "center"), textbox("Kubernetes 공식 문서", 270, 374, 390, 58, 23, false, C.gray),
  textbox("Wall", 74, 466, 180, 58, 32, true, C.blue, "center"), textbox("Grafana 공식 문서", 270, 466, 390, 58, 23, false, C.gray),
  rect(718, 182, 2, 360, C.rule, "divider"), textbox("공개 답변", 780, 194, 380, 54, 30, true, C.green, "center"),
  textbox("Mold · Glue · Koral · Wall\n\n기반 기술 이름은 명령·설정 키·API에\n꼭 필요할 때만 사용", 770, 286, 410, 188, 24, false, C.ink, "center"),
], ["https://docs.cloudstack.apache.org/en/4.22.1.0/", "https://docs.ceph.com/en/latest/", "https://kubernetes.io/docs/tasks/debug/", "https://grafana.com/docs/grafana/latest/troubleshooting/"]);

addSlide([
  rect(0, 0, 1280, 720, C.ink, "closing"), textbox("검증 목표", 64, 70, 300, 56, 28, true, C.cyan),
  textbox("정확한 해결책을 먼저 주고,\n부족한 근거만 공식 자료로 채웁니다", 64, 162, 1100, 158, 54, true, C.white),
  rect(68, 396, 2, 186, C.cyan, "left-rule"),
  textbox("15개 Versioned Golden Case · 공식 도메인 Allowlist · Source URL 대조", 96, 396, 1060, 44, 23, true, C.white),
  textbox("OpenAI 실호출 · Discussion #168 E2E · 보호 서비스 무변경", 96, 466, 1060, 40, 22, false, "#CBD5E1"),
  textbox("상세 수치는 배포 검증 보고서와 Manifest에서 추적", 96, 526, 1060, 40, 20, false, "#CBD5E1"),
], ["docs/reports/issue-76-guest-os-official-platform-evidence-validation.md"]);

async function saveBlob(target, blob) { await fs.writeFile(target, new Uint8Array(await blob.arrayBuffer())); }
await fs.mkdir(OUT, { recursive: true }); await fs.mkdir(path.join(QA, "renders"), { recursive: true }); await fs.mkdir(path.join(QA, "layouts"), { recursive: true });
for (const [index, slide] of deck.slides.items.entries()) { const stem = `slide-${String(index + 1).padStart(2, "0")}`; await saveBlob(path.join(QA, "renders", `${stem}.png`), await deck.export({ slide, format: "png", scale: 2 })); const layout = await slide.export({ format: "layout" }); await fs.writeFile(path.join(QA, "layouts", `${stem}.json`), await layout.text(), "utf8"); }
await saveBlob(path.join(QA, "montage.webp"), await deck.export({ format: "webp", montage: true, scale: 1 }));
const inspection = await deck.inspect({ kind: "slide,textbox,shape,notes", maxChars: 100000 }); await fs.writeFile(path.join(QA, "inspect.ndjson"), inspection.ndjson, "utf8");
const pptx = await PresentationFile.exportPptx(deck); await pptx.save(PPTX); console.log(JSON.stringify({ pptx: PPTX, slides: deck.slides.items.length, qa: QA }));
