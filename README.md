# 晓楠修仙

数据分两层：`data/<大类>/<组件>/{定义,规则,内容,展示}`，组件名与大类同名时不再多一层。每个组件有独立 `组件.json`，全局入口是 `data/基础/读取规则.json`，归属与布局见 [data/说明.md](data/说明.md)。旧四个顶层目录已移除。

当前仓库已经完成基础玩法与宗门玩法的第一轮闭环，正在补齐可长期复用的公共地基。正式 JSON 是规则与内容的唯一主体；Python 负责严格读取、公共核心、玩法编排、命令接入和结果展示，不保留旧实现兼容层。

## 当前保留范围

```text
data/                       正式定义、规则、内容与展示 JSON（7 大类、29 个组件包）
database/                   游戏数据库与运行日志数据库，不进入版本库
.runtime/                   历史备份与控制台媒体，不进入版本库
game/core/                  38 个跨玩法公共微服务，按包注入（见 系统架构.md）
game/features/              39 个具体玩法微服务，不依赖命令协议
game/cmd/                   40 个二级命令组件（通用 22、专属 17、后台 1）
game/startup/               跨命令、跨核心服务的启动契约
game/config.py              从框架自定义项中解释游戏配置
game/app.py                 游戏微服务的唯一组合根
launch/                     Local、QQ、HTTP 与生命周期适配
launch/adapter/local/       本地驱动器：天道后台与托管借它派发正式命令
launch/adapter/qq_wh/      QQ 开放平台回调驱动器（HTTP 路由与验签）
launch/adapter/qq_ws/      QQ 网关 WebSocket 驱动器（opcode、心跳、重连、关闭码）
launch/adapter/qq_protocol/ QQ 协议层：命令表、事件解析、去重队列与回复链路
launch/adapter/websocket.py 与平台无关的 RFC6455 客户端
message/                    通用消息协议
static/game-console/        控制台前端
static/battle-report/       战报前端
static/world-map/           全境地势、南北地界、道路与地点地图
static/说明.md              前端约定：页面归属、缓存与版本、页面策略、样式与信任边界
tools/                      游戏外校核、维护脚本、迁移清单与归档验证件
tools/公式预览/              已归档的 QQ 消息协议兼容性验证组件（默认不装载）
```

当前实测规模：正式 JSON **1750 文档、3932 实体、1360 资源池**；启动后注册 **152 条命令、10 条守卫规则**。

天道后台和公开地图是两个独立二级组件：前者只服务开发者管理台，后者通过 `game/features/ditu` 取得 `game/core/world` 提供的只读地图快照与文字概况。`game/core` 放跨玩法公共微服务，`game/features` 放具体玩法微服务，`game/cmd` 只负责命令、按钮和 HTTP 触发，`game/app.py` 是唯一组合根。角色、资产、成长、世界、位置、队伍、道侣、战斗、人物培养、道侣培养、探险、闭关、采集、炼器、炼丹、阵法、交易、服丹、赠送、切磋、讨伐、托管、先天灵宝、归元、补天、易形、铜雀台、修为转移及宗门分支业务均已有正式核心服务；完整清单与装配顺序见 [系统架构.md](系统架构.md)。新增玩法继续按同一 JSON 契约扩展。

`launch/config.py` 只解释框架自身的项目、监听、日志和路由配置。数据库、控制台凭据及其他业务环境变量必须进入 `config.custom`；游戏侧需要类型转换或校验时统一在 `game/config.py` 完成，不得向框架 `Config` 增加业务字段。

## JSON 驱动边界

