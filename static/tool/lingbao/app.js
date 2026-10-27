'use strict';
const $ = (id) => document.getElementById(id);
let UI = {};
let OWNED = [];
let MODE = 'owned';
let PAGE = 1;
const REMEMBER = 'lingbao.scope';

function say(text) { $('status').textContent = text || ''; }

function name(item) { return item ? String(item['名称'] || '') : ''; }
function idOf(item) { return item ? String(item['编号'] || '') : ''; }

async function load(scope, mode, page) {
  if (mode) MODE = mode;
  if (page) PAGE = page;
  say('读取中…');
  const params = new URLSearchParams({ page: String(PAGE) });
  if (scope) params.set('scope', scope);
  if (MODE === 'all') params.set('view', 'all');
  let data;
  try { data = await (await fetch('/lingbao/data?' + params)).json(); } catch (error) { say('读不到数据：' + error); return; }
  if (data.error) { say(data.error); return; }
  UI = data.ui || {};
  OWNED = data.owned || [];
  $('title').textContent = UI['标题'] || '灵宝谱';
  $('intro').textContent = UI['说明'] || '';
  $('label-scope').textContent = UI['挑人'] || '挑自己';
  $('label-active').textContent = UI['当前'] || '当前执掌';
  // 两个档位：自己的灵宝谱 与 全谱（词都来自数据）。
  $('label-owned').textContent = MODE === 'all' ? (UI['谱标题'] || '灵宝谱') : (UI['自备'] || '你的灵宝谱');
  $('vault').textContent = MODE === 'all' ? (data.catalog_text || '') : '';
  const ownMode = MODE !== 'all';
  $('label-active').hidden = !ownMode;
  $('active').hidden = !ownMode;
  $('active').textContent = data.active ? name(data.active) + ' · ' + (UI['权柄'] || '') + ' ' + String(data.active['权柄'] || '') : (UI['没有当前'] || '');
  const select = $('scope');
  const scopes = data.scopes || [];
  select.innerHTML = '';
  for (const item of scopes) {
    const option = document.createElement('option');
    option.value = item.id;
    option.textContent = item.name;
    select.append(option);
  }
  select.disabled = !scopes.length;
  if (data.scope) select.value = data.scope;
  select.onchange = () => { localStorage.setItem(REMEMBER, select.value); load(select.value, MODE, 1); };
  renderTabs();
  if (!scopes.length) { $('notice').textContent = UI['没人公开'] || ''; $('owned').innerHTML = ''; say(''); return; }
  $('notice').textContent = data.notice || '';
  $('page-text').textContent = data.page_text || '';
  $('prev').disabled = Number(data.page || 1) <= 1;
  $('next').disabled = Number(data.page || 1) >= Number(data.page_count || 1);
  render();
  openFromUrl();
  say('');
}

// `?id=540001` 直接摊开那一件的详情（与百科的 ?id= 同一套深链）。
function openFromUrl() {
  const wanted = new URLSearchParams(location.search).get('id');
  if (!wanted) return;
  const hit = OWNED.find((item) => idOf(item) === wanted);
  if (hit) show(hit);
}

function renderTabs() {
  const host = $('tabs');
  host.innerHTML = '';
  const rows = [
    { mode: 'owned', label: UI['自备'] || '你的灵宝谱' },
    { mode: 'all', label: UI['谱标题'] || '灵宝谱' },
  ];
  for (const row of rows) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tab' + (row.mode === MODE ? ' on' : '');
    button.textContent = row.label;
    button.onclick = () => load($('scope').value, row.mode, 1);
    host.append(button);
  }
}

function render() {
  const host = $('owned');
  host.innerHTML = '';
  if (!OWNED.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = UI['没有自备'] || '';
    host.append(empty);
    return;
  }
  for (const item of OWNED) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'item';
    const label = document.createElement('span');
    label.className = 'item-name';
    label.textContent = name(item);
    const meta = document.createElement('span');
    meta.className = 'item-meta';
    meta.textContent = idOf(item);
    const power = document.createElement('span');
    power.className = 'item-power';
    power.textContent = (UI['权柄'] || '') + ' ' + String(item['权柄'] || '');
    button.append(label, meta, power);
    if (MODE === 'all') {
      const gain = document.createElement('span');
      gain.className = 'item-gain';
      gain.textContent = (UI['谱行加成'] || '') + ' ' + String(item['加成方向'] || '');
      button.append(gain);
    }
    button.onclick = () => show(item);
    host.append(button);
  }
}

function row(key, value) {
  const term = document.createElement('dt');
  term.className = 'field-key';
  term.textContent = key;
  const text = document.createElement('dd');
  text.className = 'field-value';
  text.textContent = value;
  return [term, text];
}

function rowsFor(item) {
  return [
    ['编号', idOf(item)],
    [UI['权柄'] || '权柄', String(item['权柄'] || '')],
    [UI['效果'] || '效果', String(item['效果'] || '')],
  ];
}

function show(item) {
  $('detail-title').textContent = name(item);
  const host = $('detail');
  host.innerHTML = '';
  const list = document.createElement('dl');
  list.className = 'fields';
  for (const [key, value] of rowsFor(item)) {
    list.append(...row(key, value));
  }
  host.append(list);
  if (item['说明']) {
    const text = document.createElement('p');
    text.className = 'lore';
    text.textContent = String(item['说明']);
    host.append(text);
  }
  host.append(commandBox('使用 ' + String(item['名称'] || '')));
  if (!$('detail-dialog').open) $('detail-dialog').showModal();
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

$('refresh').onclick = () => load($('scope').value, MODE, PAGE);
$('prev').onclick = () => load($('scope').value, MODE, Math.max(1, PAGE - 1));
$('next').onclick = () => load($('scope').value, MODE, PAGE + 1);
// 原生 <dialog> 点遮罩不会关：点在 dialog 本身（而不是内容）上才算点到遮罩。
$('detail-dialog').addEventListener('click', (event) => {
  if (event.target === $('detail-dialog')) $('detail-dialog').close();
});
const FROM_URL = new URLSearchParams(location.search);
// 两个档位都支持深链：?view=all 直接开全谱。
const MODE_URL = FROM_URL.get('view') === 'all' ? 'all' : 'owned';
load(FROM_URL.get('scope') || localStorage.getItem(REMEMBER) || '', MODE_URL, 1);
