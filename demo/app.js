"use strict";

// 화면과 사용자 이벤트를 담당합니다. 수치 계산은 analysis.js에서 수행합니다.
const getElement = (id) => document.getElementById(id),
  analysis = JejuAnalysis,
  demoRows = analysis.makeData();
let currentResult = null,
  reportMarkdown = "",
  questionInterpretationLog = "구조화 조건 직접 선택";
const formatMoney = (n) => new Intl.NumberFormat("ko-KR").format(n);
// 조건 변경 시 오래된 결과를 숨겨, 다른 조건의 결과와 혼동하지 않게 합니다.
function clearPreviousResult() {
  currentResult = null;
  getElement("results").hidden = true;
  getElement("pipeline-status").textContent = "조건 확인 대기";
}
// 지원 키워드를 해석하고, 누락된 조건을 사용자에게 확인합니다.
function interpretQuestion() {
  clearPreviousResult();
  const parsedQuestion = analysis.parseQuestion(getElement("question").value);
  for (const filterName of ["region", "age", "sector", "year"]) getElement(filterName).value = parsedQuestion[filterName] ?? "";
  const message = parsedQuestion.unsupported
    ? "이 질문에는 지원하지 않는 기간 또는 요일 조건이 있습니다. 원래 질문은 분석하지 않았습니다. 아래 조건을 확인한 뒤 연간 월별 분석을 별도로 실행할 수 있습니다."
    : parsedQuestion.missing.length
      ? `${parsedQuestion.missing.join(", ")} 조건이 빠져 있습니다. 아래에서 선택해 주세요. 임의로 조건을 확대하지 않습니다.`
      : "지역·연령·연도 조건을 해석했습니다. 업종을 지정하지 않으면 전체 업종을 사용합니다. 조건을 확인하고 실행하세요.";
  getElement("question-status").textContent = message;
  questionInterpretationLog = message;
}
getElement("interpret").addEventListener("click", interpretQuestion);
getElement("question").addEventListener("input", () => {
  clearPreviousResult();
  for (const filterName of ["region", "age", "year"]) getElement(filterName).value = "";
  getElement("question-status").textContent =
    "질문이 변경되었습니다. 다시 해석하거나 분석 조건을 직접 선택하세요.";
  questionInterpretationLog = "변경된 질문 대신 사용자가 선택한 구조화 조건을 사용";
});
document.querySelectorAll("[data-question]").forEach((button) =>
  button.addEventListener("click", () => {
    getElement("question").value = button.dataset.question;
    interpretQuestion();
  }),
);
for (const filterName of ["region", "age", "sector", "year"])
  getElement(filterName).addEventListener("change", clearPreviousResult);
// 사용자가 확인한 조건으로만 계산을 실행합니다.
// 차트와 표는 같은 월별 계산 결과를 사용합니다.
function renderMonthlyChart(result, peakMonth) {
    getElement("chart").replaceChildren();
    getElement("numbers").replaceChildren();
    for (const monthlyValue of result.monthly) {
      const bar = document.createElement("div");
      bar.className = "bar" + (monthlyValue.month === peakMonth.month ? " peak" : "");
      bar.style.height = `${peakMonth.amount > 0 ? ((monthlyValue.amount ?? 0) / peakMonth.amount) * 100 : 0}%`;
      bar.title = `${monthlyValue.month}월: ${monthlyValue.amount === null ? "자료 없음" : formatMoney(monthlyValue.amount) + "원 (가상)"}`;
      bar.setAttribute("aria-label", bar.title);
      const label = document.createElement("span");
      label.textContent = monthlyValue.month + "월";
      bar.append(label);
      getElement("chart").append(bar);
      const tableRow = document.createElement("tr");
      for (const cellValue of [
        monthlyValue.month + "월",
        monthlyValue.amount === null ? "자료 없음" : formatMoney(monthlyValue.amount),
      ]) {
        const tableCell = document.createElement("td");
        tableCell.textContent = cellValue;
        tableRow.append(tableCell);
      }
      getElement("numbers").append(tableRow);
    }

}