- `data/<大类>/<组件>/定义` 声明底层概念、字段和编号规则（组件名与大类同名时省略组件那一段）。
- `data/<大类>/<组件>/规则` 声明运行规则和结算顺序。
- `data/<大类>/<组件>/内容` 保存可引用的正式实体与资源池。
- `data/<大类>/<组件>/展示` 保存战报等展示契约。
- `data/基础/读取规则.json` 声明每个组件的相对路径、正式文件属于哪个数据集、采用哪种结构以及建立哪类索引。
- `data` 不保存数据库、备份或运行媒体；数据库进入 `database`，备份和控制台媒体进入 `.runtime`。
- Python 只固定读取这一份引导文件，不硬编码功法、气机、道路等业务目录；其他微服务按数据集、实体类别或资源池取得数据。
- JSON 读取是 `core` 的第一个微服务；后续 `features` 微服务由 `game/app.py` 注入所需核心服务，`cmd` 只触发对应玩法服务。
- 所有代码级微服务使用包顶层公共契约，禁止跨目录导入内部引擎、运行模型或加载实现；详见 `微服务边界规范.md`。
- 消息业务统一使用 `user_id`；QQ 的 OpenID 和群聊目标只在 `launch/adapter/qq_protocol` 内解释，回复统一通过 `reply_target`，不向业务层泄露传输目标字段。
- 校核、评分和平衡只在 `tools/` 中运行，不进入游戏进程、存档、抽取和战斗裁定。

功法、真意、气机、器律是四个独立内容方向。它们可以组合战斗基石，但不共享一套方向名、形状或评分数据。评分仅服务游戏外平衡维护。

器律不并入上述三个随机方向。它由两到三件兽宝共同为引、多件灵矿为辅，经铸法锻入本命武器四孔；战斗核心只执行最终装配的器律能力。

## 启动

Windows：

```bat
start.bat
```

Linux 或 Docker：

```bash
bash start.sh
```

两个脚本都会在启动前建立并验证 `.venv`，依赖缺失时自动安装 `requirements.txt`；验证失败会重建，不使用已损坏的解释器。

服务地址取自 `.env` 的 `SERVER_HOST` 与 `SERVER_PORT`（模板 `.env.example` 为 `0.0.0.0:8845`，本机 `.env` 为 `0.0.0.0:8080`，浏览器访问用 `http://127.0.0.1:<端口>`）。公开全境舆图为 `/world-map`，天道后台为 `/game-console`。地图只展示世界 JSON 解析结果，不触发 QQ 命令或游戏行为；`地图` 命令只返回同一份世界快照的文字概况与公开链接。玩家命令以运行时帮助注册表为唯一公开清单，状态守卫根据人物是否创建及当前行为、队伍、控制状态统一决定能否执行。天道后台命令保持隐藏，HTTP 登录密码由 `.env` 中的 `WEB_CONSOLE_PASSWORD` 单独提供。

`tools/公式预览` 是已归档的 QQ 消息协议兼容性验证组件，只验证消息协议兼容性，不读游戏 JSON、不写数据库、不实现玩法。它已完成验证价值，默认不装载；需要复验时把 `tools.公式预览` 登记进 `.env` 的 `ROUTER_FOLDERS` 再重启，见 [tools/公式预览/说明.md](tools/公式预览/说明.md)。

旧测试与旧组件契约已经全部删除。当前地基通过编译、真实 JSON 初始化、数据库原子事务和最小战斗调用验收；新领域服务只有在主体 JSON、读取规则、公共引用和实体差异四层审查完成后才允许建立自己的新测试。游戏进程不加载 `tools`，也不执行游戏外评分、校核和平衡脚本。

## 验证

游戏本体只保留 `tests/` 中的行为与数据契约测试；一切架构审查、边界检查、目录与命名校核都属于维护工具，统一放在 `tools/`，不进入游戏进程。

