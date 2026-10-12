'use strict';
const $ = (id) => document.getElementById(id);
let UI = {};
let ITEMS = [];
let CATEGORY = '真意';
let PAGE = 1;
const REMEMBER = 'jiaoyi.scope';

function say(text) { $('status').textContent = text || ''; }

function pick(row, keys) {
  for (const key of keys) {
    if (row && row[key] !== undefined && row[key] !== null && row[key] !== '') return String(row[key]);
  }
  return '';
}

function commandBox(line) {
  const box = document.createElement('div');
  box.className = 'cmd';
  // 这一句是后端下发的说明（「把这条发进聊天即可」）：页面不自己凑。
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

function show(line) {
  const host = $('command');
  host.innerHTML = '';
  if (line) host.append(commandBox(line));
}

async function load(scope, category, page) {
  if (category) CATEGORY = category;
  if (page) PAGE = page;
  say('读取中…');
  const params = new URLSearchParams({ category: CATEGORY, page: String(PAGE) });
  if (scope) params.set('scope', scope);
  let data;
  try { data = await (await fetch('/jiaoyi/data?' + params)).json(); } catch (error) { say('读不到数据：' + error); return; }
  if (data.error) { say(data.error); return; }
  UI = data.ui || {};
  // 后端 `TradePage` 的商品在 `products`：以前读 `entries/items`，货架永远是空的。
  ITEMS = (data.page && data.page.products) || [];
  $('title').textContent = UI['标题'] || '货架';
  $('intro').textContent = UI['说明'] || '';
  $('label-shelf').textContent = UI['货架'] || '货架';
  // 挑人、类别两处文案后端一直有发（ui['挑人'] / ui['类别']），以前页面写死没用。
  $('label-scope').textContent = UI['挑人'] || '挑自己';
  $('tabs-label').textContent = UI['类别'] || '';
  const overview = data.overview || {};
  const money = overview.spirit_stones;
  const summary = [];
  if (overview.location_name) summary.push(String(overview.location_name));
  if (money !== undefined && money !== null) summary.push((UI['货币'] || '') + ' ' + money);
  $('overview').textContent = summary.join(' · ');
  $('overview').hidden = !summary.length;
  $('prev').textContent = UI['上一页'] || '上一页';
  $('next').textContent = UI['下一页'] || '下一页';
  const sheet = data.page || {};
  const totalPages = Number(sheet.total_pages) || 1;
  PAGE = Number(sheet.page) || PAGE;
  $('pager').textContent = (UI['页码'] || '页码') + ' ' + PAGE + ' / ' + totalPages;
  $('prev').disabled = PAGE <= 1;
  $('next').disabled = PAGE >= totalPages;
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
  const tabs = $('tabs');
  tabs.innerHTML = '';
  for (const name of data.categories || []) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tab' + (name === CATEGORY ? ' on' : '');
    button.textContent = name;
    button.onclick = () => load(select.value, name, 1);
    tabs.append(button);
  }
  if (!scopes.length) { $('notice').textContent = UI['没人公开'] || ''; $('shelf').innerHTML = ''; show(''); say(''); return; }
  $('notice').textContent = data.notice || '';
  renderShelf();
  say('');
}

function renderShelf() {
  const host = $('shelf');
  host.innerHTML = '';
  if (!ITEMS.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = UI['空'] || '';
    host.append(empty);
    show('');
    return;
  }
  for (const row of ITEMS) {
    const id = pick(row, ['编号', 'content_id', 'id', 'item_id']);
    const gradeId = pick(row, ['grade_id', '品级', 'grade', '品级编号']);
    const grade = pick(row, ['grade_name', '品级名']) || gradeId;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'item';
    const name = document.createElement('span');
    name.className = 'item-name';
    name.textContent = pick(row, ['名称', 'name', 'content_name']) || id;
    const meta = document.createElement('span');
    meta.className = 'item-meta';
    const price = pick(row, ['unit_price', '价格', 'price', '售价', '单价']);
    meta.textContent = [id, grade && ('品级 ' + grade), price && ('价 ' + price)].filter(Boolean).join(' · ');
    button.append(name, meta);
    button.onclick = () => show('购买 ' + id + (gradeId ? ' ' + gradeId : ''));
    host.append(button);
  }
  const first = ITEMS[0];
  const id = pick(first, ['编号', 'content_id', 'id', 'item_id']);
  const grade = pick(first, ['品级', 'grade', 'grade_id', '品级编号']);
  show('购买 ' + id + (grade ? ' ' + grade : ''));
}

$('refresh').onclick = () => load($('scope').value);
$('prev').onclick = () => load($('scope').value, CATEGORY, Math.max(1, PAGE - 1));
$('next').onclick = () => load($('scope').value, CATEGORY, PAGE + 1);
const FROM_URL = new URLSearchParams(location.search).get('scope');
load(FROM_URL || localStorage.getItem(REMEMBER) || '');
