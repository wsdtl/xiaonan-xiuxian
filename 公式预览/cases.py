"""公式能力与真实游戏消息组合的 QQ 客户端测试样板。"""

from urllib.parse import quote


def _command(label: str, command: str, *, submit: bool = True) -> str:
    encoded = quote(command, safe="")
    enter = "true" if submit else "false"
    return f"[{label}](mqqapi://aio/inlinecmd?command={encoded}&enter={enter}&reply=false)"


CASES: tuple[tuple[str, str], ...] = (
    (
        "行内公式边界",
        r"""**行内公式边界**

> 普通文字之前，$\textcolor{#E74C3C}{\text{公式正文}}$，普通文字之后。
> > 同一行连续出现：$\textcolor{#FFD700}{\text{金}}$、$\textcolor{#27AE60}{\text{木}}$、$\textcolor{#2980B9}{\text{水}}$。""",
    ),
    (
        "独立公式",
        r"""**独立公式**

> 行内：天地灵气总量 $Q=\sum_{i=1}^{n} q_i$
> > 独立行：
> > $$\sum_{i=1}^{n} i=\frac{n(n+1)}{2}$$""",
    ),
    (
        "字号层级",
        r"""**字号层级**

> $\Huge{\text{巨}}$ $\huge{\text{极大}}$ $\LARGE{\text{很大}}$ $\Large{\text{大}}$
> > $\large{\text{较大}}$ $\normalsize{\text{正常}}$ $\small{\text{小字说明}}$ $\tiny{\text{极小注记}}$""",
    ),
    (
        "字体族",
        r"""**字体族**

> $\mathbb{QQ\ BOT\ BLACKBOARD\ BOLD}$
> > $\mathfrak{Gothic\ Font\ Test}$
> > $\mathscr{Script\ Font\ Test}$""",
    ),
    (
        "文字色谱",
        r"""**文字色谱**

> $\textcolor{#E74C3C}{\text{赤}}$ $\textcolor{#FF8C00}{\text{橙}}$ $\textcolor{#FFD700}{\text{金}}$ $\textcolor{#27AE60}{\text{翠}}$ $\textcolor{#1ABC9C}{\text{青}}$
> > $\textcolor{#2980B9}{\text{蓝}}$ $\textcolor{#8E44AD}{\text{紫}}$ $\textcolor{#DB7093}{\text{绯}}$ $\textcolor{#F5DEB3}{\text{暖白}}$ $\textcolor{#808080}{\text{灰}}$""",
    ),
    (
        "背景色块",
        r"""**背景色块**

> $\colorbox{#16A085}{\color{white}{\text{生机}}}$ $\colorbox{#3498DB}{\color{white}{\text{灵息}}}$ $\colorbox{#F39C12}{\color{white}{\text{警示}}}$
> > $\colorbox{#9B59B6}{\color{white}{\text{真意}}}$ $\colorbox{#E74C3C}{\color{white}{\text{重伤}}}$ $\colorbox{#2C3E50}{\color{yellow}{\text{天灾}}}$""",
    ),
    (
        "边框高亮",
        r"""**边框高亮**

> $\boxed{\text{休息中}}$ $\boxed{\textcolor{#27AE60}{\text{胜利}}}$ $\boxed{E=mc^2}$
> > $\fcolorbox{#E74C3C}{#FAD7A1}{\color{black}{\text{血量告急}}}$""",
    ),
    (
        "线条装饰",
        r"""**线条装饰**

> $\underline{\text{当前目标}}$ $\utilde{\text{持续影响}}$
> > $\cancel{\text{旧状态}}$ $\xcancel{\text{已经失效}}$""",
    ),
    (
        "上下标注",
        r"""**上下标注**

> $\overset{\text{道侣}}{\text{顾听澜}}$ $\underset{\text{天衡城}}{\text{林远}}$
> > $\underbrace{\text{第一战}\quad\text{第二战}\quad\text{第三战}}_{\text{已解封战报}}$""",
    ),
    (
        "拼音标注",
        r"""**拼音标注**

> $\overset{\text{dào}}{\text{道}}\quad\overset{\text{lǚ}}{\text{侣}}$
> > $\overset{\text{tiān}}{\text{天}}\quad\overset{\text{héng}}{\text{衡}}\quad\overset{\text{chéng}}{\text{城}}$""",
    ),
    (
        "缩放效果",
        r"""**缩放效果**

> $\scalebox{1.2}{\colorbox{#FFD700}{\textcolor{#C0392B}{\text{突破}}}}$ $\scalebox{1.5}{\colorbox{#E74C3C}{\textcolor{white}{\text{重伤}}}}$
> > $\scalebox{1.8}{\colorbox{#8E44AD}{\textcolor{white}{\text{天灾降临}}}}$""",
    ),
    (
        "复杂嵌套",
        r"""**复杂嵌套**

> $\fcolorbox{#E74C3C}{#FFF8DC}{\color{black}{\Large{\text{首领血段二}}}}$
> > $\scalebox{1.3}{\colorbox{#16A085}{\color{white}{\text{灵田成熟，可收取}}}}$""",
    ),
    (
        "进度条语法",
        r"""**进度条语法**

> 色块字符：$\colorbox{#27AE60}{\color{white}{\text{███████}}}\colorbox{#566573}{\color{white}{\text{░░░}}}$ 70%
> > 规则横条：$\textcolor{#27AE60}{\rule{7em}{0.7em}}\textcolor{#566573}{\rule{3em}{0.7em}}$ 70%""",
    ),
    (
        "特殊字符",
        r"""**特殊字符**

> 百分号 $\text{100\%}$ · 下划线 $\text{player\_state}$ · 井号 $\text{\#1}$
> > 花括号 $\text{\{气血\}}$ · 与号 $\text{木\&火}$ · 中文「引号」、顿号、长名称。""",
    ),
    (
        "消息层级",
        r"""**人物创建完成**

> $\colorbox{#27AE60}{\color{white}{\text{创建成功}}}$
> 
> 🧑 人物
> > 姓名：$\Large{\textcolor{#F5DEB3}{\text{林远}}}$
> > 性别：男&nbsp;|&nbsp;境界：灵动&nbsp;|&nbsp;等级：1
> 
> 初始物资已经存入纳戒。""",
    ),
    (
        "人物面板",
        r"""**林远**

> 🧑 修行
> > 灵动境 · 12级&nbsp;|&nbsp;修为 $\textcolor{#FFD700}{\text{8,420 / 12,000}}$
> > 状态 $\boxed{\textcolor{#27AE60}{\text{休息中}}}$ · 所在地 天衡城
> 
> 📖 构筑
> > 功法 2 / 6&nbsp;|&nbsp;真意 1 / 6&nbsp;|&nbsp;气机 1 / 6&nbsp;|&nbsp;灵宝 1 / 1""",
    ),
    (
        "道侣对白",
        r"""**同行道侣**

> $\Large{\textcolor{#DB7093}{\text{顾听澜}}}$ · 灵动境 11级
> > 好感 $\textcolor{#FFD700}{\text{126}}$ · 状态 $\boxed{\text{随行}}$
> 
> $\small{\textcolor{#7FB3D5}{\text{「前方煞气未散，下一场恐怕更凶。」}}}$""",
    ),
    (
        "血气极值",
        r"""**血气极值**

> 满盈　$\colorbox{#27AE60}{\color{white}{\text{██████████}}}$ 1000 / 1000
> > 安稳　$\colorbox{#E74C3C}{\color{white}{\text{███████}}}\colorbox{#566573}{\color{white}{\text{░░░}}}$ 720 / 1000
> > 垂危　$\colorbox{#C0392B}{\color{white}{\text{██}}}\colorbox{#566573}{\color{white}{\text{░░░░░░░░}}}$ 180 / 1000
> > 身死　$\colorbox{#566573}{\color{white}{\text{░░░░░░░░░░}}}$ 0 / 1000""",
    ),
    (
        "多项资源",
        r"""**人物状态**

> 气血　$\colorbox{#E74C3C}{\color{white}{\text{████████}}}\colorbox{#566573}{\color{white}{\text{░░}}}$ 860 / 1000
> > 精神　$\colorbox{#2980B9}{\color{white}{\text{██████}}}\colorbox{#566573}{\color{white}{\text{░░░░}}}$ 62 / 100
> > 修为　$\colorbox{#FFD700}{\color{black}{\text{████}}}\colorbox{#566573}{\color{white}{\text{░░░░░░}}}$ 42%""",
    ),
    (
        "状态语义",
        r"""**状态语义**

> $\colorbox{#27AE60}{\color{white}{\text{可行动}}}$　$\colorbox{#2980B9}{\color{white}{\text{闭关中}}}$　$\colorbox{#F39C12}{\color{white}{\text{等待结算}}}$
> > $\colorbox{#E74C3C}{\color{white}{\text{重伤}}}$　$\colorbox{#8E44AD}{\color{white}{\text{托管中}}}$　$\colorbox{#566573}{\color{white}{\text{已结束}}}$""",
    ),
    (
        "倒计时进度",
        r"""**探险进度**

> 北荒古道 · 第 4 / 15 场
> > 剩余 $\textcolor{#FFD700}{\text{22:18}}$ · 下一场解封 $\textcolor{#1ABC9C}{\text{01:42}}$
> > $\colorbox{#27AE60}{\color{white}{\text{███}}}\colorbox{#566573}{\color{white}{\text{░░░░░░░}}}$ $\textcolor{#27AE60}{\text{27\%}}$""",
    ),
    (
        "五行相性",
        r"""**五行相性**

> $\textcolor{#27AE60}{\text{木 40\%}}$ · $\textcolor{#E74C3C}{\text{火 60\%}}$
> > 克制：$\boxed{\textcolor{#27AE60}{\text{木生火}}}$ · 受制：$\boxed{\textcolor{#2980B9}{\text{水克火}}}$
> > 无相：$\textcolor{#8E44AD}{\text{不入五行}}$""",
    ),
    (
        "修行槽位",
        r"""**修行槽位**

> 功法 $\textcolor{#FFD700}{\text{2 / 6}}$ · 真意 $\textcolor{#8E44AD}{\text{1 / 6}}$ · 气机 $\textcolor{#1ABC9C}{\text{1 / 6}}$
> > ① 九针渡劫济世典 · 02
> > ② 星辰淬骨真身诀 · 01
> > 先天灵宝：$\boxed{\textcolor{#FFD700}{\text{太虚照骨镜}}}$""",
    ),
    (
        "物品详情",
        r"""**小还丹**

> 📦 灵丹 · 黄阶 · 编号 120001
> > 数量 $\textcolor{#FFD700}{\text{×3}}$ · 服用后恢复 $\textcolor{#E74C3C}{\text{20\% 气血}}$
> > 使用范围：人物与同行道侣
> 
> $\tiny{\textcolor{#808080}{\text{存于玩家纳戒，服用后消耗一枚。}}}$""",
    ),
    (
        "功法详情",
        r"""**星辰淬骨真身诀**

> 📖 天品 · 编号 400265 · $\textcolor{#8E44AD}{\text{无相 100\%}}$
> > 主动 · 星辰借法 · $\textcolor{#2980B9}{\text{耗神 18}}$ · 冷却 2 行动
> > 主动 · 星辰易诀 · $\textcolor{#2980B9}{\text{耗神 16}}$ · 冷却 3 行动
> > 被动 · 星辰藏诀 · $\textcolor{#27AE60}{\text{攻击 +12\%}}$
> 
> $\small{\textcolor{#808080}{\text{已学会的功法可以自由更换槽位。}}}$""",
    ),
    (
        "本命武器",
        r"""**本命武器**

> ⚔ 长夜 · 18级
> > 经验 $\textcolor{#FFD700}{\text{7,640 / 9,000}}$
> > $\colorbox{#FFD700}{\color{black}{\text{████████}}}\colorbox{#566573}{\color{white}{\text{░░}}}$ 85%
> > 器律孔：3 / 4 · 已覆炼 破岳、引雷、归锋""",
    ),
    (
        "多单位编组",
        r"""**战斗编组**

> 我方一组
> > 主战：林远　辅助：顾听澜
> > 气血 $\textcolor{#27AE60}{\text{1,600 / 1,900}}$
> 
> 敌方一组
> > 主战：玄魇将　辅助：镇魂使、裂甲卫
> > 气血 $\textcolor{#E74C3C}{\text{8,420 / 12,000}}$""",
    ),
    (
        "战斗过程",
        r"""**讨伐战况**

> 第 7 行动
> > 林远施展星辰借法，对玄魇将造成 $\textcolor{#FFD700}{\text{1,284}}$ 点伤害。
> > 镇魂使施加 $\boxed{\textcolor{#8E44AD}{\text{神魂迟滞 · 2行动}}}$。
> > 顾听澜为林远恢复 $\textcolor{#27AE60}{\text{326}}$ 点气血。
> > 玄魇将进入 $\colorbox{#E74C3C}{\color{white}{\text{第三血段}}}$。""",
    ),
    (
        "冷却与持续",
        r"""**能力状态**

> 星辰借法　$\boxed{\textcolor{#F39C12}{\text{冷却 2 行动}}}$
> > 镇魂迟滞　$\boxed{\textcolor{#8E44AD}{\text{剩余 1 行动}}}$
> > 回元阵势　$\boxed{\textcolor{#27AE60}{\text{本场持续}}}$
> > 九转还魂　$\boxed{\textcolor{#E74C3C}{\text{剩余复活 1 次}}}$""",
    ),
    (
        "结算总览",
        r"""**探险总结**

> 北荒古道 · 15场战斗 · $\boxed{\textcolor{#27AE60}{\text{完成}}}$
> > 存活 5 / 6&nbsp;|&nbsp;击败 31&nbsp;|&nbsp;历时 30:00
> > 本命武器经验 $\textcolor{#FFD700}{\text{+4,280}}$
> > 共同纳戒所得：灵石 $\textcolor{#FFD700}{\text{12,460}}$ · 物品 23 件""",
    ),
    (
        "用户结算页",
        r"""**探险总结 · 林远**

> 人物
> > 最终气血 812 / 1000 · 精神 46 / 100 · 武器经验 $\textcolor{#FFD700}{\text{+2,140}}$
> 
> 道侣 · 顾听澜
> > 最终气血 620 / 900 · 精神 0 / 80 · 武器经验 $\textcolor{#FFD700}{\text{+2,140}}$
> 
> $\tiny{\textcolor{#808080}{\text{同一用户的人物与道侣始终显示在同一页。}}}$""",
    ),
    (
        "位置附近",
        r"""**天衡城 · 东城**

> 📍 坐标 42, 18 · 海拔 236米
> > 同行道侣：$\textcolor{#DB7093}{\text{顾听澜}}$
> > 附近修士：林远、谢千山、沈照微
> > 附近队伍 2支 · 附近宗门同行 1支""",
    ),
    (
        "宗门设施",
        r"""**洞天生产**

> 灵田
> > 本轮产出：灵植 $\textcolor{#27AE60}{\text{×126}}$ · 状态 $\boxed{\text{可收取}}$
> 
> 灵脉
> > 本轮产出：灵矿 $\textcolor{#2980B9}{\text{×84}}$ · 状态 $\boxed{\text{生长中}}$
> > 下次成熟 $\textcolor{#FFD700}{\text{18:42}}$""",
    ),
    (
        "空态与错误",
        r"""**操作结果**

> $\colorbox{#808080}{\color{white}{\text{空}}}$ 纳戒中尚无真意。
> > $\colorbox{#F39C12}{\color{white}{\text{受限}}}$ 当前正在探险，不能开始闭关。
> > $\colorbox{#E74C3C}{\color{white}{\text{失败}}}$ 灵石不足，还差 2,400。
> > $\colorbox{#27AE60}{\color{white}{\text{成功}}}$ 功法槽位已经更换。""",
    ),
    (
        "长名称换行",
        r"""**长文本适配**

> 功法：九转金丹大道篇之太虚玄火归元真解
> > 能力：九转金丹大道篇·九转候敌·焚尽八荒
> > 说明：受到致命伤害时消耗一次复活次数，并以最大气血的百分之三十重新进入战斗；同一来源不能连续触发。
> > $\small{\textcolor{#808080}{\text{此项专门观察窄屏换行、公式与中文长句是否互相遮挡。}}}$""",
    ),
    (
        "列表与分页",
        r"""**纳戒 · 功法 · 第 2 / 4 页**

> ① 星辰淬骨真身诀 · 天品 · ×1
> > ② 九针渡劫济世典 · 地品 · ×2
> > ③ 太素玄元养神篇 · 玄品 · ×1
> > ④ 九转金丹大道篇 · 天品 · ×1
> > ⑤ 长夜渡厄镇魂真解 · 地品 · ×3
> 
> $\tiny{\textcolor{#808080}{\text{每个小类一页最多 50 项。}}}$""",
    ),
    (
        "正文立即命令",
        """**正文无边框命令**

> 点击功法名称直接发送查看命令：
> > """
        + _command(r"$\textcolor{#8E44AD}{\text{星辰淬骨真身诀}}$", "查看 400265")
        + "\n> > 点击后应立即发送 `查看 400265`。",
    ),
    (
        "正文填入命令",
        """**正文无边框填入**

> 点击物品名称只填入命令，等待玩家补充数量：
> > """
        + _command(r"$\textcolor{#27AE60}{\text{小还丹}}$", "服丹 小还丹 ", submit=False)
        + "\n> > 点击后输入框应保留 `服丹 小还丹 `。",
    ),
    (
        "底部按钮类型",
        r"""**底部按钮类型**

> 本项测试回调、立即发送和填入三种 keyboard 行为。
> > 三个按钮应在同一行，点击结果互不相同。""",
    ),
    (
        "底部多行按钮",
        r"""**底部多行按钮**

> 本项测试 5 个按钮自动分成两行。
> > 第一行 3 个，第二行 2 个，随后另起一行显示预览导航。""",
    ),
    (
        "正文与底部联动",
        """**功法详情与操作**

> 正文中的 """
        + _command(r"$\textcolor{#8E44AD}{\text{星辰淬骨真身诀}}$", "查看 400265")
        + """ 用于查看；底部只提供装配和返回。
> > 同一条命令不能同时出现在正文和底部。""",
    ),
    (
        "混合压力样板",
        r"""$\textcolor{#FFD700}{\Huge{\text{讨伐告捷}}}$

> $\fcolorbox{#E74C3C}{#FFF8DC}{\color{black}{\text{朔关玄魇 · 霍沉戈 · 第三血段}}}$
> > 首领气血 $\colorbox{#566573}{\color{white}{\text{░░░░░░░░░░}}}$ $\textcolor{#27AE60}{\text{0 / 36,000}}$
> > 林远气血 $\colorbox{#E74C3C}{\color{white}{\text{██████}}}\colorbox{#566573}{\color{white}{\text{░░░░}}}$ 612 / 1000
> > 顾听澜气血 $\colorbox{#E74C3C}{\color{white}{\text{████████}}}\colorbox{#566573}{\color{white}{\text{░░}}}$ 741 / 900
> 
> 战果
> > 本命武器经验 $\textcolor{#FFD700}{\text{+3,860}}$ · 灵石 $\textcolor{#FFD700}{\text{+12,000}}$
> > 天灾遗物：$\boxed{\textcolor{#8E44AD}{\text{玄魇镇魂骨}}}$ ×1
> > 长期伤势：$\boxed{\textcolor{#E74C3C}{\text{神识裂隙}}}$
> 
> $\tiny{\textcolor{#808080}{\text{此项同时验证大标题、边框、色块、血条、长数字、分页提示和底部交互。}}}$""",
    ),
)


GROUPS: tuple[tuple[str, int, int], ...] = (
    ("公式原子能力", 1, 14),
    ("游戏消息组合", 15, 36),
    ("正文与按钮", 37, 42),
)


SPECIAL_BUTTONS: dict[int, tuple[tuple[str, str, str, str, int], ...]] = {
    39: (
        ("callback", "回调", "公式预览 1", "callback", 1),
        ("send", "发送", "公式预览 2", "send", 1),
        ("fill", "填入", "公式预览 ", "fill", 0),
    ),
    40: (
        ("one", "打开链接", "https://frp.dengxiaonan.cn:8080/docs", "link", 1),
        ("two", "道侣", "公式预览 17", "send", 0),
        ("three", "战斗", "公式预览 27", "send", 0),
        ("four", "结算", "公式预览 29", "send", 0),
        ("five", "返回目录", "公式预览", "send", 0),
    ),
    41: (
        ("equip", "装配", "装配功法 400265", "callback", 1),
        ("back", "返回纳戒", "纳戒 功法", "callback", 0),
    ),
}
