"""用户插件加载器：扫描用户数据目录中的 Python-Markdown 扩展并按需导入。

插件放在 ``<用户数据目录>/plugins/``，两种形式：

- 单文件：``plugins/my_ext.py``（模块名取文件名，以下划线开头的文件忽略）
- 包：``plugins/my_ext/__init__.py``

插件需提供 ``makeExtension(**kwargs)``，返回一个
``markdown.extensions.Extension``。只有在设置中**显式启用**的插件才会被导入，
单个插件加载失败不影响其它插件。

注意：插件是 Python 代码，运行在本应用进程内；请只启用你信任来源的插件。
"""

from dataclasses import dataclass
import importlib.util
import sys
from pathlib import Path

from ..config import app_data_dir

_MODULE_PREFIX = "mdnote_userplugin_"


@dataclass
class PluginInfo:
    name: str
    kind: str           # "file" | "package"
    path: Path


def plugins_dir() -> Path:
    p = app_data_dir() / "plugins"
    p.mkdir(parents=True, exist_ok=True)
    return p


def discover(directory: Path | None = None) -> list[PluginInfo]:
    d = directory or plugins_dir()
    out: list[PluginInfo] = []
    if not d.exists():
        return out
    for child in sorted(d.iterdir(), key=lambda p: p.name.lower()):
        if child.is_file():
            if child.suffix == ".py" and not child.name.startswith("_"):
                out.append(PluginInfo(child.stem, "file", child))
        elif child.is_dir() and (child / "__init__.py").exists():
            out.append(PluginInfo(child.name, "package", child))
    return out


def _import_plugin(info: PluginInfo):
    mod_name = f"{_MODULE_PREFIX}{info.name}"
    if info.kind == "file":
        location = info.path
        submodule_search = None
    else:
        location = info.path / "__init__.py"
        submodule_search = [str(info.path)]

    spec = importlib.util.spec_from_file_location(mod_name, location)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法为插件 {info.name} 创建导入规格")
    if submodule_search is not None:
        spec.submodule_search_locations = submodule_search

    previous = sys.modules.get(mod_name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        # 失败时恢复旧模块（若有），避免半成品残留在 sys.modules
        if previous is not None:
            sys.modules[mod_name] = previous
        else:
            sys.modules.pop(mod_name, None)
        raise
    return module


def load_enabled(
    names: list[str],
    directory: Path | None = None,
) -> tuple[list, list[tuple[str, str]]]:
    """按启用名单导入并实例化扩展。

    返回 ``(Extension 实例列表, [(插件名, 错误信息), ...])``。
    """
    by_name = {p.name: p for p in discover(directory)}
    instances: list = []
    errors: list[tuple[str, str]] = []
    for name in names:
        info = by_name.get(name)
        if info is None:
            errors.append((name, "未找到该插件"))
            continue
        try:
            module = _import_plugin(info)
            factory = getattr(module, "makeExtension", None)
            if not callable(factory):
                raise AttributeError("插件未提供 makeExtension()")
            ext = factory()
        except Exception as e:  # 隔离每个插件的导入 / 实例化错误
            errors.append((name, f"{type(e).__name__}: {e}"))
            continue
        instances.append(ext)
    return instances, errors
