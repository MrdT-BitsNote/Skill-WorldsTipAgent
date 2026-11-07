#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""history_query.py — 人文史按需加载（v0.2.22 新增）

A 版为压体积把 12.9 万字人文史整段删掉；B 版保留但让主数据涨到 1.66 MB，
每次查询都把全文拖进上下文。本模块用 sidecar 解决两难：

  - 主数据 references/moto_places.json 只留坐标/类型/全称（精简、快）
  - 人文史单独放 references/places_history.json，只有明确查询时才读
  - 支持按景点名精确/包含匹配、按行政区前缀过滤、限制条数与字数
  - 查不到明确返回 found=false，绝不编造

用法：
  python scripts/history_query.py 张家界 --json
  python scripts/history_query.py 山 --contains --max 5 --json
"""
from __future__ import print_function

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(os.path.dirname(HERE), "references", "places_history.json")
_CACHE = None


def _load():
    global _CACHE
    if _CACHE is None:
        with open(PATH, encoding="utf-8") as f:
            _CACHE = json.load(f)
    return _CACHE


def query(name, contains=False, admin="", max_items=5, max_chars=600):
    d = _load()
    items = d.get("items", {})
    hits = []
    for k, v in items.items():
        if contains:
            if name not in k and name not in str(v.get("admin", "")):
                continue
        elif name != k and name not in str(v.get("admin", "")):
            continue
        if admin and admin not in str(v.get("admin", "")):
            continue
        hits.append({"name": k, "admin": v.get("admin", ""),
                     "hi": str(v.get("hi", ""))[:max_chars],
                     "his": str(v.get("his", ""))[:max_chars]})
        if len(hits) >= max_items:
            break
    return {"found": bool(hits), "total_indexed": d.get("total", 0),
            "matched": len(hits), "items": hits,
            "policy": d.get("policy", "")}


def main():
    ap = argparse.ArgumentParser(description="按需查询景点人文史")
    ap.add_argument("name", nargs="?", default="", help="景点名 / 关键词")
    ap.add_argument("--contains", action="store_true", help="包含匹配")
    ap.add_argument("--admin", default="", help="按行政区过滤")
    ap.add_argument("--max", type=int, default=5, dest="max_items")
    ap.add_argument("--max-chars", type=int, default=600)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not a.name:
        print("错误：请给出景点名或关键词", file=sys.stderr)
        return 2
    r = query(a.name, a.contains, a.admin, a.max_items, a.max_chars)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif not r["found"]:
        print("未找到「%s」的人文史（索引 %d 条）" % (a.name, r["total_indexed"]))
    else:
        for x in r["items"]:
            print("\n【%s】%s" % (x["name"], x["admin"]))
            if x["hi"]:
                print("  看点：" + x["hi"])
            if x["his"]:
                print("  沿革：" + x["his"])
    return 0 if r["found"] else 1


if __name__ == "__main__":
    sys.exit(main())
