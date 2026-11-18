'use strict';

const PRESETS = [
  { label: '🍊 서귀포시 30대 관광객 식음료 프로모션 적기', query: '서귀포시에서 30대 관광객을 대상으로 식음료 프로모션을 하려면 언제가 좋을까?' },
  { label: '☕ 제주시 20대 여성 카페·디저트 소비 추세', query: '제주시 20대 여성 관광객의 카페·디저트 소비 추세는 어때?' },
  { label: '🏖 제주시 구도심 주말·평일 소비 패턴', query: '제주시 구도심의 요일별 소비 패턴을 주말과 평일로 비교해줘' },
  { label: '📈 최근 1년 소비 증가율 1위 테마', query: '최근 1년 제주 전 지역에서 전년 대비 소비 증가율이 가장 높은 테마는?' },
];
const AMBIGUOUS_QUERY = '요즘 제주도 장사 어디가 잘 돼?';
const CHIP_BASE = 'preset-chip text-left text-xs sm:text-[13px] px-3.5 py-2 rounded-xl border transition';
const CHIP_IDLE = 'border-[#E5E0D8] bg-cream-bg hover:bg-tangerine-light/50 hover:border-tangerine-border text-warmgray hover:text-charcoal';
const CHIP_ACTIVE = 'bg-tangerine-light border-tangerine text-charcoal font-semibold';
const OPTION_BASE = 'clarify-option px-3 py-1.5 rounded-lg text-xs border transition';
const OPTION_IDLE = 'font-medium border-[#E2DDD5] bg-white text-charcoal hover:border-tangerine';
const OPTION_ACTIVE = 'font-semibold border-tangerine bg-tangerine-light text-[#9A4A00]';

const $ = (id) => document.getElementById(id);
const state = { question: '', answers: {}, report: null, running: false, charts: {} };

// Firebase Hosting에는 Python 서버가 없어 미리 계산한 분석 결과를 재생한다.
const STATIC_DEMO = window.JEJU_STATIC_DEMO === true;
let demoData = null;

async function loadDemo() {
  if (!demoData) demoData = await (await fetch('/static/demo.json')).json();
  return demoData;
}

