'use strict';
const $ = (id) => document.getElementById(id);
let UI = {};
let TERRAINS = [];
const REMEMBER = 'lingtian.scope';

function say(text) { $('status').textContent = text || ''; }

function commandBox(line, withLabel) {
  const box = document.createElement('div');
  box.className = 'cmd';
  if (withLabel) {
    const label = document.createElement('span');
    label.className = 'cmd-label';
    label.textContent = UI['命令'] || '';
    box.append(label);
  }
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

async function load(scope) {
  say('读取中…');
  const url = '/lingtian/data' + (scope ? '?scope=' + encodeURIComponent(scope) : '');
  let data;
  try { data = await (await fetch(url)).json(); } catch (error) { say('读不到数据：' + error); return; }
  if (data.error) { say(data.error); return; }
  UI = data.ui || {};
  $('title').textContent = UI['标题'] || '宗门灵田';
  $('intro').textContent = UI['说明'] || '';
  $('label-scope').textContent = UI['挑人'] || '挑自己';
  $('label-terrain').textContent = UI['地形'] || '可选地形';
  $('label-usual').textContent = UI['常用'] || '常用命令';
  // 开没开、当前地形、地形数量：三句都由后端按数据模板填好，页面只照印。
  $('state').textContent = data.started_text || '';
  $('terrain-text').textContent = data.terrain_text ? (UI['当前地形'] || '') + '：' + data.terrain_text : '';
  $('hint').textContent = data.terrain_hint || '';
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
  $('usual').innerHTML = '';
  for (const line of data.usual || []) $('usual').append(commandBox(line, false));
  if (!scopes.length) { $('notice').textContent = UI['没人公开'] || ''; $('terrains').innerHTML = ''; $('command').innerHTML = ''; say(''); return; }
  $('notice').textContent = data.notice || '';
  $('terrains').innerHTML = '';
  TERRAINS = data.terrains || [];
  if (!TERRAINS.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = UI['未选'] || '';
    $('terrains').append(empty);
  }
  for (const name of TERRAINS) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'item';
    const label = document.createElement('span');
    label.className = 'item-name';
    label.textContent = name;
    button.append(label);
    // 选中地形用数据里的「当前地形」这个词，不再写死「（当前）」。
    if (name === data.terrain) {
      const mark = document.createElement('span');
      mark.className = 'item-mark';
      mark.textContent = UI['当前地形'] || '';
      button.append(mark);
    }
    button.onclick = () => show('灵田 选地形 ' + name);
    $('terrains').append(button);
  }
  $('command').innerHTML = '';
  if (TERRAINS.length) show('灵田 选地形 ' + TERRAINS[0]);
  say('');
}

function show(line) {
  const host = $('command');
  host.innerHTML = '';
  host.append(commandBox(line, true));
}

$('refresh').onclick = () => load($('scope').value);
const FROM_URL = new URLSearchParams(location.search).get('scope');
load(FROM_URL || localStorage.getItem(REMEMBER) || '');
