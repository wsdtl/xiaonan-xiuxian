"""按配置导入业务模块，并挂载其中公开的 FastAPI 路由。

装载边界只有两件事：导入模块触发注册，以及挂载模块公开的 router。
模块清单来自 `.env`，框架不硬编码任何业务包名，也不解释业务规则。
"""

from collections.abc import Iterator
from importlib import import_module
from pathlib import Path

from .config import config
from .log import C, logger


def _module_path(name: str) -> Path:
    """把配置中的点号模块名转换成项目内目录。"""

    path = Path(*name.split(".")) if "." in name else Path(name)
    return path if path.is_absolute() else config.base_dir / path


def _require_directory(name: str) -> Path:
    """确认配置指向真实目录，错误在启动阶段直接暴露。"""

    path = _module_path(name)
    if not path.is_dir():
        raise FileNotFoundError(f"模块目录不存在或不是目录：{name} -> {path}")
    return path


def _require_package(name: str) -> Path:
    """确认目录是 Python 包，避免导入阶段才出现难定位的错误。"""

    path = _require_directory(name)
    init_file = path / "__init__.py"
    if not init_file.is_file():
        raise FileNotFoundError(f"模块缺少 __init__.py：{name} -> {init_file}")
    return path


def _package_children(name: str) -> Iterator[str]:
    """返回目录下的子包名，顺序固定以保证启动结果可复现。"""

    for child in sorted(_require_directory(name).iterdir(), key=lambda item: item.name):
        if child.is_dir() and (child / "__init__.py").is_file():
            yield child.name


def _collect_modules() -> tuple[tuple[str, ...], frozenset[str]]:
    """收集待导入模块，以及其中真正提供路由的模块。

    配置含义保持单一：模块组导入所有子包；路由目录导入一个 router 包；
    普通模块只导入；路由组挂载组本身并导入子包；路由子目录把每个子包
    都当作 router。最后按首次出现顺序去重。
    """

    modules: list[str] = []
    routers: set[str] = set()

    def add(name: str, *, has_router: bool = False) -> None:
        # 先记录导入顺序，再单独记录需要 include_router 的模块；
        # 一个模块可能只负责注册命令，也可能同时暴露 HTTP router。
        modules.append(name)
        if has_router:
            routers.add(name)

    for folder in config.router.module_groups:
        modules.extend(f"{folder}.{child}" for child in _package_children(folder))

    for folder in config.router.router_folders:
        _require_package(folder)
        add(folder, has_router=True)

    modules.extend(config.router.modules)

    for folder in config.router.router_groups:
        _require_package(folder)
        add(folder, has_router=True)
        modules.extend(f"{folder}.{child}" for child in _package_children(folder))

    for folder in config.router.router_child_folders:
        for child in _package_children(folder):
            add(f"{folder}.{child}", has_router=True)

    return tuple(dict.fromkeys(modules)), frozenset(routers)


def module_tag(module_name: str) -> str:
    """生成 OpenAPI 文档分类名，默认使用模块最后一段。"""

    return module_name.rsplit(".", 1)[-1]


def FastAPIIncludeRouter(app) -> None:
    """导入配置模块并挂载路由，重复调用时保持幂等。"""

    if getattr(app.state, "business_router_loaded", False):
        return

    modules, routers = _collect_modules()
    for module_name in modules:
        try:
            module = import_module(module_name)
        except Exception as exc:
            logger.opt(colors=True, exception=exc).error(
                C.join(C.fail("业务模块加载失败"), C.kv("module", module_name))
            )
            raise

        if module_name not in routers:
            logger.opt(colors=True).success(
                C.join(C.ok("已导入业务模块"), C.kv("module", module_name))
            )
            continue

        router = getattr(module, "router", None)
        if router is None:
            raise AttributeError(f"路由模块未暴露 router：{module_name}")

        tag = module_tag(module_name)
        app.include_router(router, tags=[tag])
        logger.opt(colors=True).success(
            C.join(C.ok("已挂载业务路由"), C.kv("module", module_name), C.kv("tag", tag))
        )

    app.state.business_router_loaded = True


__all__ = ["FastAPIIncludeRouter", "module_tag"]
