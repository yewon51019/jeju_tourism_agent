const { test } = require("node:test");
const assert = require("node:assert/strict");
const A = require("../demo/analysis.js");
const f = { region: "서귀포시", age: "30대", sector: "음식점", year: 2025 };
test("누락 조건은 추정하지 않고 반환", () => {
  assert.deepEqual(A.parseQuestion("서귀포시 프로모션").missing, [
    "연령",
    "연도",
  ]);
});
test("요일 및 특정 월 분석을 조용히 연간 분석으로 바꾸지 않음", () => {
  assert.equal(A.parseQuestion("2025년 서귀포시 30대 주말").unsupported, true);
  assert.equal(A.parseQuestion("2025년 3월 서귀포시 30대").unsupported, true);
});
test("수작업 계산 fixture: 필터·합계·순위·전년 비교", () => {
  const rows = [];
  for (const year of [2024, 2025])
    for (let month = 1; month <= 12; month++)
      rows.push({
        ...f,
        year,
        month,
        amount: year === 2025 ? month * 20 : month * 10,
      });
  rows.push({ ...f, region: "제주시", month: 1, amount: 999999 });
  const r = A.analyze(rows, f);
  assert.equal(r.total, 1560);
  assert.equal(r.yoy, 100);
  assert.equal(r.ranking[0].month, 12);
  assert.equal(r.rows, 12);
});
test("전년도 없으면 0% 대신 비교 불가", () => {
  assert.equal(A.analyze(A.makeData(), { ...f, year: 2024 }).yoy, null);
});
test("누락 월은 0이 아니라 null, 연간 비교 차단", () => {
  const r = A.analyze(
    A.makeData().filter((r) => !(r.year === 2025 && r.month === 8)),
    f,
  );
  assert.equal(r.monthly[7].amount, null);
  assert.equal(r.full, false);
  assert.equal(r.yoy, null);
});
test("중복 행과 비정상 금액 차단", () => {
  const rows = A.makeData();
  const row = rows.find(
    (r) =>
      r.year === 2025 &&
      r.region === f.region &&
      r.age === f.age &&
      r.sector === f.sector,
  );
  assert.throws(() => A.analyze([...rows, row], f), /중복/);
  assert.throws(
    () =>
      A.analyze(
        rows.map((r) => (r === row ? { ...r, amount: -1 } : r)),
        f,
      ),
    /검증/,
  );
});
