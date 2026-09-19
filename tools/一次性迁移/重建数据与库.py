"""从**原文基线**重建 `data/` 与模板库（**唯一的正确顺序**）。

## 原文基线是哪个提交

管线里有**无幂等步骤**（`缩放治愈数值.py` 会把治愈 / 护盾数值一直乘下去），它靠
「每次从原文重跑，所以只执行一次」成立。所以恢复点钉在标签 **`原文基线`** 上（第 69 轮的
平铺布局那份提交），而不是 `HEAD`——第 82 轮之后 `HEAD` 是**派生出来的**状态，
按 `HEAD` 恢复会把无幂等的那一步做第二遍。

## 顺序为什么不能变

    ① 规范化数据（按「一个结算点只算一次」折叠）
    ② 从**原文形态**的数据挖库
    ③ 把原文换成引用

挖库的输入必须是原文：数据一旦被引用化，收集器认不出引用节点（它们没有 `能力` 键），
只会挖出残片——实测在引用形态的仓库上只挖到 38 个簇（库里应有 1,300+ 份模板），
**并且会把整个库覆盖成这 38 份**。这一条踩过两次。

规范化的输入也必须是原文：只折「能换成引用」的候选项会漏掉裸项里的重复（实测漏 1 处）。

用法：

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/重建数据与库.py
"""

from __future__ import annotations

import importlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import 构筑模板 as 模板  # noqa: E402
from game.core.combat.template_data import library  # noqa: E402

#: 原文基线：**模板化之前**的那份提交（第 69 轮，平铺布局）。
#:
#: 为什么钉在标签上而不是 `HEAD`：管线里有**无幂等步骤**——`缩放治愈数值.py` 会把治愈 /
#: 护盾数值一直乘 0.25 下去，它靠「每次从原文重跑，所以只执行一次」成立。第 82 轮把派生
#: 出来的状态提交成了新基线之后，`HEAD` 已经是缩过的数据，再按 `HEAD` 恢复就会**缩第二遍**。
#: 恢复点因此固定在标签上，`HEAD` 可以随便往前走。
原文基线 = "原文基线"

#: 要恢复成「纯原文」的六个面。**写的是原文基线里的旧路径**（那时还是平铺布局）：
#: `git checkout <标签> -- <路径>` 只能按那份提交里的样子取；取回来立刻由 `按大类归位()`
#: 搬进七大类，往后每一步都按新路径走。
旧面 = (
    "data/战斗/内容/功法",
    "data/战斗/内容/真意",
    "data/炼器/内容",
    "data/战斗/内容/战场环境",
    "data/角色/内容",
    "data/炼丹/内容/丹药/战丹",
    # 丹方要并进丹药（第 76 轮）：原文基线里还有丹方，取回来再让下面那一步并掉。
    "data/炼丹/内容/丹方",
)
#: 归位之后这批面的位置。除「从提交恢复」之外的每一步都按这个走。
面 = (
    "data/战斗/内容/功法",
    "data/战斗/内容/真意",
    "data/物品/炼器/内容",
    "data/战斗/内容/战场环境",
    "data/角色/内容",
    "data/物品/炼丹/内容/丹药/战丹",
    "data/物品/炼丹/内容/丹方",
)
模板文件 = ROOT / "game/core/combat/template_data.py"


def main() -> int:
    备份()
    从提交恢复()
    按大类归位()
    展开成原文()
    合并丹方()
    卡名去重()
    清旧能力名()
    去尝试执行重复()
    重设计悬空引用()
    挪监听入被动()
    拆被动()
    能力名去重()
    规范化()
    缩放治愈数值()
    # 缩放改的是数值：原本不一样的两笔可能因此变得一字不差（实测 6 处），
    # 所以折完再缩之后要**再折一遍**——规范化是幂等的。
    规范化()
    建库()
    迁移()
    汇报()
    return 0


def 备份() -> None:
    if 模板文件.exists():
        # 临时目录用 `tempfile.gettempdir()`：写死 `C:\Users\<谁>\AppData\...` 换台机器就没有。
        shutil.copyfile(模板文件, pathlib.Path(tempfile.gettempdir()) / "构筑模板_备份.py")
        print(f"已备份当前库到 {pathlib.Path(tempfile.gettempdir()) / '构筑模板_备份.py'}")


def 从提交恢复() -> None:
    for path in 旧面:
        subprocess.run(
            ["git", "-C", str(ROOT), "checkout", 原文基线, "--", path], check=True
        )
    print(f"已从「{原文基线}」恢复六个面（纯原文）")


def 按大类归位() -> None:
    """把 29 个平铺组件收进七大类（方法与实体各归其位）。

    必须紧跟在「从提交恢复」之后：恢复出来的是提交里的平铺布局，后面每一步都按
    `物品/炼丹/…`、`世界/位置/…` 这批新路径走。幂等——已经在目标位置时什么都不做。
    """

    工具 = importlib.import_module("按大类归位")
    _调用(工具, "按大类归位.py", ["--落盘"])


def 合并丹方() -> None:
    """把丹方并进丹药（方法与实体合在一处，照炼器的写法）。

    排在「展开成原文」之后：它只是普通内容改写，与模板无关；排在「建库」之前就行。
    """

    工具 = importlib.import_module("合并丹方")
    _调用(工具, "合并丹方.py", ["--落盘"])


