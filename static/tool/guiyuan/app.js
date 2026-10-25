'use strict';
const $ = (id) => document.getElementById(id);
let UI = {};
let PREVIEW = null;
const REMEMBER = 'page.scope';

function say(text) { $('status').textContent = text || ''; }

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

function cell(name, meta) {
  const box = document.createElement('div');
  box.className = 'cell';
  const head = document.createElement('span');
  head.className = 'cell-name';
  head.textContent = name;
  box.append(head);
  if (meta) {
    const tail = document.createElement('span');
    tail.className = 'cell-meta';
    tail.textContent = meta;
    box.append(tail);
  }
  return box;
}

async function load(scope) {
  say('读取中…');
  const url = location.pathname + '/data' + (scope ? '?scope=' + encodeURIComponent(scope) : '');
  let data;
  try { data = await (await fetch(url)).json(); } catch (error) { say('读不到数据：' + error); return; }
  if (data.error) { say(data.error); return; }
  UI = data.ui || {};
  PREVIEW = data.preview || null;
  document.title = (UI['标题'] || document.title) + ' · 晓楠修仙';
  $('title').textContent = UI['标题'] || $('title').textContent;
  $('intro').textContent = UI['说明'] || '';
  $('label-scope').textContent = UI['挑人'] || '挑自己';
  $('label-preview').textContent = UI['地点'] || '预览';
  $('label-modes').textContent = UI['类别'] || '发哪一条';
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
  select.onchange = () => { localStorage.setItem(REMEMBER, select.value); load(select.value); };
  if (!scopes.length) { $('notice').textContent = UI['没人公开'] || ''; $('preview').innerHTML = ''; $('modes').innerHTML = ''; $('command').innerHTML = ''; $('medicine').textContent = ''; say(''); return; }
  $('notice').textContent = data.notice || '';
  renderPreview();
  renderModes(data);
  say('');
}

// 预览的形状由后端给（地点／道侣／丹药／丹药齐备／构筑）：这里只按数据里的词排出来。
function renderPreview() {
  const host = $('preview');
  host.innerHTML = '';
  $('medicine').textContent = '';
  // 核心没给预览（例如「当前没有同行道侣」）时这里什么都不印：理由由上面的提示说，
  // 印「道侣还没有这一类构筑」会把人往错的地方引（实测过）。
  if (!PREVIEW) return;
  host.append(cell(UI['地点'] || '地点', String(PREVIEW['地点'] || '')));
  host.append(cell(UI['道侣'] || '同行道侣', String(PREVIEW['道侣'] || '')));
  host.append(cell(UI['丹药'] || '归元丹', String(PREVIEW['丹药'] || '')));
  // 丹药齐备与否照印后端那句（有丹／无丹），不自己判也不自己写。
  $('medicine').textContent = PREVIEW['丹药齐备'] ? (UI['有丹'] || '') : (UI['无丹'] || '');
  $('medicine').classList.toggle('medicine-missing', !PREVIEW['丹药齐备']);
  const rows = PREVIEW['构筑'] || [];
  const title = document.createElement('p');
  title.className = 'blocks-title';
  title.textContent = UI['构筑'] || '当前构筑';
  host.append(title);
  if (!rows.length) { host.append(cell(UI['空'] || '')); return; }
  for (const row of rows) {
    host.append(cell(String(row['类别'] || ''), String(row['数量'] || '')));
  }
}

function renderModes(data) {
  const host = $('modes');
  host.innerHTML = '';
  const items = data.categories || data.modes || [];
  for (const name of items) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'mode';
    button.textContent = name;
    button.onclick = () => show(modeLine(name));
    host.append(button);
  }
  $('command').innerHTML = '';
  if (items.length) show(modeLine(items[0]));
}

function modeLine(name) {
  return '归元 ' + name;
}

function show(line) {
  const host = $('command');
  host.innerHTML = '';
  host.append(commandBox(line));
}

$('refresh').onclick = () => load($('scope').value);
const FROM_URL = new URLSearchParams(location.search).get('scope');
load(FROM_URL || localStorage.getItem(REMEMBER) || '');
