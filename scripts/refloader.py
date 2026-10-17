#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共享 reference 加载器：统一 references/ 目录解析与 JSON 读取语义，消除 27 个脚本各自为政的
`json.load(open(os.path.join(REF_DIR, name)))` 重复代码。

设计取舍（重要）：
- **默认不做跨调用缓存**。各脚本历史上可能就地修改加载出来的 dict；若返回共享缓存对象，
  一处修改会污染后续所有调用，属难排查的静默错误。故 load() 每次返回全新解析结果，
  与迁移前各脚本 `_load()` 的语义完全一致——这是纯粹的去重/可维护性重构，零行为变更。
- 性能本就不是瓶颈：唯一的大文件 geo_admin.json(390KB) 在 geo_lookup 内已有 _LOADED 守卫
  做进程内一次性建索引，不经由本模块重复加载。
- 只服务 references/ 下的内置数据；用户经 CLI 传入的 plan.json/weather.json 等**不走本模块**。

用法:
    import refloader
    rules = refloader.load("moto_rules.json")        # 缺失/损坏返回 {}
    dests = refloader.load("destinations.json")["destinations"]
    p     = refloader.path("poi.json")               # 仅取绝对路径
"""
import json
import os
from typing import Any

REF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references")

_SENTINEL = object()


def ref_dir() -> str:
    """references/ 目录绝对路径（与安装位置无关）。"""
    return REF_DIR


def path(name: str) -> str:
    """把 reference 文件名解析为绝对路径；已是绝对路径则原样返回。"""
    return name if os.path.isabs(name) else os.path.join(REF_DIR, name)


def load(name: str, default: Any = _SENTINEL) -> Any:
    """读取 references/<name> 并解析为 JSON，每次返回全新对象。

    文件缺失或解析失败时返回 default：
      - 不传 default → 返回 {}（匹配 geo_lookup / outbound_constraints 等的兜底）
      - default=None → 返回 None（匹配 outbound_safety「缺表即 None」的断言语义）
    绝不抛异常打断主流程。
    """
    fallback = {} if default is _SENTINEL else default
    p = path(name)
    if not os.path.exists(p):
        return fallback
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback
