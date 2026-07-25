"""Provider PR-10 · Adapter 注册装饰器契约测试。"""
from __future__ import annotations

import pytest

from app.adapters.provider.registry_decorator import (
    AdapterInfo,
    clear_registry_for_testing,
    list_adapters,
    register_adapter,
    resolve_adapter,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry_for_testing()
    yield
    clear_registry_for_testing()


def test_TB40_register_and_resolve():
    @register_adapter("test_proto", capabilities=("chat",))
    class MyAdapter:
        pass

    info = resolve_adapter("test_proto")
    assert info is not None
    assert info.protocol == "test_proto"
    assert "chat" in info.capabilities
    assert "MyAdapter" in info.adapter_class_qualname
    assert MyAdapter._ic_adapter_protocol == "test_proto"


def test_TB41_resolve_missing_returns_none():
    assert resolve_adapter("nonexistent") is None
    assert resolve_adapter("") is None


def test_TB42_resolve_with_capability_filter():
    @register_adapter("multi_proto", capabilities=("chat", "generate_image"))
    class Multi:
        pass

    assert resolve_adapter("multi_proto", capability="chat") is not None
    assert resolve_adapter("multi_proto", capability="video_generate") is None


def test_TB43_duplicate_registration_rejected_by_default():
    @register_adapter("dup_proto")
    class A:
        pass

    with pytest.raises(ValueError, match="already registered"):
        @register_adapter("dup_proto")
        class B:
            pass


def test_TB44_duplicate_registration_allowed_with_replace():
    @register_adapter("replaceable")
    class A:
        pass

    @register_adapter("replaceable", replace=True)
    class B:
        pass

    info = resolve_adapter("replaceable")
    assert info is not None
    assert "B" in info.adapter_class_qualname


def test_TB45_empty_protocol_rejected():
    with pytest.raises(ValueError, match="protocol"):
        @register_adapter("")
        class Nope:
            pass


def test_TB46_list_adapters_sorted():
    @register_adapter("z_proto")
    class Z:
        pass

    @register_adapter("a_proto")
    class A:
        pass

    @register_adapter("m_proto")
    class M:
        pass

    listed = list_adapters()
    assert [a.protocol for a in listed] == ["a_proto", "m_proto", "z_proto"]


def test_TB47_adapter_info_invariants():
    with pytest.raises(ValueError, match="protocol"):
        AdapterInfo(protocol="", adapter_class_qualname="X.Y", capabilities=())
    with pytest.raises(ValueError, match="adapter_class_qualname"):
        AdapterInfo(protocol="x", adapter_class_qualname="", capabilities=())


def test_TB48_module_does_not_import_main():
    import app.adapters.provider.registry_decorator as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