async function replayDemo(question, answers) {
  const demo = await loadDemo();
  const key = answers ? [question, answers.region, answers.theme, answers.age].join('||') : question;
  const events = demo.runs[key];
  if (!events) throw new Error('공개 데모에서는 예시 질문만 분석할 수 있습니다. 예시 질문을 선택해 주세요.');
  for (const event of events) {
    handleEvent(event);
    await new Promise((resolve) => { setTimeout(resolve, 180); });
  }
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

function richText(value) {
  return escapeHtml(value).replace(/\*\*(.+?)\*\*/g, '<strong class="text-[#B85500] font-bold">$1</strong>');
}

function showToast(message, kind = 'success') {
  const toast = document.createElement('div');
  const color = kind === 'success' ? 'bg-charcoal border-leaf' : 'bg-[#B85500] border-tangerine-hover';
  toast.className = `flex items-center gap-2 px-4 py-3 rounded-2xl shadow-lg border text-white text-xs sm:text-sm font-semibold animate-fade-in-up ${color}`;
  toast.textContent = message;
  $('toastContainer').appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

function renderPresets(activeQuery) {
  $('presetChips').innerHTML = PRESETS.map((p, i) =>
    `<button type="button" data-index="${i}" class="${CHIP_BASE} ${p.query === activeQuery ? CHIP_ACTIVE : CHIP_IDLE}">${escapeHtml(p.label)}</button>`).join('');
}

function setStep(number, status, detail) {
  const card = $(`stepCard-${number}`);
  const label = $(`stepStatus-${number}`);
  card.classList.remove('is-waiting', 'is-running', 'is-done', 'is-failed');
  card.classList.add({ waiting: 'is-waiting', running: 'is-running', done: 'is-done', failed: 'is-failed' }[status]);
  label.textContent = { waiting: '대기', running: '진행 중', done: '완료 ✓', failed: '중단' }[status];
  label.className = `text-xs font-bold ${status === 'done' ? 'text-leaf' : status === 'failed' ? 'text-red-700' : 'text-warmgray'}`;
  if (detail !== undefined) $(`stepDetail-${number}`).textContent = detail;
}

function setPipeline(status, text) {
  const badge = $('pipelineBadge');
  const icon = $('pipelineIcon');
  badge.textContent = text;
  const styles = {
    running: ['bg-tangerine-light text-[#9A4A00]', 'bg-tangerine-light text-tangerine'],
    done: ['bg-leaf-light text-leaf', 'bg-leaf-light text-leaf'],
    failed: ['bg-red-50 text-red-700', 'bg-red-50 text-red-700'],
    waiting: ['bg-leaf-light text-leaf', 'bg-leaf-light text-leaf'],
  }[status];
  badge.className = `text-xs font-semibold px-2.5 py-0.5 rounded-full ${styles[0]}`;
  icon.className = `w-7 h-7 rounded-lg flex items-center justify-center font-bold text-sm shrink-0 ${styles[1]}`;
  icon.innerHTML = status === 'running' ? '<span class="w-2.5 h-2.5 rounded-full bg-tangerine pulse-ring"></span>'
    : status === 'failed' ? '!' : status === 'waiting' ? '?' : '✓';
}

function resetPipeline() {
  $('pipelineSection').classList.remove('hidden');
  $('stepTags').innerHTML = '';
  for (let i = 1; i <= 4; i += 1) setStep(i, 'waiting', '');
  setPipeline('running', 'Agent 분석 중');
}

function closeClarification() {
  $('clarificationBox').classList.add('hidden');
}

function openClarification(event) {
  $('clarificationText').textContent = event.question;
  state.answers = {};
  $('clarificationFields').innerHTML = event.fields.map((field) => {
    state.answers[field.key] = field.options[0];
    const options = field.options.map((option, i) =>
      `<button type="button" data-key="${escapeHtml(field.key)}" data-value="${escapeHtml(option)}" aria-pressed="${i === 0}" class="${OPTION_BASE} ${i === 0 ? OPTION_ACTIVE : OPTION_IDLE}">${escapeHtml(option)}</button>`).join('');
    return `<div><span class="block text-xs font-bold text-warmgray mb-1.5">${escapeHtml(field.label)}</span><div class="flex flex-wrap gap-1.5">${options}</div></div>`;
  }).join('');
  $('clarificationBox').classList.remove('hidden');
  $('clarificationBox').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function renderLog(report) {
  const log = report.log;
  const tools = log.tools.map((t) => `<code class="block text-[#FDE047]">${escapeHtml(t)}</code>`).join('');
  $('logBody').innerHTML = `
    <div class="space-y-2">
      <div><span class="text-tangerine font-bold">[1. 의도 해석]</span> ${escapeHtml(log.intent)}</div>
      <div><span class="text-[#86EFAC] font-bold">[2. 호출 도구]</span>${tools}</div>
    </div>
    <div class="space-y-2">
      <div><span class="text-[#93C5FD] font-bold">[3. 적용 조건]</span> ${escapeHtml(log.filters)}</div>
      <div><span class="text-[#86EFAC] font-bold">[4. 검증 결과]</span> ${escapeHtml(log.validation)}</div>
      ${report.verification.items.map((c) => `<div>${c.status === 'pass' ? '✓' : c.status === 'warning' ? '⚠' : '✕'} ${escapeHtml(c.result)} ${escapeHtml(c.name)}: ${escapeHtml(c.detail)}</div>`).join('')}
    </div>`;
}

const FONT = { family: 'Pretendard', size: 11 };

function drawPrimary(chart) {
  state.charts.primary?.destroy();
  $('primaryChartCard').classList.toggle('hidden', !chart);
  if (!chart) return;
  $('primaryKicker').textContent = chart.kicker;
  $('primaryTitle').textContent = chart.title;
  const max = Math.max(...chart.bars);
  state.charts.primary = new Chart($('primaryChart'), {
    type: 'bar',
    data: {
      labels: chart.labels,
      datasets: [
        { type: 'line', label: '전년 대비 증감률 (%)', data: chart.line, borderColor: '#2D5A3C', backgroundColor: '#2D5A3C', borderWidth: 2.5, pointRadius: 3.5, pointBackgroundColor: '#FFFFFF', pointBorderColor: '#2D5A3C', pointBorderWidth: 2, tension: 0.35, yAxisID: 'y1', spanGaps: true },
        { type: 'bar', label: '카드 이용금액 (억 원)', data: chart.bars, backgroundColor: chart.bars.map((v) => (v >= max * 0.92 ? '#FF7A00' : 'rgba(255, 122, 0, 0.32)')), borderRadius: 6, barPercentage: 0.58, yAxisID: 'y' },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 8, font: FONT } }, tooltip: { backgroundColor: '#1E2421', padding: 10, cornerRadius: 10 } },
      scales: {
        x: { grid: { display: false }, ticks: { font: FONT, color: '#5C6660' } },
        y: { beginAtZero: true, position: 'left', grid: { color: '#EAE5DC' }, ticks: { font: FONT, color: '#5C6660' } },
        y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { font: FONT, color: '#2D5A3C', callback: (v) => `${v}%` } },
      },
    },
  });
}

