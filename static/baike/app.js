"use strict";

const 前缀表 = document.getElementById("prefixes");
const 条目表 = document.getElementById("entries");
const 状态 = document.getElementById("status");
const 搜索框 = document.getElementById("query");

async function 取数据(参数) {
  const response = await fetch("/baike/data" + (参数 || ""));
  if (!response.ok) throw new Error("取数失败：" + response.status);
  return response.json();
}

function 建行(左, 右) {
  const item = document.createElement("li");
  item.className = "entry";
  const 编号 = document.createElement("span");
  编号.className = "code";
  编号.textContent = 左;
  const 名称 = document.createElement("span");
  名称.className = "name";
  名称.textContent = 右;
  item.append(编号, 名称);
  return item;
}

function 画条目(条目) {
  条目表.replaceChildren();
  状态.textContent = 条目.length ? "共 " + 条目.length + " 条" : "没有条目";
  const 片段 = document.createDocumentFragment();
  for (const row of 条目) 片段.append(建行(row["编号"], row["名称"]));
  条目表.append(片段);
}

function 画前缀(表) {
  前缀表.replaceChildren();
  const 片段 = document.createDocumentFragment();
  for (const row of 表) {
    const item = document.createElement("li");
    item.className = "prefix";
    const link = document.createElement("button");
    link.className = "prefix-button";
    link.type = "button";
    link.textContent = row["前缀"] + " " + row["类别"];
    const 计数 = document.createElement("span");
    计数.className = "count";
    计数.textContent = row["条数"] + " 条";
    link.append(计数);
    link.addEventListener("click", async () => {
      状态.textContent = "正在载入…";
      画条目((await 取数据("?prefix=" + row["前缀"])).条目);
    });
    item.append(link);
    片段.append(item);
  }
  前缀表.append(片段);
}

async function 检索(词) {
  状态.textContent = "正在载入…";
  try {
    画条目((await 取数据("?q=" + encodeURIComponent(词))).条目);
  } catch (error) {
    状态.textContent = String(error.message || error);
  }
}

async function 看前缀(前缀) {
  状态.textContent = "正在载入…";
  try {
    画条目((await 取数据("?prefix=" + encodeURIComponent(前缀))).条目);
  } catch (error) {
    状态.textContent = String(error.message || error);
  }
}

async function 启动() {
  try {
    const 总表 = await 取数据();
    画前缀(总表.前缀表);
    // 深链接：/baike?q=550001 或 /baike?prefix=55 —— 从「查看」回复点进来时用得上。
    const 参数 = new URLSearchParams(location.search);
    const 词 = (参数.get("q") || "").trim();
    const 前缀 = (参数.get("prefix") || "").trim();
    if (词) {
      搜索框.value = 词;
      await 检索(词);
      return;
    }
    if (前缀) {
      await 看前缀(前缀);
      return;
    }
    状态.textContent = "选一个前缀，或直接搜编号与名称";
  } catch (error) {
    状态.textContent = String(error.message || error);
  }
}

搜索框.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") return;
  const 词 = 搜索框.value.trim();
  if (!词) return;
  状态.textContent = "正在载入…";
  try {
    画条目((await 取数据("?q=" + encodeURIComponent(词))).条目);
  } catch (error) {
    状态.textContent = String(error.message || error);
  }
});

启动();
