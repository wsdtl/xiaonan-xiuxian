'use strict';
const $ = (id) => document.getElementById(id);
let UI = {};
let SCOPE = '';
let FORMATIONS = [];
const REMEMBER = 'lianzhen.scope';

function say(text) { $('status').textContent = text || ''; }

function fill(select, rows, label) {
  select.innerHTML = '';
  for (const row of rows) {
    const option = document.createElement('option');
    option.value = row.id;
    option.textContent = label ? label(row) : row.name;
    select.append(option);
  }
}

// 选中阵法的说明来自核心（`SectFacilityEntry.detail`）：页面只照印，不自己写。
function showDetail() {
  const hit = FORMATIONS.find((row) => row.id === $('formation').value);
  $('detail').textContent = hit && hit.detail ? hit.detail : '';
}

async function load(scope) {
  say('读取中…');
  const url = '/lianzhen/data' + (scope ? '?scope=' + encodeURIComponent(scope) : '');
  let data;
  try { data = await (await fetch(url)).json(); } catch (error) { say('读不到数据：' + error); return; }
  if (data.error) { say(data.error); return; }
  UI = data.ui || {};
  $('title').textContent = UI['标题'] || '演阵台';
  $('intro').textContent = UI['说明'] || '';
  $('label-scope').textContent = UI['挑人'] || '挑自己';
  $('label-formation').textContent = UI['阵法'] || '阵法';
  $('label-grade').textContent = UI['品级'] || '品级';
  $('label-triple').textContent = UI['三相'] || '';
  $('calc').textContent = UI['算一算'] || '算一算';
  fill($('scope'), data.scopes || []);
  $('scope').disabled = !(data.scopes || []).length;
  if (data.scope) { $('scope').value = data.scope; SCOPE = data.scope; }
  $('scope').onchange = () => { localStorage.setItem(REMEMBER, $('scope').value); SCOPE = $('scope').value; load(SCOPE); };
  if (!(data.scopes || []).length) { $('notice').textContent = UI['没人公开'] || ''; say(''); return; }
  FORMATIONS = data.formations || [];
  fill($('formation'), FORMATIONS);
  fill($('grade'), (data.grades || []).map((g) => ({ id: g, name: g })));
  $('formation').onchange = showDetail;
  showDetail();
  $('notice').textContent = data.notice || '';
  say('');
}

async function calc() {
  const params = new URLSearchParams({
    scope: SCOPE,
    identifier: $('formation').value,
    grade: $('grade').value,
    shoubao: $('shoubao').value || '0',
    lingkuang: $('lingkuang').value || '0',
    lingzhi: $('lingzhi').value || '0',
  });
  say('算中…');
  const data = await (await fetch('/lianzhen/preview?' + params)).json();
  say('');
  render(data);
}

function addText(host, className, text) {
  const line = document.createElement('p');
  line.className = className;
  line.textContent = text;
  host.append(line);
}

function commandBox(line) {
  const box = document.createElement('div');
  box.className = 'cmd';
  const label = document.createElement('span');
  label.className = 'cmd-label';
  label.textContent = UI['命令'] || '';
  const text = document.createElement('code');
  text.className = 'cmd-text';
  text.textContent = line;
  const copy = document.createElement('button');
  copy.type = 'button';
  copy.className = 'copy';
  copy.textContent = '复制';
  copy.onclick = async () => {
    try { await navigator.clipboard.writeText(line); copy.textContent = '已复制'; }
    catch (error) { copy.textContent = '请手动复制'; }
  };
  box.append(label, text, copy);
  return box;
}

function commandLine() {
  return ['演阵台', '炼阵', $('formation').value, $('grade').value, $('shoubao').value || '0', $('lingkuang').value || '0', $('lingzhi').value || '0'].join(' ');
}

function renderFields(host, view) {
  const rows = view['字段'] || [];
  if (!rows.length) return;
  const list = document.createElement('dl');
  list.className = 'preview';
  for (const row of rows) {
    const term = document.createElement('dt');
    term.className = 'field-key';
    term.textContent = row['键'];
    const value = document.createElement('dd');
    value.className = 'field-value';
    value.textContent = row['值'];
    list.append(term, value);
  }
  host.append(list);
}

function renderMaterials(host, view) {
  const rows = view['材料'] || [];
  if (!rows.length) return;
  const title = document.createElement('h3');
  title.className = 'refs-title';
  title.textContent = '材料';
  const list = document.createElement('ul');
  list.className = 'materials';
  for (const row of rows) {
    const item = document.createElement('li');
    item.className = 'material';
    const name = document.createElement('span');
    name.className = 'material-name';
    name.textContent = (row['品级'] || '') + (row['名称'] || '');
    const meta = document.createElement('span');
    meta.className = 'material-meta';
    meta.textContent = [row['类别'], row['编号'], '×' + row['数量']].filter(Boolean).join(' · ');
    item.append(name, meta);
    list.append(item);
  }
  host.append(title, list);
}

function render(data) {
  const host = $('result');
  host.innerHTML = '';
  $('result-title').textContent = UI['结果'] || '';
  if (data.error) {
    addText(host, 'reason', data.error);
  } else {
    if (data.notice) addText(host, 'reason', data.notice);
    const view = data.preview;
    if (view) {
      $('result-title').textContent = view['标题'] || UI['结果'] || '';
      renderFields(host, view);
      renderMaterials(host, view);
      const cost = view['费用'];
      if (cost) addText(host, 'cost', cost['键'] + ' ' + cost['值']);
      if (view['去向']) addText(host, 'destiny', view['去向']);
    }
  }
  host.append(commandBox(commandLine()));
  openSheet();
}

function openSheet() {
  if (!$('result-dialog').open) $('result-dialog').showModal();
}

$('calc').onclick = calc;
$('refresh').onclick = () => load($('scope').value);
// 原生 <dialog> 点遮罩不会关：点在 dialog 本身（而不是内容）上才算点到遮罩。
$('result-dialog').addEventListener('click', (event) => {
  if (event.target === $('result-dialog')) $('result-dialog').close();
});
const FROM_URL = new URLSearchParams(location.search).get('scope');
load(FROM_URL || localStorage.getItem(REMEMBER) || '');