function drawSecondary(chart) {
  state.charts.secondary?.destroy();
  $('secondaryChartCard').classList.toggle('hidden', !chart);
  $('primaryChartCard').classList.toggle('lg:col-span-7', Boolean(chart));
  $('primaryChartCard').classList.toggle('lg:col-span-12', !chart);
  if (!chart) return;
  $('secondaryKicker').textContent = chart.kicker;
  $('secondaryTitle').textContent = chart.title;
  const max = Math.max(...chart.data);
  state.charts.secondary = new Chart($('secondaryChart'), {
    type: 'bar',
    data: { labels: chart.labels, datasets: [{ label: '소비 비중 (%)', data: chart.data, backgroundColor: chart.data.map((v) => (v >= max * 0.85 ? '#FF7A00' : '#2D5A3C')), borderRadius: 8, barPercentage: 0.55 }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { backgroundColor: '#1E2421', padding: 10, cornerRadius: 10, callbacks: { label: (c) => ` 소비 비중: ${c.raw}%` } } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { ...FONT, size: 12, weight: 'bold' }, color: '#1E2421' } },
        y: { beginAtZero: true, grid: { color: '#EAE5DC' }, ticks: { font: FONT, color: '#5C6660', callback: (v) => `${v}%` } },
      },
    },
  });
}

function yoyClass(value) {
  if (value.startsWith('+')) return 'bg-leaf-light text-leaf';
  if (value.startsWith('-')) return 'bg-red-50 text-red-700';
  return 'bg-cream-bg text-warmgray';
}

