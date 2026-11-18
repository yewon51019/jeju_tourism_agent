// 사용자 기획서의 목차와 표를 유지해 Markdown을 인쇄용 HTML로 변환합니다.
// 네트워크나 외부 라이브러리 없이 생성하며 모든 원문 HTML은 이스케이프합니다.
const fs = require("node:fs");
const path = require("node:path");
const sourcePath = path.join(__dirname, "../docs/proposal.md");
const outputPath = path.join(__dirname, "../docs/proposal.html");

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderSection(markdown, index, total) {
  const blocks = markdown.trim().split(/\r?\n\s*\r?\n/);
  const content = blocks
    .map((block) => {
      if (block.startsWith("# "))
        return `<h1>${escapeHtml(block.slice(2))}</h1>`;
      if (block.startsWith("## "))
        return `<h2>${escapeHtml(block.slice(3))}</h2>`;
      if (block.startsWith("### "))
        return `<h3>${escapeHtml(block.slice(4))}</h3>`;
      if (block.startsWith("| ")) {
        const rows = block.split(/\r?\n/).map((line) =>
          line.replace(/^\|\s*/, "").replace(/\s*\|$/, "").split("|").map((cell) => cell.trim()),
        );
        const header = rows[0].map((cell) => `<th scope="col">${escapeHtml(cell)}</th>`).join("");
        const body = rows.slice(2).map((row) =>
          `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`,
        ).join("");
        return `<table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
      }
      if (block.startsWith("- "))
        return (
          "<ul>" +
          block
            .split(/\r?\n/)
            .map((line) => `<li>${escapeHtml(line.slice(2))}</li>`)
            .join("") +
          "</ul>"
        );
      if (/^\d+\. /.test(block))
        return (
          "<ol>" +
          block
            .split(/\r?\n/)
            .map(
              (line) => `<li>${escapeHtml(line.replace(/^\d+\. /, ""))}</li>`,
            )
            .join("") +
          "</ol>"
        );
      return `<p>${escapeHtml(block)}</p>`;
    })
    .join("\n");
  return `<section class="page"><div class="topline">JEJU SIGNAL / PROPOSAL</div>${content}<footer>구현 반영본 · 합성 데모 / 실데이터 소량 확인<span>${index + 1} / ${total}</span></footer></section>`;
}

const markdown = fs.readFileSync(sourcePath, "utf8");
const sections = markdown.split(/\r?\n---\r?\n/);
const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>제주 관광 소비 인사이트 Agent — 기획서</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#e7eee8;color:#193d35;font-family:'Malgun Gothic','Segoe UI',sans-serif}.toolbar{padding:18px;text-align:center;background:#123f36;color:white;font-size:13px}.toolbar a{color:#d7edac}.toolbar button{margin-left:15px;padding:8px 16px;cursor:pointer}.page{width:210mm;min-height:297mm;margin:20px auto;padding:20mm 19mm;background:#fff;position:relative}.topline{font-size:10px;letter-spacing:2px;color:#47725b;border-bottom:2px solid #c9df9d;padding-bottom:13px}h1{font-size:27px;line-height:1.4;margin:27px 0 20px;letter-spacing:-1px}h2{font-size:18px;color:#22765a;margin-bottom:24px}p,li{font-size:13px;line-height:1.95;overflow-wrap:anywhere}p{margin:19px 0}ul,ol{padding-left:22px}li{margin:8px 0}footer{position:absolute;bottom:15mm;left:19mm;right:19mm;border-top:1px solid #dbe5d9;padding-top:10px;color:#718277;font-size:10px}footer span{float:right}@page{size:A4;margin:0}@media print{body{background:white}.toolbar{display:none}.page{margin:0;break-after:page;min-height:297mm}.page:last-child{break-after:auto}}@media screen and (max-width:820px){.page{width:96%;min-height:auto;padding:28px 24px 75px}footer{left:24px;right:24px;bottom:25px}}
</style></head><body><div class="toolbar">12섹션 기획서 초안 · 인쇄 시 A4 / 배율 100% / 머리글·바닥글 해제 · PDF 저장 후 실제 페이지 수 확인 <button onclick="window.print()">인쇄 / PDF 저장</button> <a href="../demo/index.html">데모 보기</a></div>${sections.map((section, index) => renderSection(section, index, sections.length)).join("\n")}</body></html>`;
const finalHtml = html
  .replace("12섹션 기획서 초안", `${sections.length}개 인쇄 섹션 · 사용자 기획서 목차 1~7장`)
  .replace("</style>", "table{width:100%;border-collapse:collapse;margin:14px 0;font-size:12px;line-height:1.55}th,td{border:1px solid #dbe5d9;padding:7px 9px;text-align:left;vertical-align:top}th{background:#f2f7ed}h1{font-size:24px;margin:20px 0 14px}h2{font-size:17px;margin:16px 0 10px}p,li{font-size:12px;line-height:1.65}p{margin:12px 0}li{margin:5px 0}tr{break-inside:avoid}</style>");
fs.writeFileSync(outputPath, finalHtml, "utf8");
console.log(`기획서 HTML 생성 완료: ${sections.length}개 섹션`);
