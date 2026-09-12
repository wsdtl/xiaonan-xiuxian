"""
项目配置。

只读取项目根目录的 .env，并实例化出全局 config。

其他模块统一这样使用：

    from launch.config import config

或：

    from launch import config

项目只有一个配置入口，也只有一个配置对象。
"""

import ast
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# 项目根目录。
BASE_DIR = Path(__file__).resolve().parent.parent


# 未配置公开域名时，用本机地址生成项目内公开链接。
DEFAULT_PUBLIC_HOST = "127.0.0.1"


# 唯一配置入口：项目根目录下的 .env 文件。
ENV_FILE = BASE_DIR / ".env"


# 项目基础配置在 .env 里的键名。
PROJECT_ENV_KEYS = {
    "PROJECT_ID",
    "PROJECT_NAME",
    "PROJECT_DEBUG",
    "PROJECT_TIMEZONE",
    "PROJECT_DOMAIN",
}


# 服务监听配置在 .env 里的键名。
SERVER_ENV_KEYS = {
    "SERVER_HOST",
    "SERVER_PORT",
    "SERVER_RELOAD",
    "SERVER_SSL_CERTFILE",
    "SERVER_SSL_KEYFILE",
}


# 日志配置在 .env 里的键名。默认值在 load_config() 中维护。
LOG_ENV_KEYS = {
    "LOG_LEVEL",
    "LOG_COLOR",
    "LOG_DIR",
    "LOG_FILE",
    "LOG_ROTATION",
    "LOG_RETENTION",
    "LOG_COMPRESSION",
}


# 模块 / 路由加载配置在 .env 里的键名。
ROUTER_ENV_KEYS = {
    "ROUTER_MODULE_GROUPS",
    "ROUTER_MODULES",
    "ROUTER_FOLDERS",
    "ROUTER_GROUPS",
    "ROUTER_CHILD_FOLDERS",
}


# 通信驱动器配置在 .env 里的键名。
#
# 驱动器清单本身由代码登记，这里只放"启用哪些"和驱动器自己的协议参数。
# 框架不猜测业务含义，所以这些键不进入 config.custom。
ADAPTER_ENV_KEYS = {
    "QQ_TRANSPORT",
    "QQ_WS_GATEWAY_URL",
    "QQ_WS_INTENTS",
}


# 项目已经认识的配置键名；其他 .env 项会进入 config.custom。
SYSTEM_ENV_KEYS = (
    PROJECT_ENV_KEYS
    | SERVER_ENV_KEYS
    | LOG_ENV_KEYS
    | ROUTER_ENV_KEYS
    | ADAPTER_ENV_KEYS
)


def read_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    """
    读取 .env，返回字符串字典。

    支持写法：

        PROJECT_ID=xiaonan_xiuxian
        PROJECT_NAME=晓楠修仙
        ROUTER_GROUPS=["示例路由组"]
        zdy1=hello

    空行、# 注释、无等号的行会被忽略。
    """

    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在：{path}\n" "请复制项目根目录的 .env.example 为 .env 后再启动项目。")

    values: dict[str, str] = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key:
            values[key] = value

    return values


class Env:
    """
    .env 字符串字典的读取工具。

    只负责把字符串转成常用类型，不负责业务含义。
    """

    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get(self, name: str, default: str = "") -> str:
        """读取一个字符串配置。"""

        return self.values.get(name, default).strip()

    def get_bool(self, name: str, default: bool = False) -> bool:
        """
        读取布尔配置。

        推荐写法：

            PROJECT_DEBUG=true
            PROJECT_DEBUG=false

        也支持 1/0、yes/no、on/off。
        """

        raw = self.get(name)
        if not raw:
            return default

        value = raw.lower()
        if value in {"true", "1", "yes", "on"}:
            return True
        if value in {"false", "0", "no", "off"}:
            return False

        raise ValueError(f"{name} 的值只能是 true/false、1/0、yes/no、on/off，当前值是：{raw}")

    def get_list(self, name: str, default: Iterable[str] = ()) -> list[str]:
        """
        读取列表配置。

        .env 中必须写成列表：

            ROUTER_GROUPS=["示例路由组"]
        """

        raw = self.get(name)
        if not raw:
            return list(default)

        try:
            value = ast.literal_eval(raw)
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"{name} 必须写成列表，例如：{name}=['game']") from exc

        if not isinstance(value, list):
            raise TypeError(f"{name} 必须是列表，例如：{name}=['game']")

        for item in value:
            if not isinstance(item, str):
                raise TypeError(f"{name} 里的每一项都必须是字符串，当前项是：{item!r}")

        return [item.strip() for item in value if item.strip()]

    def get_path(self, name: str, default: Path | str) -> Path:
        """
        读取路径配置。

        相对路径会转成相对于项目根目录的绝对路径。
        """

        path = Path(self.get(name, str(default)))
        if path.is_absolute():
            return path
        return BASE_DIR / path


def apply_project_timezone(timezone_name: str) -> None:
    """校验项目时区，并在支持 IANA TZ 的平台同步到当前进程。

    Windows 运行库不按 IANA 时区名解析 TZ=Asia/Shanghai。reload 子进程
    如果继承这个环境变量，日志时间会被解析成错误的 UTC+1，所以 Windows
    下只保留 ZoneInfo 校验，不写入 TZ。
    """

    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"PROJECT_TIMEZONE 配置无效，当前值是：{timezone_name}") from exc

    if os.name == "nt":
        os.environ.pop("TZ", None)
        return

    os.environ["TZ"] = timezone_name
    if hasattr(time, "tzset"):
        time.tzset()