function renderReport(report) {
  state.report = report;
  $('reportSection').classList.remove('hidden');
  $('reportMode').textContent = report.mode;
  $('reportMeta').textContent = report.meta;
  $('reportTitle').textContent = report.title;
  $('reportQuestion').textContent = `질문: "${report.question}"`;
  $('reportSummary').innerHTML = richText(report.summary);
  $('reportSource').textContent = `출처: ${report.data.source} · ${report.data.period}`;
  const v = report.verification;
  $('verifyBadge').textContent = `검증 ${v.total}건 중 ${v.passed}건 통과${v.warnings ? ` · 경고 ${v.warnings}건` : ''}`;

  $('stepTags').innerHTML = report.tags.map((t) => {
    const color = t.type === 'tangerine' ? 'bg-tangerine-light text-[#9A4A00] border-tangerine-border'
      : t.type === 'leaf' ? 'bg-leaf-light text-leaf border-leaf-border' : 'bg-white text-warmgray border-[#E2DDD5]';
    return `<span class="px-2 py-0.5 rounded-md text-[11px] font-semibold border ${color}">${escapeHtml(t.label)}</span>`;
  }).join('');
  $('stepDetail-1').textContent = '';

  $('kpiCards').innerHTML = report.kpis.map((k) => {
    const box = k.accent === 'tangerine' ? 'border-tangerine-border bg-tangerine-light/25' : k.accent === 'leaf' ? 'border-leaf-border bg-leaf-light/25' : 'border-[#EAE5DC] bg-cream-bg/60';
    const text = k.accent === 'tangerine' ? 'text-[#B85500]' : k.accent === 'leaf' ? 'text-leaf' : 'text-charcoal';
    return `<div class="p-4 sm:p-5 rounded-2xl border ${box} flex flex-col justify-between"><span class="text-xs font-bold text-warmgray">${escapeHtml(k.label)}</span><div class="text-lg sm:text-xl font-extrabold ${text} my-1.5 tracking-tight">${escapeHtml(k.value)}</div><p class="text-xs text-warmgray leading-snug">${escapeHtml(k.sub)}</p></div>`;
  }).join('');

  $('evidenceBody').innerHTML = report.table.map((r) => `
    <tr class="${r.highlight ? 'bg-tangerine-light/25 font-medium' : 'hover:bg-cream-bg/50'} transition">
      <th scope="row" class="py-3 px-4 font-bold text-charcoal">${escapeHtml(r.label)}</th>
      <td class="py-3 px-4 font-extrabold text-charcoal">${escapeHtml(r.amount)}</td>
      <td class="py-3 px-4"><span class="px-2 py-0.5 rounded-md text-xs font-bold ${yoyClass(r.yoy)}">${escapeHtml(r.yoy)}</span></td>
      <td class="py-3 px-4 text-charcoal">${escapeHtml(r.average)}</td>
      <td class="py-3 px-4 text-xs text-warmgray">${escapeHtml(r.note)}</td>
    </tr>`).join('');

  $('actionCards').innerHTML = report.actions.map((a, i) => `
    <div class="p-4 rounded-2xl bg-white border border-[#EAE5DC] hover:border-tangerine-border transition space-y-1.5">
      <div class="flex items-center justify-between">
        <span class="px-2 py-0.5 rounded-md text-[11px] font-bold ${i % 2 === 0 ? 'bg-tangerine-light text-[#9A4A00]' : 'bg-leaf-light text-leaf'}">${escapeHtml(a.badge)}</span>
        <span class="text-[11px] font-bold text-warmgray/60">0${i + 1}</span>
      </div>
      <h4 class="text-sm font-bold text-charcoal">${escapeHtml(a.title)}</h4>
      <p class="text-xs text-warmgray leading-relaxed">${escapeHtml(a.desc)}</p>
    </div>`).join('');

  $('limitations').innerHTML = report.limitations.map((l) => `<li>${escapeHtml(l)}</li>`).join('');
  renderLog(report);
  drawPrimary(report.charts.primary);
  drawSecondary(report.charts.secondary);
}