```powershell
.venv/Scripts/python.exe -X utf8 tools/全量核对.py          # 一次跑完必过项（推荐入口）
.venv/Scripts/python.exe -X utf8 tools/全量核对.py --全量    # 连语料与基准一起跑
.venv/Scripts/python.exe -X utf8 -m pytest -q tests
.venv/Scripts/python.exe -X utf8 tools/audit_data.py
.venv/Scripts/python.exe -X utf8 tools/audit_combat_descriptions.py
.venv/Scripts/python.exe -X utf8 tools/验证契约引擎.py
.venv/Scripts/python.exe -X utf8 tools/架构审查/检查边界.py
.venv/Scripts/python.exe -X utf8 tools/架构审查/校验命令目录.py
.venv/Scripts/python.exe -X utf8 tools/架构审查/校验启动契约.py
.venv/Scripts/python.exe -X utf8 tools/架构审查/检查构筑形状.py
.venv/Scripts/python.exe -X utf8 tools/验证控制台媒体.py
.venv/Scripts/python.exe -X utf8 tools/验证驱动器派发.py
.venv/Scripts/python.exe -X utf8 tools/验证启动顺序.py
.venv/Scripts/python.exe -X utf8 tools/验证QQ传输开关.py
.venv/Scripts/python.exe -X utf8 tools/验证QQ双驱动器生命周期.py
.venv/Scripts/python.exe -X utf8 tools/验证QQWebSocket.py
.venv/Scripts/python.exe -X utf8 tools/验证QQWebSocket关闭码.py
```

`全量核对.py` 是**唯一入口**：它按 `REQUIRED` / `SLOW` 逐支跑、各自计时、末尾给一行总账，
任一失败整体非零退出。下面这些单跑命令只在定位问题时用。

`pytest` 是开发期工具，不在 `requirements.txt` 中，需要单独安装：`.venv/Scripts/python.exe -m pip install pytest`。

`tools/架构审查/` 把 `系统架构.md` 与 `微服务边界规范.md` 已经声明的禁止项变成可执行检查，是维护期手动入口，不进入游戏启动，也不被 `game` 依赖：

- `检查边界.py`：动态导入边界、框架反向依赖、跨服务导入内部实现、硬编码数据目录、第二套 JSON 读取、微服务包必备文件、后台例外边界、中文标识符、文件编码、重复定义、写死机器路径、被忽略却仍在索引里的文件等，**共 25 项**（全表见 `tools/架构审查/说明.md`）；
- `校验命令目录.py`：命令所在目录与其 `metadata.scope` 是否一致；
- `校验启动契约.py`：`game/app.py` 的初始化播报、接收者配对与装配顺序；
- `检查数据驱动.py`：无消费者的数据集/池、字段契约覆盖率与手写校验规模；
- `检查构筑形状.py`：功法、真意、气机、器律四个方向的形状是否互相越界，以及被动槽位里从未生效的效果。

另有按领域补充的独立验证入口：

- `验证契约引擎.py`：字段契约引擎本身的行为契约（真实数据通过 + 定向破坏必被拒绝），含四类构筑的形状断言；

- `验证控制台媒体.py`：控制台图片物化、落盘与引用清理的行为契约；
- `验证驱动器派发.py`：QQ webhook、QQ WebSocket 与 Local 三个驱动器在共享派发逻辑上的一致性与截断符契约；
- `验证启动顺序.py`：框架生命周期顺序——驱动器晚于业务服务启动、调度器早于业务启动回调、静态资源与 QQ 入口确实挂载；
- `验证QQ传输开关.py`：`QQ_TRANSPORT` 各取值、未配置时的默认值（webhook）、非法值必须报错，以及两个 QQ 驱动器共用同一个回复管理器；
- `验证QQ双驱动器生命周期.py`：`both` 模式下两种启停顺序，共享运行时都不会被提前拆掉；
- `验证QQWebSocket.py`：回环假网关上的握手、鉴权、心跳、命令派发、回复载荷与 Resume 全链路；
- `验证QQWebSocket关闭码.py`：按官方错误码表核对关闭码决策（可 Resume / 必须重新 Identify / 停止重连）；
- `验证契约引擎.py`：字段契约引擎对合法数据、契约破坏与数据破坏的判定；
- `验证物品契约.py`：物品契约对丹药数据的实际约束力（基线通过 + 各类破坏被拒）；
- `验证组件契约.py`：境界、伤势、阵法、先天灵宝契约对实体数据的实际约束力。

全部检查都必须为 0 越界。修改 `game/` 或 `launch/` 后应先运行它们，再运行测试。改动源码后若结果与预期不符，先清除对应目录的 `__pycache__`：陈旧字节码会掩盖源码改动。

字段契约的书写约定见 [data/schema编写规范.md](data/schema编写规范.md)。
