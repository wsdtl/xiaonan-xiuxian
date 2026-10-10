'use strict';
const $ = (id) => document.getElementById(id);
let UI = {};
const REMEMBER = 'lingtian.scope';

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

async function load(scope) {
  say('读取中…');
  const url = '/lingtian/data' + (scope ? '?scope=' + encodeURIComponent(scope) : '');
  let data;
  try { data = await (await fetch(url)).json(); } catch (error) { say('读不到数据：' + error); return; }
  if (data.error) { say(data.error); return; }
  UI = data.ui || {};
  $('title').textContent = UI['标题'] || '宗门灵田';
  $('intro').textContent = UI['说明'] || '';
  $('label-terrain').textContent = UI['地形'] || '可选地形';
  $('label-usual').textContent = UI['常用'] || '常用命令';
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
  for (const line of data.usual || []) $('usual').append(commandBox(line));
  if (!scopes.length) { $('notice').textContent = UI['没人公开'] || ''; $('terrains').innerHTML = ''; $('command').innerHTML = ''; say(''); return; }
  $('notice').textContent = data.notice || '';
  $('terrains').innerHTML = '';
  const terrains = data.terrains || [];
  if (!terrains.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = UI['未选'] || '';
    $('terrains').append(empty);
  }
  for (const name of terrains) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'item';
    const label = document.createElement('span');
    label.className = 'item-name';
    label.textContent = name + (name === data.terrain ? '（当前）' : '');
    button.append(label);
    button.onclick = () => show('灵田 选地形 ' + name);
    $('terrains').append(button);
  }
  $('command').innerHTML = '';
  if (terrains.length) show('灵田 选地形 ' + terrains[0]);
  say('');
}

function show(line) {
  const host = $('command');
  host.innerHTML = '';
  host.append(commandBox(line));
}

$('refresh').onclick = () => load($('scope').value);
const FROM_URL = new URLSearchParams(location.search).get('scope');
load(FROM_URL || localStorage.getItem(REMEMBER) || '');
