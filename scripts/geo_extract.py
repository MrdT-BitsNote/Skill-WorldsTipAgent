#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""geo_extract.py — 地名抽取与出发/目的地消歧（v0.2.22 新增）

补的是 v0.2.x 明确留下的缺口：route.detect_to() 只抽境外提示词，
国内地名一律返回空，导致「一句话 → 成品」必须人工补 --to。

做法：
  - 惰性读取技能自带三份地名数据（destinations / geo_admin / moto_places），
    进程内缓存，只在被调用时加载，不进 SKILL.md 默认上下文。
  - 先按「去/到/前往/目的地」等指向词切出目的地候选片段，再在片段内做
    最长匹配；这样「从岳阳出发去张家界」不会把出发地当成目的地。
  - 无指向词时退回全文最长匹配，并在 confidence 里如实标注 lower。
  - 纯标准库、零联网、确定性：同输入必得同输出。

返回 dict：{to, from_city, confidence, matched_via, candidates}
"""
from __future__ import print_function

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REFS = os.path.join(os.path.dirname(HERE), "references")

_CACHE = {}

# 指向词：其后第一个地名优先视作目的地。
TO_MARKS = ("去", "到", "前往", "飞", "抵达", "目的地", "玩", "爬", "逛", "奔")
FROM_MARKS = ("从", "由", "自")

# 这些词在地名库里存在但作目的地太泛，命中也不采信。
TOO_GENERIC = {"中国", "华北", "华东", "华中", "华南", "西南", "西北", "东北",
               "市", "省", "县", "区", "自治区", "特别行政区"}


def _load(name):
    if name not in _CACHE:
        p = os.path.join(REFS, name)
        try:
            with open(p, encoding="utf-8") as f:
                _CACHE[name] = json.load(f)
        except Exception:
            _CACHE[name] = {}
    return _CACHE[name]


def _lexicon():
    """构建 {地名: 来源} 表。长词在前由调用方排序，这里只负责去重。"""
    if "lex" in _CACHE:
        return _CACHE["lex"]
    lex = {}

    def put(word, src):
        if not isinstance(word, str):
            return
        w = word.strip()
        if len(w) < 2 or w in TOO_GENERIC:
            return
        # 只收中文专名，避免把编码/英文键混进来
        if not re.search(r"[\u4e00-\u9fff]", w):
            return
        lex.setdefault(w, src)

    d = _load("destinations.json")
    for x in d.get("destinations", []) or []:
        if isinstance(x, dict):
            put(x.get("name"), "destinations.name")
            put(x.get("short"), "destinations.short")

    g = _load("geo_admin.json")
    for key in ("province", "city", "county"):
        for x in g.get(key, []) or []:
            if isinstance(x, dict):
                put(x.get("name"), "geo_admin." + key)
                for k in x.get("keys", []) or []:
                    put(k, "geo_admin." + key)

    m = _load("moto_places.json")
    for x in m.get("places", []) or []:
        if isinstance(x, dict):
            put(x.get("n"), "moto_places.n")
            put(x.get("alt"), "moto_places.alt")

    _CACHE["lex"] = lex
    _CACHE["lex_sorted"] = sorted(lex.keys(), key=len, reverse=True)
    return lex


def _longest(text, words, limit=1):
    """在片段内做最长匹配，返回按顺序的去重命中。"""
    found = []
    for w in words:
        if w in text and w not in found:
            found.append(w)
            if len(found) >= limit:
                break
    return found


def _ambiguous(text):
    """命中跨省同名地名时返回候选清单，未命中返回 None。

    纪律：先查后问——绝不空手提问，也不静默替用户选一个。
    用户若说出候选的锚点（县名/镇名/特征词），则直接锁定不再问。
    """
    d = _load("geo_ambiguous.json")
    mc = d.get("multi_candidate", {}) or {}
    for canonical, info in mc.items():
        names = [canonical] + list(info.get("aliases", []) or [])
        hit = next((n for n in names if n and n in text), "")
        if not hit:
            continue
        cands = info.get("candidates", []) or []
        # 锚点锁定：命中候选的县/镇/市名即直接收敛
        anchors = []
        for c in cands:
            for key in ("county", "town", "city", "name"):
                v = c.get(key, "")
                if v and len(v) >= 2 and v in text:
                    anchors.append((c, key, v))
        if anchors:
            c = anchors[0][0]
            return {"name": canonical, "hit": hit, "locked": True,
                    "locked_by": anchors[0][2], "to": c.get("name") or canonical,
                    "candidates": [], "hint": ""}
        brief = [{"name": c.get("name"), "province": c.get("province"),
                  "county": c.get("county"), "tags": c.get("tags", [])[:6],
                  "intent_fit": c.get("intent_fit", {})}
                 for c in cands]
        return {"name": canonical, "hit": hit, "locked": False,
                "to": "", "candidates": brief,
                "hint": info.get("default_hint", ""),
                "correction": info.get("correction", {})}
    return None


def extract(text, explicit_to="", explicit_from=""):
    """主入口。explicit_* 由调用方传入时优先采信。"""
    t = (text or "").strip()
    lex = _lexicon()
    words = _CACHE["lex_sorted"]
    out = {"to": explicit_to or "", "from_city": explicit_from or "",
           "confidence": "explicit" if explicit_to else "none",
           "matched_via": "cli" if explicit_to else "", "candidates": [],
           "ambiguous": None}

    if not t:
        return out

    # 歧义优先于普通地名：跨省同名一律先列候选，不静默归属。
    if not explicit_to:
        amb = _ambiguous(t)
        if amb:
            out["ambiguous"] = amb
            if amb["locked"]:
                out["to"] = amb["to"]
                out["confidence"] = "high"
                out["matched_via"] = "geo_ambiguous.anchor"
            else:
                out["confidence"] = "ambiguous"
            return out

    # 出发地：只在「从 X 出发 / 由 X / 自 X」结构里取。
    fm = re.search(r"[从由自]([\u4e00-\u9fff]{2,12}?)(?:出发|启程|走|去|到|前往|，|,|\s|$)", t)
    if fm and not out["from_city"]:
        hit = _longest(fm.group(1), words, 1)
        if hit:
            out["from_city"] = hit[0]

    # 目的地：优先在指向词之后的片段里找。
    seg = ""
    for mark in TO_MARKS:
        m = re.search(re.escape(mark) + r"([\u4e00-\u9fffA-Za-z0-9]{2,20})", t)
        if m:
            seg = m.group(1)
            break
    if not explicit_to:
        scope = seg or t
        # 去掉出发地，避免「从岳阳出发去张家界」把岳阳再命中一次
        if out["from_city"]:
            scope = scope.replace(out["from_city"], "", 1)
        hits = _longest(scope, words, 4)
        out["candidates"] = hits
        if hits:
            out["to"] = hits[0]
            out["matched_via"] = lex.get(hits[0], "")
            out["confidence"] = "high" if seg else "lower"
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description="从用户原话抽取出发地与目的地")
    ap.add_argument("text", nargs="?", default="")
    ap.add_argument("--to", default="")
    ap.add_argument("--from", dest="frm", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = extract(a.text, a.to, a.frm)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print("目的地=%s  出发地=%s  置信=%s  命中表=%s" %
              (r["to"], r["from_city"], r["confidence"], r["matched_via"]))
    return 0 if r["to"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
