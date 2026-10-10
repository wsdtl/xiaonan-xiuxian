'use strict';
const $ = (id) => document.getElementById(id);
let UI = {};
let PREVIEW = null;
const REMEMBER = 'page.scope';

function say(text) { $('status').textContent = text || ''; }

function commandBox(line) {
  const box = document.createElement('div');
  box.className = 'cmd';
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
  box.append(text, copy);
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
  const prefix = location.pathname;
  const url = prefix + '/data' + (scope ? '?scope=' + encodeURIComponent(scope) : '');
  let data;
  try { data = await (await fetch(url)).json(); } catch (error) { say('读不到数据：' + error); return; }
  if (data.error) { say(data.error); return; }
  UI = data.ui || {};
  PREVIEW = data.preview || null;
  document.title = (UI['标题'] || document.title) + ' · 晓楠修仙';
  $('title').textContent = UI['标题'] || $('title').textContent;
  $('intro').textContent = UI['说明'] || '';
  $('label-preview').textContent = UI['地点'] || '预览';
  $('label-modes').textContent = UI['类别'] || UI['模式'] || '发哪一条';
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
  if (!scopes.length) { $('notice').textContent = UI['没人公开'] || ''; $('preview').innerHTML = ''; $('modes').innerHTML = ''; $('command').innerHTML = ''; say(''); return; }
  $('notice').textContent = data.notice || '';
  renderPreview();
  renderModes(data);
  say('');
}

function renderPreview() {
  const host = $('preview');
  host.innerHTML = '';
  if (!PREVIEW) { host.append(cell(UI['空'] || '（核心没有给出预览）')); return; }
  for (const [key, value] of Object.entries(PREVIEW)) {
    if (value === null || value === undefined || value === '') continue;
    if (typeof value === 'object') {
      const rows = Array.isArray(value) ? value : Object.entries(value).map(([k, v]) => [k, v]);
      for (const row of rows) {
        if (Array.isArray(row)) host.append(cell(String(row[0]), String(row[1])));
        else if (row && typeof row === 'object') host.append(cell(String(Object.values(row)[0]), String(Object.values(row)[1] || '')));
      }
      continue;
    }
    host.append(cell(String(key), String(value)));
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
