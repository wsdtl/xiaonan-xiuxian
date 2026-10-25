'use strict';
const $ = (id) => document.getElementById(id);
let UI = {};
let CANDIDATES = [];
let MEDICINE = { id: '', name: '' };
const REMEMBER = 'butian.scope';

function say(text) { $('status').textContent = text || ''; }

async function load(scope) {
  say('读取中…');
  const url = '/butian/data' + (scope ? '?scope=' + encodeURIComponent(scope) : '');
  let data;
  try {
    const res = await fetch(url);
    data = await res.json();
  } catch (error) {
    say('读不到数据：' + error);
    return;
  }
  if (data.error) { $('targets').innerHTML = ''; say(data.error); return; }
  UI = data.ui || {};
  CANDIDATES = data.candidates || [];
  MEDICINE = { id: data.medicine_id || '', name: data.medicine_name || '' };
  $('title').textContent = UI['标题'] || '九霄补天';
  $('intro').textContent = UI['说明'] || '';
  $('label-scope').textContent = UI['挑人'] || '挑自己';
  renderScopes(data);
  if (!(data.scopes || []).length) { $('targets').innerHTML = ''; say(''); $('hint').textContent = UI['没人公开'] || ''; return; }
  $('hint').textContent = UI['命令'] || '';
  say('');
  renderTargets(data.targets || []);
}

function renderScopes(data) {
  const select = $('scope');
  const list = data.scopes || [];
  select.innerHTML = '';
  for (const item of list) {
    const option = document.createElement('option');
    option.value = item.id;
    option.textContent = item.name;
    select.append(option);
  }
  select.disabled = list.length === 0;
  if (data.scope) select.value = data.scope;
  select.onchange = () => { localStorage.setItem(REMEMBER, select.value); load(select.value); };
}

function renderTargets(targets) {
  const host = $('targets');
  host.innerHTML = '';
  if (!targets.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = UI['没有道侣'] || '';
    host.append(empty);
    return;
  }
  for (const target of targets) {
    const box = document.createElement('article');
    box.className = 'target';
    const head = document.createElement('div');
    head.className = 'target-head';
    const who = document.createElement('h2');
    who.textContent = (target.kind === '道侣' ? (UI['道侣'] || '同行道侣') + ' · ' : '') + (target.name || '');
    const realm = document.createElement('p');
    realm.className = 'realm';
    realm.textContent = (UI['当前境界'] || '当前境界') + '：' + (target.realm || '');
    const state = document.createElement('p');
    state.className = 'state ' + (target.correctable ? 'yes' : 'no');
    state.textContent = target.correctable ? (UI['可补正'] || '') : (UI['不可补正'] || '');
    head.append(who, realm, state);
    box.append(head);
    if (!target.correctable && target.reason) {
      const reason = document.createElement('p');
      reason.className = 'reason';
      reason.textContent = target.reason;
      box.append(reason);
    }
    if (target.correctable) box.append(renderMeds(target));
    host.append(box);
  }
}

function renderMeds(target) {
  const wrap = document.createElement('div');
  wrap.className = 'meds';
  const title = document.createElement('h3');
  title.textContent = UI['候选丹'] || '包里的突破丹';
  wrap.append(title);
  // 每次补天另扣的那枚丹（编号一直有发、页面从没用过）：名字与编号都照印。
  if (MEDICINE.name || MEDICINE.id) {
    const extra = document.createElement('p');
    extra.className = 'extra';
    extra.textContent = [UI['丹药'] || '', MEDICINE.name, MEDICINE.id].filter(Boolean).join(' ');
    wrap.append(extra);
  }
  const legal = new Set((target.legal || []).map((row) => row.id + '|' + row.grade));
  let shown = 0;
  let first = null;
  for (const med of CANDIDATES) {
    if (!legal.has(med.id + '|' + med.grade)) continue;
    shown += 1;
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'med';
    const name = document.createElement('span');
    name.className = 'med-name';
    name.textContent = med.name + ' · ' + med.grade_name;
    const meta = document.createElement('span');
    meta.className = 'med-meta';
    meta.textContent = med.id + ' · 存 ' + med.quantity;
    row.append(name, meta);
    // 命令钉在**点中的那一行下面**：原来追加在整张列表末尾，长长的候选丹里点一枚要往下滚才看见命令。
    row.onclick = () => pick(target, med, wrap, row);
    wrap.append(row);
    if (first === null) first = { med, row };
  }
  if (!shown) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = UI['没有丹'] || '';
    wrap.append(empty);
  } else if (first) {
    // 默认就选中第一枚合法丹：页面的承诺是「把要发的命令原文摆出来」，不该藏在一键之后。
    setTimeout(() => pick(target, first.med, wrap, first.row), 0);
  }
  return wrap;
}

function pick(target, med, host, row) {
  for (const old of host.querySelectorAll('.cmd')) old.remove();
  const line = '补天 ' + target.kind + ' ' + target.realm + ' ' + med.id;
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
  if (row && row.parentNode === host) row.after(box);
  else host.append(box);
}

$('refresh').onclick = () => load($('scope').value);
const FROM_URL = new URLSearchParams(location.search).get('scope');
load(FROM_URL || localStorage.getItem(REMEMBER) || '');
