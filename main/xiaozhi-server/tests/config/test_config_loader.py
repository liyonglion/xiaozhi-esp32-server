"""Tests for the recursive config merge in config/config_loader.py."""
from config.config_loader import merge_configs

import asyncio
import importlib

import pytest

import config.config_loader as config_loader_module


def test_merge_simple_override():
    default = {"a": 1, "b": 2}
    custom = {"b": 99}
    assert merge_configs(default, custom) == {"a": 1, "b": 99}


def test_merge_adds_new_key():
    default = {"a": 1}
    custom = {"b": 2}
    assert merge_configs(default, custom) == {"a": 1, "b": 2}


def test_merge_recursive_dict():
    default = {"x": {"a": 1, "b": 2}}
    custom = {"x": {"b": 99}}
    assert merge_configs(default, custom) == {"x": {"a": 1, "b": 99}}


def test_merge_deep_recursive():
    default = {"a": {"b": {"c": 1, "d": 2}}}
    custom = {"a": {"b": {"c": 99}}}
    assert merge_configs(default, custom) == {"a": {"b": {"c": 99, "d": 2}}}


def test_merge_replaces_non_dict_with_dict():
    default = {"a": 1}
    custom = {"a": {"nested": True}}
    assert merge_configs(default, custom) == {"a": {"nested": True}}


def test_merge_replaces_dict_with_non_dict():
    default = {"a": {"nested": True}}
    custom = {"a": 1}
    assert merge_configs(default, custom) == {"a": 1}


def test_merge_does_not_mutate_defaults():
    default = {"a": {"b": 1}}
    custom = {"a": {"c": 2}}
    merge_configs(default, custom)
    assert default == {"a": {"b": 1}}  # unchanged


# ---- read_config_from_api 两模式分支（工单 #10）----
# 开关 = data/.config.yaml 里 manager-api.url 填/清：填了走 manager-api
# 拉取（read_config_from_api=True），没填走本地文件合并。


@pytest.fixture
def real_load_config():
    """conftest 把模块级 load_config 换成了桩——reload 拿回真函数，
    用完恢复 conftest 桩，保证后续测试隔离不受影响。"""
    conftest_stub = config_loader_module.load_config
    reloaded = importlib.reload(config_loader_module)
    yield reloaded.load_config
    config_loader_module.load_config = conftest_stub


def _isolate_loader(monkeypatch, default, custom):
    """隔离文件读取/远端拉取/目录创建与配置缓存，只留分支逻辑。"""

    def fake_read(path):
        return dict(custom) if path.endswith("data/.config.yaml") else dict(default)

    monkeypatch.setattr(config_loader_module, "read_config", fake_read)
    monkeypatch.setattr(config_loader_module, "ensure_directories", lambda _cfg: None)
    import core.utils.cache.manager as cache_module

    monkeypatch.setattr(
        cache_module.cache_manager, "get", lambda *_a, **_k: None, raising=False
    )
    monkeypatch.setattr(
        cache_module.cache_manager, "set", lambda *_a, **_k: None, raising=False
    )


def test_load_config_with_manager_api_url_goes_api_mode(monkeypatch, real_load_config):
    """填了 manager-api.url → 走 manager-api 拉取，配置带 read_config_from_api=True。"""
    _isolate_loader(monkeypatch, default={}, custom={"manager-api": {"url": "http://127.0.0.1:8002/xiaozhi", "secret": "s"}})

    calls = []

    async def _fake_api_config(custom_cfg):
        calls.append(custom_cfg)
        return {"server": {"ip": "0.0.0.0"}, "read_config_from_api": True}

    monkeypatch.setattr(config_loader_module, "get_config_from_api_async", _fake_api_config)

    config = asyncio.run(real_load_config())

    assert config["read_config_from_api"] is True
    assert len(calls) == 1


def test_load_config_without_url_merges_files_and_skips_api(monkeypatch, real_load_config):
    """没填 manager-api.url → 本地文件合并，不触达 manager-api。"""
    _isolate_loader(monkeypatch, default={"a": 1}, custom={"b": 2})

    async def _fail_api_config(_cfg):
        raise AssertionError("文件模式不应调用 manager-api")

    monkeypatch.setattr(config_loader_module, "get_config_from_api_async", _fail_api_config)

    config = asyncio.run(real_load_config())

    assert config == {"a": 1, "b": 2}
    assert not config.get("read_config_from_api")