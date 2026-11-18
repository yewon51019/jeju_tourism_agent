// 문서 변경도 코드 변경처럼 검증합니다. 외부 서비스나 키 파일은 읽지 않습니다.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const proposal = fs.readFileSync(path.join(root, 'docs/proposal.md'), 'utf8');
const printable = fs.readFileSync(path.join(root, 'docs/proposal.html'), 'utf8');

test('제출용 기획서는 사용자 원안의 7개 본문 목차를 순서대로 유지한다', () => {
  const headings = [...proposal.matchAll(/^# ([1-7])\. (.+)$/gm)];
  assert.deepEqual(headings.map((match) => Number(match[1])), [1, 2, 3, 4, 5, 6, 7]);
  for (const heading of headings) {
    assert.ok(printable.includes(`<h1>${heading[1]}. ${heading[2]}</h1>`));
  }
});

test('기획서 HTML은 표지와 7장, 실제 표 구조를 포함한다', () => {
  assert.equal((printable.match(/<section class="page">/g) || []).length, 8);
  const markdownTables = proposal.split(/\r?\n\s*\r?\n/).filter((block) => block.startsWith('| '));
  assert.ok(markdownTables.length >= 7);
  assert.equal((printable.match(/<table>/g) || []).length, markdownTables.length);
  assert.equal(printable.includes('12섹션'), false);
});

test('기획서는 목표와 실측 및 실제 API 미완료 범위를 구분한다', () => {
  for (const expected of ['HTTP 200', 'HTTP 403', '5행', '335', '목표이며', '실제 Claude', '15페이지']) {
    assert.ok(proposal.includes(expected), `Missing disclosure: ${expected}`);
  }
});

test('README의 상대 파일 링크는 실제 파일을 가리킨다', () => {
  const readme = fs.readFileSync(path.join(root, 'README.md'), 'utf8');
  for (const match of readme.matchAll(/\]\(([^)]+)\)/g)) {
    const target = match[1];
    if (/^[a-z]+:/i.test(target) || target.startsWith('#')) continue;
    assert.ok(fs.existsSync(path.resolve(root, target.split('#')[0])), `Missing local link: ${target}`);
  }
});
