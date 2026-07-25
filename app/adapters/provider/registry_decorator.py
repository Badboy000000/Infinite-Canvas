"""``app.adapters.provider.registry_decorator`` — Adapter 注册装饰器骨架
(Provider PR-10)。

**承接**:[[40 实施计划/Provider 适配体系治理实施计划与PR清单]] PR-10 ·
承接治理方案 §"AdapterRegistry" · @adapter 装饰器。

**定位**:纯 Python · 允许 Adapter 通过 ``@register_adapter("protocol")`` 装饰器
注册到 registry · 提供 ``resolve_adapter(provider, model?, capability?)`` 骨架 ·
**不接** 实际 provider 分派(归下游 PR)。

**骨架契约**:
- ``AdapterInfo``:frozen dataclass · 一次注册记录
- ``register_adapter(protocol, *, capabilities, replace=False)``:装饰器工厂
- ``resolve_adapter(protocol, ...)``:查找入口 · 未命中返回 ``None``
- ``list_adapters()``:只读 · 用于契约测试与 metadata 端点
- ``clear_registry_for_testing()``:测试专用

**硬约束**:
- 治理期 registry 是模块级 dict · 未来 PR 承接切迁到 registry.py 主体
- 未知 protocol 不抛异常(返回 None)· 便于治理期灰度共存
- 严禁记录密钥
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, Mapping, Optional, Tuple, Type


@dataclass(frozen=True)
class AdapterInfo:
    """一次 adapter 注册记录。"""

    protocol: str
    adapter_class_qualname: str
    capabilities: Tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.protocol:
            raise ValueError("protocol must not be empty")
        if not self.adapter_class_qualname:
            raise ValueError("adapter_class_qualname must not be empty")


# 模块级 registry · 未来 PR 承接切迁到 registry.py 主体
_REGISTRY: Dict[str, AdapterInfo] = {}


def register_adapter(
    protocol: str,
    *,
    capabilities: Iterable[str] = (),
    replace: bool = False,
) -> Callable[[Type], Type]:
    """装饰器工厂 · 把 Adapter 类注册到 registry。

    Args:
        protocol: 协议名(如 "openai_chat")
        capabilities: 声明能力列表
        replace: 如果已存在同 protocol · 是否允许覆盖(默认拒绝)
    """
    if not protocol:
        raise ValueError("protocol must not be empty")

    caps = tuple(capabilities)

    def _decorator(cls: Type) -> Type:
        if not replace and protocol in _REGISTRY:
            existing = _REGISTRY[protocol]
            raise ValueError(
                f"adapter for protocol={protocol!r} already registered "
                f"(existing={existing.adapter_class_qualname}); pass replace=True to override"
            )
        qualname = f"{cls.__module__}.{cls.__qualname__}"
        _REGISTRY[protocol] = AdapterInfo(
            protocol=protocol,
            adapter_class_qualname=qualname,
            capabilities=caps,
        )
        # 附一个 hint 属性 · 供 introspection 使用(不改类语义)
        setattr(cls, "_ic_adapter_protocol", protocol)
        setattr(cls, "_ic_adapter_capabilities", caps)
        return cls

    return _decorator


def resolve_adapter(
    protocol: str,
    *,
    capability: Optional[str] = None,
) -> Optional[AdapterInfo]:
    """查找 adapter · 未命中 protocol 或 capability 时返回 None(不抛)。"""
    if not protocol:
        return None
    info = _REGISTRY.get(protocol)
    if info is None:
        return None
    if capability is not None and capability not in info.capabilities:
        return None
    return info


def list_adapters() -> Tuple[AdapterInfo, ...]:
    """只读 view · 按 protocol 排序。"""
    return tuple(sorted(_REGISTRY.values(), key=lambda a: a.protocol))


def clear_registry_for_testing() -> None:
    """测试专用 · 生产严禁调用(不做 assert · 由 test fixture 显式使用)。"""
    _REGISTRY.clear()