@dataclass(frozen=True)
class ProjectConfig:
    """项目基础配置。"""

    id: str
    name: str
    debug: bool
    timezone: str
    domain: str


@dataclass(frozen=True)
class ServerConfig:
    """服务监听配置。"""

    host: str
    port: int
    reload: bool
    ssl_certfile: Path | None
    ssl_keyfile: Path | None


@dataclass(frozen=True)
class LogConfig:
    """日志相关配置。"""

    level: str
    color: str
    dir: Path
    file: Path
    rotation: str
    retention: str
    compression: str


@dataclass(frozen=True)
class RouterConfig:
    """
    模块和路由加载配置。

    .env 中必须写成列表：

        ROUTER_MODULE_GROUPS=["auto"]
        ROUTER_GROUPS=["示例路由组"]
    """

    module_groups: list[str]
    modules: list[str]
    router_folders: list[str]
    router_groups: list[str]
    router_child_folders: list[str]


@dataclass(frozen=True)
class Config:
    """
    项目总配置。

    常用读取：

        from launch import config

        print(config.project.id)
        print(config.project.name)
        print(config.project.debug)
        print(config.project.timezone)
        print(config.log.level)
        print(config.router.modules)

    自定义参数：

        zdy1=hello
        print(config.zdy1)

    非 Python 属性名用 get：

        MY-TOKEN=123
        token = config.get("MY-TOKEN", "")
    """

    base_dir: Path
    env_file: Path
    raw: dict[str, str]
    project: ProjectConfig
    server: ServerConfig
    log: LogConfig
    router: RouterConfig
    custom: dict[str, str]

    def get(self, name: str, default: str = "") -> str:
        """
        安全读取自定义配置。

        适合读取不方便点语法的名字：

            config.get("MY-TOKEN")
            config.get("abc.def")
            config.get("1name")
        """

        return self.custom.get(name, default)

    def __getattr__(self, name: str) -> str:
        """
        让自定义配置可以用 config.xxx 直接读取。

        例如：

            zdy1=hello
            print(config.zdy1)
        """

        if name in self.custom:
            return self.custom[name]

        raise AttributeError(f"配置项不存在：config.{name}")


def load_config() -> Config:
    """读取 .env，并实例化项目配置。"""

    raw = read_env_file()
    env = Env(raw)

    # 项目基础配置。
    project_id = env.get("PROJECT_ID", "xiaonan_xiuxian").strip()
    project_name = env.get("PROJECT_NAME", "晓楠修仙").strip()
    if not project_id or not project_id.isascii():
        raise ValueError("PROJECT_ID 必须是非空 ASCII 技术标识")
    if not project_name:
        raise ValueError("PROJECT_NAME 不能为空")

    project = ProjectConfig(
        id=project_id,
        name=project_name,
        debug=env.get_bool("PROJECT_DEBUG", False),
        timezone=env.get("PROJECT_TIMEZONE", "Asia/Shanghai"),
        domain=env.get("PROJECT_DOMAIN", ""),
    )
    apply_project_timezone(project.timezone)

    # 服务监听配置。
    server = ServerConfig(
        host=env.get("SERVER_HOST", "0.0.0.0"),
        port=int(env.get("SERVER_PORT", "1234") or "1234"),
        reload=env.get_bool("SERVER_RELOAD", False),
        ssl_certfile=env.get_path("SERVER_SSL_CERTFILE", "") if env.get("SERVER_SSL_CERTFILE") else None,
        ssl_keyfile=env.get_path("SERVER_SSL_KEYFILE", "") if env.get("SERVER_SSL_KEYFILE") else None,
    )

    # 日志配置默认写在这里，需要变化时再放到 .env 覆盖。
    log_dir = env.get_path("LOG_DIR", BASE_DIR / "log")

    log = LogConfig(
        level=env.get("LOG_LEVEL", "INFO").upper(),
        color=env.get("LOG_COLOR", "auto").lower(),
        dir=log_dir,
        file=env.get_path("LOG_FILE", log_dir / "runserver.log"),
        rotation=env.get("LOG_ROTATION", "12:00"),
        retention=env.get("LOG_RETENTION", "14 days"),
        compression=env.get("LOG_COMPRESSION", "zip"),
    )

    # Router 配置默认写在这里，.env 覆盖时必须写成列表。
    router = RouterConfig(
        module_groups=env.get_list("ROUTER_MODULE_GROUPS", []),
        modules=env.get_list("ROUTER_MODULES", []),
        router_folders=env.get_list("ROUTER_FOLDERS", []),
        router_groups=env.get_list("ROUTER_GROUPS", []),
        router_child_folders=env.get_list("ROUTER_CHILD_FOLDERS", []),
    )

    # 未被系统识别的键都作为自定义配置。
    custom = {key: value for key, value in raw.items() if key not in SYSTEM_ENV_KEYS}

    return Config(
        base_dir=BASE_DIR,
        env_file=ENV_FILE,
        raw=raw,
        project=project,
        server=server,
        log=log,
        router=router,
        custom=custom,
    )


# 已经实例化好的项目配置对象，供其他模块直接读取。
config = load_config()
