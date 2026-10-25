'use strict';
const $ = (id) => document.getElementById(id);
let UI = {};
const REMEMBER = 'yijing.scope';

function say(text) { $('status').textContent = text || ''; }

async function copyText(text, node, done) {
  try {
    await navigator.clipboard.writeText(text);
    node.textContent = done;
  } catch (error) {
    say('复制失败，请手动抄这条命令：' + text);
  }
}

function commandButton(label, command, done) {
  const node = document.createElement('button');
  node.type = 'button';
  node.className = 'copy';
  node.textContent = label;
  node.onclick = () => copyText(command, node, done);
  return node;
}

async function load(scope) {
  say('读取中…');
  const url = '/yijing/data' + (scope ? '?scope=' + encodeURIComponent(scope) : '');
  let data;
  try {
    const res = await fetch(url);
    data = await res.json();
  } catch (error) {
    say('读不到数据：' + error);
    return;
  }
  if (data.error) { $('routes').innerHTML = ''; say(data.error); return; }
  UI = data.ui || {};
  $('title').textContent = UI['标题'] || '意境 · 六路';
  $('intro').textContent = UI['说明'] || '';
  $('label-scope').textContent = UI['挑人'] || '挑自己';
  renderScopes(data);
  if (!(data.scopes || []).length) {
    $('routes').innerHTML = '';
    $('totals').textContent = '';
    say('');
    $('hint').textContent = UI['没人公开'] || '';
    return;
  }
  $('hint').textContent = UI['命令'] || '';
  say('');
  renderTotals(data);
  renderRoutes(data.routes || [], data.cap || 0);
  renderRetreat();
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

function renderTotals(data) {
  $('totals').textContent = (UI['道行'] || '道行') + ' ' + (data.points || 0) +
    ' · ' + (UI['阶上限'] || '当前境界可点到') + ' ' + (data.cap || 0) + ' 阶';
}

function stateText(route, cap) {
  if (!route.tier) return UI['未点'] || '未点';
  if (route.tier >= 9) return UI['已满'] || '已满九阶';
  if (route.tier >= cap) return UI['到上限'] || '到境界上限';
  return route.tier + ' 阶';
}

function renderRoutes(routes, cap) {
  const host = $('routes');
  host.innerHTML = '';
  if (!routes.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = UI['没人公开'] || '';
    host.append(empty);
    return;
  }
  for (const route of routes) {
    const box = document.createElement('article');
    box.className = 'target';
    const head = document.createElement('div');
    head.className = 'target-head';
    const who = document.createElement('h2');
    who.textContent = route.name || route.id;
    const tier = document.createElement('p');
    tier.className = 'tier';
    tier.textContent = stateText(route, cap);
    head.append(who, tier);
    box.append(head);
    if (route.next_cost) {
      const cost = document.createElement('p');
      cost.className = 'state yes';
      cost.textContent = (UI['下一阶'] || '下一阶') + ' ' + route.next_cost + ' 道行' +
        (route.missing ? '（' + (UI['还差'] || '还差') + ' ' + route.missing + '）' : '');
      box.append(cost);
    }
    box.append(commandButton(UI['点这一路'] || '复制点阶命令', '意境 点 ' + (route.name || route.id), '已复制，发到群里'));
    host.append(box);
  }
}

function renderRetreat() {
  const box = $('retreat');
  $('retreat-text').textContent = UI['退点'] || '';
  const label = UI['退点命令'] || '坐忘';
  $('retreat-copy').innerHTML = '';
  $('retreat-copy').append(commandButton(UI['复制退点'] || '复制坐忘命令', label, '已复制，发到群里'));
  box.hidden = false;
}

$('refresh').onclick = () => load($('scope').value || localStorage.getItem(REMEMBER) || '');
load(localStorage.getItem(REMEMBER) || '');