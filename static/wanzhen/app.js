'use strict';
const $ = (id) => document.getElementById(id);
let UI = {};
let ITEMS = [];
let PICKED = null;
const REMEMBER = 'wanzhen.scope';

function say(text) { $('status').textContent = text || ''; }

async function load(scope) {
  say('读取中…');
  const url = '/wanzhen/data' + (scope ? '?scope=' + encodeURIComponent(scope) : '');
  let data;
  try { data = await (await fetch(url)).json(); } catch (error) { say('读不到数据：' + error); return; }
  if (data.error) { say(data.error); return; }
  UI = data.ui || {};
  ITEMS = data.items || [];
  $('title').textContent = UI['标题'] || '万珍殿';
  $('intro').textContent = UI['说明'] || '';
  $('label-category').textContent = UI['分类'] || '分类';
  $('label-quantity').textContent = UI['数量'] || '数量';
  $('label-items').textContent = UI['成品'] || '你的成品';
  $('vault').textContent = data.vault || '';
  $('notice').textContent = data.notice || '';
  const scopes = data.scopes || [];
  const select = $('scope');
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
  if (!scopes.length) { $('notice').textContent = UI['没人公开'] || ''; $('items').innerHTML = ''; say(''); return; }
  const cat = $('category');
  cat.innerHTML = '';
  for (const name of data.categories || []) {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    cat.append(option);
  }
  cat.onchange = renderItems;
  $('quantity').onchange = renderItems;
  say('');
  renderItems();
}

function commandFor(item, quantity) {
  const qty = Math.max(1, parseInt(quantity, 10) || 1);
  // 阵法只报名字：状态键是代码内部的东西，玩家不该见；同名多条时带上灵宝名做区分。
  if (item.category === '阵法') {
    const tail = item.treasure_name ? '[' + item.treasure_name + ']' : '';
    return '捐入万珍殿 阵法 ' + item.name + tail;
  }
  if (item.category === '器律') return '捐入万珍殿 器律 ' + item.id + ' ' + qty;
  return '捐入万珍殿 ' + item.category + ' ' + item.id + ' ' + (item.grade || '01') + ' ' + qty;
}

function renderItems() {
  const cat = $('category').value;
  const host = $('items');
  host.innerHTML = '';
  const rows = ITEMS.filter((item) => item.category === cat);
  if (!rows.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = UI['没有成品'] || '';
    host.append(empty);
    $('command').innerHTML = '';
    return;
  }
  for (const item of rows) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'item';
    const name = document.createElement('span');
    name.className = 'item-name';
    name.textContent = item.name;
    const meta = document.createElement('span');
    meta.className = 'item-meta';
    meta.textContent = item.id + ' · 品级 ' + (item.grade || '—') + ' · 存 ' + item.quantity;
    button.append(name, meta);
    if (item.category === '阵法') {
      const lucky = document.createElement('span');
      lucky.className = 'item-meta';
      lucky.textContent = item.treasure
        ? (UI['灵宝'] || '灵宝') + '：' + (item.treasure_name || item.treasure) + ' · ' + (item.treasure_effect || '')
        : '';
      button.append(lucky);
    }
    button.onclick = () => { PICKED = item; showCommand(); };
    host.append(button);
  }
  // 默认选中第一件（有货就先把命令摆出来），想换点别的行就行。
  PICKED = rows[0];
  showCommand();
}

function showCommand() {
  const host = $('command');
  host.innerHTML = '';
  if (!PICKED) return;
  const line = commandFor(PICKED, $('quantity').value);
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
