'use strict';
const $ = (id) => document.getElementById(id);
let UI = {};
let SCOPE = '';
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

async function load(scope) {
  say('读取中…');
  const url = '/lianzhen/data' + (scope ? '?scope=' + encodeURIComponent(scope) : '');
  let data;
  try { data = await (await fetch(url)).json(); } catch (error) { say('读不到数据：' + error); return; }
  if (data.error) { say(data.error); return; }
  UI = data.ui || {};
  $('title').textContent = UI['标题'] || '演阵台';
  $('intro').textContent = UI['说明'] || '';
  $('label-formation').textContent = UI['阵法'] || '阵法';
  $('label-grade').textContent = UI['品级'] || '品级';
  $('label-triple').textContent = UI['三相'] || '';
  $('calc').textContent = UI['算一算'] || '算一算';
  fill($('scope'), data.scopes || []);
  $('scope').disabled = !(data.scopes || []).length;
  if (data.scope) { $('scope').value = data.scope; SCOPE = data.scope; }
  $('scope').onchange = () => { localStorage.setItem(REMEMBER, $('scope').value); SCOPE = $('scope').value; load(SCOPE); };
  if (!(data.scopes || []).length) { $('notice').textContent = UI['没人公开'] || ''; say(''); return; }
  fill($('formation'), data.formations || []);
  fill($('grade'), (data.grades || []).map((g) => ({ id: g, name: g })));
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

function render(data) {
  const host = $('result');
  host.innerHTML = '';
  if (data.error) { addText(host, 'reason', data.error); return; }
  if (data.notice) { addText(host, 'reason', data.notice); }
  if (data.preview) {
    const pre = document.createElement('pre');
    pre.className = 'preview';
    pre.textContent = JSON.stringify(data.preview, null, 2);
    host.append(pre);
  }
  const line = ['演阵台', '炼阵', $('formation').value, $('grade').value, $('shoubao').value || '0', $('lingkuang').value || '0', $('lingzhi').value || '0'].join(' ');
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

function addText(host, className, text) {
  const line = document.createElement('p');
  line.className = className;
  line.textContent = text;
  host.append(line);
}

$('calc').onclick = calc;
$('refresh').onclick = () => load($('scope').value);
const FROM_URL = new URLSearchParams(location.search).get('scope');
load(FROM_URL || localStorage.getItem(REMEMBER) || '');