def 卡名去重() -> None:
    """卡名全库唯一：三处撞车的各给一个贴合环境的新名字。

    排在「展开成原文」之后、「能力名去重」之前：它改的是卡的 `名称` 与跟着派生的
    能力名前缀，往后那一步还能在这之上继续判能力名有没有撞。
    """

    工具 = importlib.import_module("卡名去重")
    _调用(工具, "卡名去重.py", ["--落盘"])


def 展开成原文() -> None:
    """数据里若已含引用，先用**当前库**展开成原文。"""

    from game.core.combat import templates as 引擎

    需要 = False
    for path in 面:
        for p in (ROOT / path).rglob("*.json"):
            if '"模板"' in p.read_text(encoding="utf-8"):
                需要 = True
                break
        if 需要:
            break
    if not 需要:
        print("数据已是纯原文，无需展开")
        return
    库 = library()
    for 面名, 配置 in 模板.SEGMENTS.items():
        for path in sorted(配置["目录"].glob(配置["模式"])):
            文档 = json.loads(path.read_text(encoding="utf-8"))
            for 实体 in (文档 if isinstance(文档, list) else [文档]):
                if isinstance(实体, dict):
                    引擎.expand_in_place(实体, 库)
            path.write_text(
                json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    print("已展开成原文")


def 规范化() -> None:
    工具 = importlib.import_module("规范化数据")
    _调用(工具, "规范化数据.py", ["--落盘"])


def 去尝试执行重复() -> None:
    """去掉「尝试执行」里与成功/失败分支逐字相同的那一步。

    排在「规范化」之前：规范化随后还能把因此新挨到一起的重复折掉。
    排在「建库」之前：库从数据挖出来，先改数据，模板主体自然是改过的。
    """

    工具 = importlib.import_module("去尝试执行重复")
    _调用(工具, "去尝试执行重复.py", ["--落盘"])


def 重设计悬空引用() -> None:
    """把「读了却没人积累」的引用重设计成会生效的（死计量拆掉、事实补记录）。

    排在「去尝试执行重复」之后：那一步先去掉重复，这一步再重设计剩下的死块。
    排在「规范化」之前：规范化随后会把因此新挨到一起的重复折掉。
    """

    工具 = importlib.import_module("重设计悬空引用")
    _调用(工具, "重设计悬空引用.py", ["--落盘"])


def 挪监听入被动() -> None:
    """把挂错槽位的监听挪进被动技能（400397 那一处）。

    排在「拆被动」之前：它挪完可能让某个被动一时挂着两条，紧接着的拆分会把它们各归一位。
    """

    工具 = importlib.import_module("挪监听入被动")
    _调用(工具, "挪监听入被动.py", [])


def 拆被动() -> None:
    """一个被动只留一条监听，各给各的名字。

    排在「重设计悬空引用」之后：那一步会往被动里补记录用的监听，先拆会被它再拼回去。
    """

    工具 = importlib.import_module("拆被动")
    _调用(工具, "拆被动.py", ["--落盘"])


def 能力名去重() -> None:
    """能力短名全库唯一：撞名的补这张卡自己的身份词前缀。

    排在「拆被动」之后：拆分会产生新的 `（事件简称）` 名字，可能撞上别的卡。
    """

    工具 = importlib.import_module("能力名去重")
    _调用(工具, "能力名去重.py", ["--落盘"])


def 清旧能力名() -> None:
    """把旧能力名（`增加状态层数` 等）从数据里彻底清掉。

    必须排在「建库」之前：模板主体里带着旧名，挖库会把它固化进新库。
    也必须排在「展开」之后：引用节点没有 `能力` 键，藏在未展开引用背后的旧名
    露不出来。本工具内部做定点迭代，直到两件事都不再发生。
    """

    工具 = importlib.import_module("清旧能力名")
    _调用(工具, "清旧能力名.py", ["--落盘"])


def 缩放治愈数值() -> None:
    """把删掉全局「恢复倍率」造成的 4 倍差异，写回每个治愈/护盾数值里。

    排在「建库」之前：库是从数据生成的，缩过数据，模板主体与引用展开结果自然都对。
    排在「规范化」之后：折叠会合并同计量的两笔，先缩再折与先折再缩结果一样（都是
    逐值乘 0.25），但排在后面能少碰被折掉的那些节点。
    """

    工具 = importlib.import_module("缩放治愈数值")
    _调用(工具, "缩放治愈数值.py", ["--落盘"])


def 建库() -> None:
    生成器 = importlib.import_module("构筑模板代码化")
    _调用(生成器, "构筑模板代码化.py", ["--输出", str(模板文件)])


def 迁移() -> None:
    # 库刚被重写，进程里缓存着旧模块；迁移必须看到新的。
    importlib.invalidate_caches()
    for 名 in [k for k in sys.modules if "template_data" in k]:
        del sys.modules[名]
    迁移工具 = importlib.import_module("构筑模板迁移")
    迁移工具._库缓存 = None
    _调用(迁移工具, "构筑模板迁移.py", ["--落盘"])


def _调用(模块, 名字: str, 参数: list[str]) -> None:
    旧 = sys.argv
    sys.argv = [名字, *参数]
    try:
        模块.main()
    finally:
        sys.argv = 旧


def 汇报() -> None:
    importlib.invalidate_caches()
    for 名 in [k for k in sys.modules if "template_data" in k]:
        del sys.modules[名]
    from game.core.combat.template_data import library as 现库

    print(f"库 {len(现库())} 份模板")


if __name__ == "__main__":
    raise SystemExit(main())