function handleEvent(event) {
  if (event.type === 'step') {
    setStep(event.step, event.status === 'done' ? 'done' : 'running', event.detail);
  } else if (event.type === 'notice') {
    showToast(event.message, 'warning');
  } else if (event.type === 'clarify') {
    setPipeline('waiting', '조건 확인 필요');
    setStep(1, 'running', '사용자의 조건 선택을 기다리고 있습니다.');
    openClarification(event);
  } else if (event.type === 'report') {
    renderReport(event.report);
    setPipeline('done', '분석 및 검증 완료');
    showToast('인사이트 보고서가 생성되었습니다.');
    $('reportSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else if (event.type === 'error') {
    failPipeline(event.message);
  }
}

function failPipeline(message) {
  setPipeline('failed', '분석 중단');
  for (let i = 1; i <= 4; i += 1) {
    if ($(`stepCard-${i}`).classList.contains('is-running')) setStep(i, 'failed', message);
  }
  showToast(message, 'warning');
}

async function runAnalysis(question, answers = null) {
  if (state.running) return;
  state.running = true;
  state.question = question;
  $('runBtn').disabled = true;
  closeClarification();
  resetPipeline();
  $('reportSection').classList.add('hidden');
  try {
    if (STATIC_DEMO) {
      await replayDemo(question, answers);
      return;
    }
    const response = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, answers }),
    });
    if (!response.ok) throw new Error('요청을 처리하지 못했습니다. 질문을 확인해 주세요.');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      lines.filter(Boolean).forEach((line) => handleEvent(JSON.parse(line)));
    }
    if (buffer.trim()) handleEvent(JSON.parse(buffer));
  } catch (err) {
    failPipeline(err instanceof TypeError ? '서버에 연결할 수 없습니다. 실행 창이 열려 있는지 확인해 주세요.' : err.message);
  } finally {
    state.running = false;
    $('runBtn').disabled = false;
  }
}

function submitQuestion(question) {
  const text = question.trim();
  if (!text) {
    showToast('분석할 질문을 입력하거나 예시 질문을 선택해 주세요.', 'warning');
    return;
  }
  $('queryInput').value = text;
  renderPresets(text);
  runAnalysis(text);
}

async function copyReport() {
  const r = state.report;
  if (!r) return;
  const text = [
    `[제주 관광 소비 인사이트 Agent 보고서] ${r.title}`, `질문: ${r.question}`, '',
    '[핵심 결론]', r.summary.replace(/\*\*/g, ''), '',
    '[주요 지표]', ...r.kpis.map((k) => `- ${k.label}: ${k.value} (${k.sub})`), '',
    '[실행 제안]', ...r.actions.map((a, i) => `${i + 1}. [${a.badge}] ${a.title}: ${a.desc}`), '',
    '[유의사항]', ...r.limitations.map((l) => `- ${l}`), '',
    `출처: ${r.data.source} (${r.data.period})`,
  ].join('\n');
  try {
    await navigator.clipboard.writeText(text);
    showToast('보고서 요약을 복사했습니다.');
  } catch {
    showToast('복사하지 못했습니다. 브라우저 권한을 확인해 주세요.', 'warning');
  }
}

function toggleModal(open) {
  $('specModal').classList.toggle('hidden', !open);
}

function toggleKeyModal(open) {
  $('keyModal').classList.toggle('hidden', !open);
  $('keyInput').value = '';
  $('keyError').classList.add('hidden');
  if (open) $('keyInput').focus();
}

function showKeyError(message) {
  $('keyError').textContent = message;
  $('keyError').classList.remove('hidden');
}

async function submitKey(event) {
  event.preventDefault();
  const apiKey = $('keyInput').value.trim();
  if (!apiKey) {
    showKeyError('API 키를 입력해 주세요.');
    return;
  }
  $('keySaveBtn').disabled = true;
  $('keySaveBtn').textContent = '확인 중';
  try {
    const response = await fetch('/api/settings/api-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
    });
    const result = await response.json();
    if (!response.ok) {
      showKeyError(typeof result.detail === 'string' ? result.detail : 'API 키 형식을 확인해 주세요.');
      return;
    }
    toggleKeyModal(false);
    showToast(result.message, result.verified ? 'success' : 'warning');
    await loadStatus();
  } catch {
    showKeyError('서버에 연결할 수 없습니다. 실행 창이 열려 있는지 확인해 주세요.');
  } finally {
    $('keyInput').value = '';
    $('keySaveBtn').disabled = false;
    $('keySaveBtn').textContent = '확인 후 저장';
  }
}

