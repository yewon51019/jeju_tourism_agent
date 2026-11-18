(function (root) {
  "use strict";
  const regions = ["제주시", "서귀포시"],
    ages = ["20대", "30대", "40대", "50대", "60대"],
    sectors = ["음식점", "숙박", "쇼핑"];
  function makeData() {
    const rows = [];
    for (const year of [2024, 2025])
      for (let month = 1; month <= 12; month++)
        for (const region of regions)
          for (const age of ages)
            for (const sector of sectors) {
              const seasonal = [
                0.8, 0.82, 1.02, 1.13, 1.18, 1.12, 1.34, 1.45, 1.16, 1.25, 0.91,
                0.88,
              ][month - 1];
              const amount = Math.round(
                10000000 *
                  seasonal *
                  (region === "서귀포시" ? 1.12 : 1) *
                  (1 + ages.indexOf(age) * 0.08) *
                  (1 + sectors.indexOf(sector) * 0.3) *
                  (year === 2025 ? 1.09 : 1),
              );
              rows.push({ year, month, region, age, sector, amount });
            }
    return rows;
  }
  function parseQuestion(question) {
    const region =
      regions.find((x) => question.includes(x)) ||
      (question.includes("서귀포")
        ? "서귀포시"
        : question.includes("제주시")
          ? "제주시"
          : null);
    const age =
      ages.find((x) => question.includes(x)) ||
      (question.includes("전체 연령") ? "전체" : null);
    const sector =
      sectors.find((x) => question.includes(x)) ||
      (question.includes("식당")
        ? "음식점"
        : question.includes("호텔")
          ? "숙박"
          : null);
    const year = Number((question.match(/(20\d{2})년/) || [])[1]) || null;
    const missing = [];
    if (!region) missing.push("지역");
    if (!age) missing.push("연령");
    if (!year) missing.push("연도");
    // Unsupported time resolution must never silently become a full-year answer.
    const unsupported =
      /요일|월요일|화요일|수요일|목요일|금요일|토요일|일요일|주말|평일|시간대|분기|상반기|하반기|\d{1,2}월/.test(
        question,
      );
    return {
      region,
      age,
      sector: sector || "전체",
      year,
      missing,
      unsupported,
    };
  }
  function analyze(rows, filters) {
    if (
      !regions.includes(filters.region) ||
      !["전체", ...ages].includes(filters.age) ||
      !["전체", ...sectors].includes(filters.sector) ||
      ![2024, 2025].includes(Number(filters.year))
    )
      throw Error("지원하지 않는 분석 조건입니다.");
    const match = (r) =>
      r.region === filters.region &&
      (filters.age === "전체" || r.age === filters.age) &&
      (filters.sector === "전체" || r.sector === filters.sector);
    const selected = rows.filter(
      (r) => match(r) && r.year === Number(filters.year),
    );
    if (!selected.length)
      throw Error(
        "해당 조건의 데이터가 없습니다. 조건을 자동으로 확대하지 않습니다.",
      );
    if (
      selected.some(
        (r) =>
          !Number.isFinite(r.amount) ||
          r.amount < 0 ||
          !Number.isInteger(r.month) ||
          r.month < 1 ||
          r.month > 12,
      )
    )
      throw Error("금액 또는 월 데이터 검증에 실패했습니다.");
    const keys = selected.map((r) =>
      [r.year, r.month, r.region, r.age, r.sector].join("|"),
    );
    if (new Set(keys).size !== keys.length)
      throw Error("중복 집계 행이 있습니다. 분석을 중단합니다.");
    const monthly = Array.from({ length: 12 }, (_, i) => ({
      month: i + 1,
      amount: null,
    }));
    for (const row of selected) {
      const m = monthly[row.month - 1];
      m.amount = (m.amount ?? 0) + row.amount;
    }
    const total = selected.reduce((sum, r) => sum + r.amount, 0),
      groupedTotal = monthly.reduce((sum, r) => sum + (r.amount ?? 0), 0);
    if (total !== groupedTotal)
      throw Error("원본과 월별 집계의 합계가 다릅니다.");
    const expectedPerMonth =
      (filters.age === "전체" ? ages.length : 1) *
      (filters.sector === "전체" ? sectors.length : 1);
    const full = monthly.every(
      (m) =>
        selected.filter((r) => r.month === m.month).length === expectedPerMonth,
    );
    const previous = rows.filter(
      (r) => match(r) && r.year === Number(filters.year) - 1,
    );
    const previousKeys = previous.map((r) =>
      [r.month, r.region, r.age, r.sector].join("|"),
    );
    const comparable =
      full &&
      previous.length === 12 * expectedPerMonth &&
      new Set(previousKeys).size === previous.length &&
      previous.every(
        (r) =>
          Number.isFinite(r.amount) &&
          r.amount >= 0 &&
          r.month >= 1 &&
          r.month <= 12,
      );
    const previousTotal = previous.reduce((sum, r) => sum + r.amount, 0);
    const yoy =
      comparable && previousTotal > 0
        ? (total / previousTotal - 1) * 100
        : null;
    const ranking = monthly
      .filter((m) => m.amount !== null)
      .slice()
      .sort((a, b) => b.amount - a.amount || a.month - b.month);
    return {
      filters,
      total,
      monthly,
      ranking,
      yoy,
      rows: selected.length,
      full,
      verified: total === groupedTotal,
      warnings: [
        ...(!full
          ? [
              "월별 세부 조건이 누락되어 연간 비교와 프로모션 시기 제안을 보류합니다.",
            ]
          : []),
        ...(yoy === null
          ? [
              "동일 조건의 전년도 전체 자료가 없어 전년 대비 증감률을 제공하지 않습니다.",
            ]
          : []),
        "가상 데이터 결과입니다. 실제 제주 소비 동향 또는 정책·영업 판단의 근거로 사용할 수 없습니다.",
        "카드 지출 규모는 프로모션의 인과적 효과나 수익성을 의미하지 않습니다.",
      ],
    };
  }
  const api = { makeData, parseQuestion, analyze, regions, ages, sectors };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JejuAnalysis = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
