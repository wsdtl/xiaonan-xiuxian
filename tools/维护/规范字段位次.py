# -*- coding: utf-8 -*-
"""把 data/ 下所有 JSON 对象按统一字段位次重排。

规则：
  1. 编号记录：编号 -> 名称 -> 说明 -> 分类/引用 -> 规则/数值 -> 展示。
  2. 能力节点：能力 -> 名称 -> 说明 -> 范围/目标 -> 状态/资源/属性 -> 条件/效果 -> 数值。
  3. schema：说明 -> 字段 -> 约束。
  4. 以名字为键的纯映射保留原顺序；只重排对象字段，不重排数组。
  5. 已登记字段按语义组排；未登记字段统一按 Unicode 码位接在末尾。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

# 字段位次：数字只在同一组内比较；未登记字段排到组后，按码位排序。
RANK: dict[str, int] = {}
for index, key in enumerate((
    "编号", "名称", "说明",
    "前缀", "主体",
    "类别", "来源类别", "类型", "分类", "定位",
    "品级", "器阶", "阶", "阶序", "阶段", "境界", "书脉", "流派",
    "种族", "性别", "身份", "角色类型", "关系", "立场", "归属",
    "码", "权柄", "地形", "事件标签",
    "匹配状态", "匹配优先级", "触发优先级", "优先级",
    "结算顺序", "释放顺序", "获得顺序", "排序", "顺序",
    "等级", "等级下限", "等级上限", "寿元", "寿元系数",
    "下一境界", "目标境界", "最低品级", "最低值", "最高值",
    "最小", "最大", "下限", "上限", "数量", "次数", "权重",
    "参考价", "基准当量", "倍率", "系数", "比例", "概率", "百分比",
    "数值", "金额", "消耗", "冷却", "冷却行动", "剩余行动",
    "持续", "持续单位", "每层所需轮数", "每场战斗最多触发",
    "每次行动最多触发", "每条根链最多触发", "自身行动间隔最多触发",
    "能力", "范围", "目标", "选择全部", "状态", "资源", "属性",
    "属性构成", "属性覆盖", "效果", "条件", "事件", "观察角色",
    "阵营关系", "来源", "来源目标", "来源资源", "接收目标", "接收资源",
    "方式", "左值", "右值", "比较", "口径", "单位", "执行器",
    "监听", "监听事件", "触发", "匹配", "战斗状态", "战前状态",
    "叠加", "治疗", "层数", "层数上限", "重复方式", "材料", "掉落",
    "使用效果", "常驻能力", "入阶能力", "基础", "阵核", "检测",
    "宏观监测", "阵法核心", "冲击", "传导", "节点", "起点", "终点",
    "途经坐标", "坐标", "坐标带", "可用功能", "功能配置", "功能",
    "要求", "名额", "可交互", "携带事实", "可修改", "规则介入",
    "是否控制", "能否暴击", "能否格挡", "不足时是否失败", "处置",
    "拦截点", "x轴", "y", "命令",
    "标题", "页面", "样式", "显示", "格式", "按钮", "文本", "错误",
    "提示", "说明规则", "分页", "分类顺序", "品级顺序", "页码",
    "提示语", "旁白", "文案",
    "组件", "读取规则", "数据集", "路径", "结构", "实体类别",
    "编号类别", "目录池", "编号定义", "文件名唯一", "资源池字段",
    "归属规则", "扫描目录", "归属目录层级", "编号前缀",
    "字段", "约束", "必填", "默认", "选项", "最少项", "最多项",
    "唯一", "允许空", "当", "存在", "字段名", "值",
)):
    RANK.setdefault(key, index)

RECORD_PREFIX = ("编号", "名称", "说明")
ABILITY_PREFIX = ("能力",)
SCHEMA_PREFIX = ("说明", "字段", "约束")
PREFIX_PREFIX = ("前缀", "主体", "类别")


def _rank(key: str) -> tuple[int, int, str]:
    if key in RANK:
        return (0, RANK[key], key)
    return (1, 0, key)


def _ordered_keys(obj: dict[str, object]) -> list[str]:
    keys = list(obj)
    if "编号" in obj:
        prefix = [key for key in RECORD_PREFIX if key in obj]
    elif "能力" in obj:
        prefix = [key for key in ABILITY_PREFIX if key in obj]
    elif "字段" in obj or "约束" in obj:
        prefix = [key for key in SCHEMA_PREFIX if key in obj]
    elif "前缀" in obj:
        prefix = [key for key in PREFIX_PREFIX if key in obj]
    else:
        prefix = []
    chosen = set(prefix)
    rest = [key for key in keys if key not in chosen]
    return prefix + sorted(rest, key=_rank)


def reorder(node: object) -> object:
    if isinstance(node, dict):
        if not any(key in RANK for key in node):
            # 纯名字映射：键的顺序就是内容顺序，保留；值仍递归整理。
            return {key: reorder(value) for key, value in node.items()}
        return {key: reorder(node[key]) for key in _ordered_keys(node)}
    if isinstance(node, list):
        return [reorder(value) for value in node]
    return node


def load(path: pathlib.Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: pathlib.Path, value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))


def numbered_position_errors(value: object) -> int:
    errors = 0
    if isinstance(value, dict):
        if "编号" in value and next(iter(value)) != "编号":
            errors += 1
        for child in value.values():
            errors += numbered_position_errors(child)
    elif isinstance(value, list):
        for child in value:
            errors += numbered_position_errors(child)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--root", default="data")
    args = parser.parse_args()
    root = pathlib.Path(args.root)
    files = sorted(root.rglob("*.json"))
    changed_files = 0
    errors_before = 0
    errors_after = 0
    for path in files:
        before = load(path)
        after = reorder(before)
        if before != after:
            print("VALUE CHANGED", path)
            return 1
        errors_before += numbered_position_errors(before)
        errors_after += numbered_position_errors(after)
        if json.dumps(before, ensure_ascii=False, separators=(",", ":")) != json.dumps(after, ensure_ascii=False, separators=(",", ":")):
            changed_files += 1
            if args.write:
                dump(path, after)
    if args.write:
        # 写完后再读回，确认文件仍可解析，且编号都在第一。
        errors_after = 0
        for path in files:
            errors_after += numbered_position_errors(load(path))
    print("files", len(files), "changed", changed_files, "numbered-not-first-before", errors_before, "after", errors_after)
    return 0


if __name__ == "__main__":
    sys.exit(main())