async function deleteKey() {
  try {
    const response = await fetch('/api/settings/api-key', { method: 'DELETE' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail);
    toggleKeyModal(false);
    showToast(result.message);
    await loadStatus();
  } catch {
    showKeyError('API 키를 삭제하지 못했습니다.');
  }
}

async function loadStatus() {
  try {
    const status = STATIC_DEMO ? (await loadDemo()).status : await (await fetch('/api/status')).json();
    if (!status.ready) {
      $('dataBadgeText').textContent = '데이터 오류';
      showToast(status.error, 'warning');
      return;
    }
    $('dataBadgeText').textContent = `${status.isSample ? '합성 샘플' : '실제 데이터'} · ${status.period}`;
    $('modeBadge').textContent = status.llm ? 'Claude 사용' : '규칙 기반 모드';
    $('keyBtn').textContent = status.llm ? 'API 키 관리' : 'API 키 입력';
    $('keyState').textContent = status.llm ? '저장된 API 키로 Claude를 사용 중입니다.' : '저장된 API 키가 없습니다.';
    $('keyDeleteBtn').classList.toggle('hidden', !status.llm);
    $('sampleBanner').classList.toggle('hidden', !status.isSample);
    $('footerSource').textContent = `데이터: ${status.source}`;
    if (STATIC_DEMO) {
      $('modeBadge').textContent = '공개 데모';
      $('keyBtn').classList.add('hidden');
      document.querySelector('#sampleBanner p').textContent = '공개 데모입니다. 합성 샘플 데이터로 미리 계산한 예시 질문만 제공하며, 화면의 수치는 실제 제주 관광 통계가 아닙니다.';
    }
    $('qualityBox').innerHTML = status.quality.map((q) => `<p>${escapeHtml(q)}</p>`).join('');
  } catch {
    showToast('서버 상태를 확인할 수 없습니다.', 'warning');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  renderPresets($('queryInput').value);
  loadStatus();

  $('queryForm').addEventListener('submit', (e) => { e.preventDefault(); submitQuestion($('queryInput').value); });
  $('presetChips').addEventListener('click', (e) => {
    const chip = e.target.closest('button[data-index]');
    if (chip) submitQuestion(PRESETS[Number(chip.dataset.index)].query);
  });
  $('clarifyDemoBtn').addEventListener('click', () => submitQuestion(AMBIGUOUS_QUERY));
  $('clarificationFields').addEventListener('click', (e) => {
    const option = e.target.closest('button[data-key]');
    if (!option) return;
    state.answers[option.dataset.key] = option.dataset.value;
    option.parentElement.querySelectorAll('button').forEach((b) => {
      const active = b === option;
      b.className = `${OPTION_BASE} ${active ? OPTION_ACTIVE : OPTION_IDLE}`;
      b.setAttribute('aria-pressed', String(active));
    });
  });
  $('clarifySubmitBtn').addEventListener('click', () => runAnalysis(state.question, { ...state.answers }));
  $('clarifyCancelBtn').addEventListener('click', () => { closeClarification(); $('pipelineSection').classList.add('hidden'); });
  $('logToggleBtn').addEventListener('click', () => {
    const hidden = $('logPanel').classList.toggle('hidden');
    $('logToggleBtn').setAttribute('aria-expanded', String(!hidden));
    $('logChevron').style.transform = hidden ? '' : 'rotate(180deg)';
  });
  $('copyBtn').addEventListener('click', copyReport);
  $('printBtn').addEventListener('click', () => window.print());
  $('logoBtn').addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  $('specBtn').addEventListener('click', () => toggleModal(true));
  $('specCloseBtn').addEventListener('click', () => toggleModal(false));
  $('specCloseIcon').addEventListener('click', () => toggleModal(false));
  $('specModal').addEventListener('click', (e) => { if (e.target === $('specModal')) toggleModal(false); });
  $('keyBtn').addEventListener('click', () => toggleKeyModal(true));
  $('keyCloseIcon').addEventListener('click', () => toggleKeyModal(false));
  $('keyForm').addEventListener('submit', submitKey);
  $('keyDeleteBtn').addEventListener('click', deleteKey);
  $('keyModal').addEventListener('click', (e) => { if (e.target === $('keyModal')) toggleKeyModal(false); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { toggleModal(false); toggleKeyModal(false); } });
});
