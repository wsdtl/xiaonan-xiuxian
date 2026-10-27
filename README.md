# 晓楠修仙

QQ 文字修仙游戏：Python 3.12 + FastAPI + SQLite。规则与内容住在 `data/` 的 JSON 里，Python 只做读取、编排、结算与展示。

> [系统架构.md](系统架构.md) 管服务与依赖，[微服务边界规范.md](微服务边界规范.md) 管导入边界，[核心设定.md](核心设定.md) 管玩法，[说明模版.md](说明模版.md) 管写法。

## 改哪儿，读哪几份

| 要改的东西 | 读这几份 |
| --- | --- |
| 数据结构、组件与 schema | [data/说明.md](data/说明.md)、[data/schema编写规范.md](data/schema编写规范.md) |
| 编号、品级、属性 | [data/基础/说明.md](data/基础/说明.md) |
| 战斗规则与卡面文本 | [data/战斗/说明.md](data/战斗/说明.md)、[data/战斗/内容/文本规范.md](data/战斗/内容/文本规范.md) |
| 某个玩法 | `data/玩法/<域>/<组件>/说明.md` |
| 命令、消息、按钮 | [game/cmd/说明.md](game/cmd/说明.md)、[message/消息协议说明.md](message/消息协议说明.md) |
| 某个核心服务 | `game/core/<包>/说明.md`（只留关键服务） |
| 启动与组合根 | [game/startup/说明.md](game/startup/说明.md)、[系统架构.md](系统架构.md) |
| 通信适配 | [launch/adapter/说明.md](launch/adapter/说明.md) |
| 展示页 | [static/说明.md](static/说明.md) |
| 判据与工具 | [tools/说明.md](tools/说明.md) |

## 当前规模

- 数据：**3174 份 JSON、57 个组件包**；正式装载 **3117 文档、2935 实体、317 资源池**。
- 服务：**41 个核心微服务、49 个玩法微服务**；命令层 **52 个二级组件**（查看与工具 11、修行 7、关系 3、行动 7、战斗 3、炼制 3、宗门 11、特殊地点 6、后台入口 1）。
- 命令：**166 条命令、10 条守卫规则**；页面 14 个。
- 这些数以实际装载与启动日志为准。

## 目录

```text
data/          定义、规则、内容与展示 JSON
database/      玩家存档、运行日志与辅助路由库（不进版本库）
game/core/     跨玩法公共微服务
game/features/ 具体玩法微服务
game/cmd/      命令、按钮与 HTTP 触发
game/startup/  启动契约
game/app.py    唯一组合根
launch/        Local、QQ、HTTP、生命周期与统一身份端口
assist_router/ QQ openid / group_openid 与真实 QQ 号/群号对齐
message/       通用消息协议
static/        展示页面
tools/         游戏外校核脚本
tests/         核心行为测试
```

## JSON 驱动边界

- `data/<大类>/<组件>/{定义,规则,内容,展示}`；组件名与大类同名时省略一层。
- 唯一入口是 `data/基础/读取规则.json`，每包另有 `组件.json`；一份正式 JSON 必须且只能匹配一条规则。
- Python 只固定读取这份引导文件，不硬编码业务目录；运行期不扫描、不热重载，改完必须重启。
- `data` 不保存数据库、备份或运行媒体；数据库进 `database/`，备份与控制台媒体进 `.runtime/`。
- 校核、评分与平衡只在 `tools/` 跑，不进入游戏进程、存档、抽取与战斗裁定。
- 每个组件一份 `说明.md`：写行为、数据集与边界，不复述代码。

## 启动

Windows 用 `start.bat`，Linux/Docker 用 `bash start.sh`；脚本会先建并验证 `.venv`，缺依赖时安装 `requirements.txt`。

证书目录 `certs/` 启动时自建；**HTTP 还是 HTTPS 由证书实际在不在决定**：没配或文件不在就走 HTTP，两个文件都在才走 HTTPS。

地址取自 `.env` 的 `SERVER_HOST` 与 `SERVER_PORT`（本机 `0.0.0.0:8443`）。页面：`/baike`、`/game-console`、`/battle/<战报编号>`、`/world-map`、`/assembly`、`/yijing`。天道后台命令隐藏，密码由 `WEB_CONSOLE_PASSWORD` 提供。游戏进程不加载 `tools`。

QQ 统一身份由 `assist_router` 维护：官方 openid 对齐到 QQ 号，游戏账号主键使用 QQ 号，openid 只作平台回复目标。未建立路由的 QQ 命令会回复“身份同步中，请稍后再发一次”；本地/后台命令不受影响。

## 打包发布

```bat
.venv\Scripts\python.exe -X utf8 build.py
```

把游戏本体与 `data/` 拷进 `BUILD/`：只放代码与数据，`.md` 不进包（要留档加 `--含说明`）。运行期状态与 `*.lock` / `*.db` / `*.bak` 不进包。打包器默认做一次全新部署自检；更新时用 `BUILD/` 覆盖，`database/`、`.env`、`log/`、`.runtime/`、`certs/` 都不进包。

## 验证

```powershell
.venv/Scripts/python.exe -X utf8 tools/全量核对.py   # 9 项必过，退出码把关
```

9 项：边界审查、启动契约、数据驱动、存档键名、存档结构（键名/结构/领域语义）、数据不被写回、启动顺序、语法、单元测试。每项独立进程并发跑，末尾一行总账。

`pytest` 不在 `requirements.txt` 里，需单独安装；测试由 `tools/跑测试.py` 跑，用临时数据库，不碰真实存档。判据挡下改动时先改做法，不改判据口径。
