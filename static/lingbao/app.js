'use strict';
const $ = (id) => document.getElementById(id);
let UI = {};
let OWNED = [];
const REMEMBER = 'lingbao.scope';

function say(text) { $('status').textContent = text || ''; }

function name(item) {
  if (!item) return '';
  const raw = item['名称'] || item.name || item['编号'] || item.id || '';
  return String(raw);
}

function idOf(item) {
  if (!item) return '';
  return String(item['编号'] || item.treasure_id || item.id || item.content_id || '');
}

async function load(scope) {
  say('读取中…');
  const url = '/lingbao/data' + (scope ? '?scope=' + encodeURIComponent(scope) : '');
  let data;
  try { data = await (await fetch(url)).json(); } catch (error) { say('读不到数据：' + error); return; }
  if (data.error) { say(data.error); return; }
  UI = data.ui || {};
  OWNED = data.owned || [];
  $('title').textContent = UI['标题'] || '灵宝谱';
  $('intro').textContent = UI['说明'] || '';
  $('label-active').textContent = UI['当前'] || '当前执掌';
  $('label-owned').textContent = UI['自备'] || '你的灵宝谱';
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
  if (!scopes.length) { $('notice').textContent = UI['没人公开'] || ''; $('owned').innerHTML = ''; $('active').textContent = ''; say(''); return; }
  $('notice').textContent = data.notice || '';
  $('active').textContent = data.active ? name(data.active) : (UI['没有当前'] || '');
  render();
  say('');
}

function render() {
  const host = $('owned');
  host.innerHTML = '';
  if (!OWNED.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = UI['没有自备'] || '';
    host.append(empty);
    $('command').innerHTML = '';
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
    button.append(label, meta);
    button.onclick = () => show(idOf(item));
    host.append(button);
  }
  show(idOf(OWNED[0]));
}

function show(id) {
  const host = $('command');
  host.innerHTML = '';
  if (!id) return;
  const line = '执掌灵宝 ' + id;
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
  host.append(box);
}

$('refresh').onclick = () => load($('scope').value);
const FROM_URL = new URLSearchParams(location.search).get('scope');
load(FROM_URL || localStorage.getItem(REMEMBER) || '');
