# OneFlow 技能目录 — 自学习能力产出的工具模块放这里
# 每个 <slug>.py 必须用 @tool 装饰器注册恰好一个工具（与 registry 契约一致）。
# 加载失败的单个文件不影响其他技能与其余工具。
import importlib
import logging
import pkgutil

from ..registry import _REGISTRY

logger = logging.getLogger(__name__)

LOADED: dict[str, str] = {}  # slug -> 状态("ok"/"error: ...")，供诊断


def load_skill_modules(slug: str | None = None) -> list[str]:
    """(重)加载技能模块。slug 为空则扫描整个目录；否则只加载指定技能。

    返回本次成功加载的 slug 列表。重复加载同一 slug 时先清掉其旧注册，
    保证「改了代码重新合并」后生效的是新版本。
    """
    loaded = []
    if slug is None:
        targets = [m.name for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_")]
    else:
        targets = [slug]
    for name in targets:
        full = f"{__name__}.{name}"
        try:
            mod = importlib.import_module(full)
            importlib.reload(mod)
        except Exception as e:  # 单个技能坏了不能拖垮整个注册表
            LOADED[name] = f"error: {e}"
            logger.warning("技能 %s 加载失败: %s", name, e)
            continue
        LOADED[name] = "ok"
        loaded.append(name)
    return loaded


load_skill_modules()