function runAnalysis() {
  clearPreviousResult();
  const filters = Object.fromEntries(
    ["region", "age", "sector", "year"].map((filterName) => [filterName, getElement(filterName).value]),
  );
  if (!filters.region || !filters.age || !filters.year) {
    getElement("question-status").textContent = "지역·연령·연도를 모두 선택해 주세요.";
    return;
  }
  try {
    currentResult = analysis.analyze(demoRows, filters);
    const result = currentResult,
      peakMonth = result.ranking[0],
      secondMonth = result.ranking[1];
    getElement("result-title").textContent =
      `${filters.region} · ${filters.age} 소비 인사이트`;
    const condition = `분석 기준: ${filters.year}년 1–12월 / ${filters.region} / ${filters.age} / ${filters.sector} 업종 / 가상 월별 데이터`;
    getElement("result-conditions").textContent = condition;
    getElement("total").textContent = `${(result.total / 100000000).toFixed(2)}억 원`;
    getElement("peak").textContent = `${peakMonth.month}월`;
    getElement("yoy").textContent =
      result.yoy === null
        ? "비교 불가"
        : `${result.yoy >= 0 ? "+" : ""}${result.yoy.toFixed(1)}%`;
    renderMonthlyChart(result, peakMonth);
    const insight = result.full
      ? `가상 데이터에서 ${peakMonth.month}월 이용금액이 ${formatMoney(peakMonth.amount)}원으로 가장 높고, ${secondMonth.month}월이 뒤를 잇습니다. 기능 시연용 실행 가설로는 ${peakMonth.month}월을 수요 대응형 프로모션 검토 시기로 정할 수 있습니다. 실제 시행 여부는 실데이터, 광고비, 마진, 재고 및 행사 일정을 함께 검토해야 합니다.`
      : "자료가 불완전해 시기 제안을 보류합니다.";
    getElement("insight").textContent = insight;
    getElement("warnings").replaceChildren();
    result.warnings.forEach((warning) => {
      const li = document.createElement("li");
      li.textContent = warning;
      getElement("warnings").append(li);
    });
    const logs = [
      `질문 해석: ${questionInterpretationLog}`,
      `조건 확정: ${condition}`,
      `데이터 선택: 합성 월별 소비 데이터 ${result.rows}행. 요일별 데이터와 결합하지 않음.`,
      `도구 실행: 월별 합계와 금액 순위 계산. 전년 비교는 동일 조건의 12개월 자료가 있을 때만 수행.`,
      `검증: 중복 키·음수·비정상 금액 검사, 원본 합계 ${formatMoney(result.total)}원 = 월별 합계. ${result.full ? "12개월 세부 조건 완전성 확인." : "누락 발견."}`,
      `출력: 고정 템플릿 보고서 생성. LLM 호출 없음. 실제 관광객 수·프로모션 효과는 추정하지 않음.`,
    ];
    getElement("logs").replaceChildren();
    logs.forEach((logLine) => {
      const li = document.createElement("li");
      li.textContent = logLine;
      getElement("logs").append(li);
    });
    reportMarkdown = [
      "# 제주 관광 소비 인사이트 — 가상 데이터 데모",
      "",
      condition,
      "",
      "주의: 실제 제주 통계가 아닙니다.",
      "",
      insight,
      "",
      `총액: ${formatMoney(result.total)}원`,
      `전년 대비: ${result.yoy === null ? "비교 불가" : result.yoy.toFixed(1) + "%"}`,
      "",
      "## 월별 금액",
      ...result.monthly.map(
        (monthlyValue) =>
          `- ${monthlyValue.month}월: ${monthlyValue.amount === null ? "자료 없음" : formatMoney(monthlyValue.amount) + "원"}`,
      ),
      "",
      "## 판단 로그",
      ...logs.map((logLine) => "- " + logLine),
      "",
      "## 한계",
      ...result.warnings.map((logLine) => "- " + logLine),
    ].join("\n");
    getElement("results").hidden = false;
    getElement("pipeline-status").textContent = "선택 조건 분석·검증 완료";
    getElement("question-status").textContent =
      "선택한 조건으로 분석을 완료했습니다. 아래 결과는 가상 데이터 기준입니다.";
  } catch (error) {
    getElement("question-status").textContent = error.message;
  }
}
getElement("analyze").addEventListener("click", runAnalysis);

// 파일은 브라우저 안에서 생성하며 외부 서버로 전송하지 않습니다.
getElement("download").addEventListener("click", () => {
  if (!currentResult) return;
  const url = URL.createObjectURL(
    new Blob(["\ufeff" + reportMarkdown], { type: "text/markdown;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "제주소비_가상데이터_분석보고서.md";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
interpretQuestion();
