#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_expert_pack.py — 从 expert/ 源码确定性重建 WorkBuddy 专家包 zip。

与技能包构建器保持同一套纪律：
  - 包内保留外层目录 worldstip-travel-expert/（专家包约定，与技能包相反）
  - 固定时间戳、稳定排序、文本统一 LF，同输入产出字节可复现
  - --verify 逐条目比对 zip 内字节与源码，不一致即 EXIT 1
  - 只收集常规资产，排除缓存与隐藏文件

用法：
    python tools/build_expert_pack.py --verify
    python tools/build_expert_pack.py --out releases/worldstip-travel-expert.zip --verify
"""
from __future__ import print_function

import argparse
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "expert", "worldstip-travel-expert")
OUTER = "worldstip-travel-expert"
STAMP = (2026, 11, 7, 0, 0, 0)
TEXT_EXT = {".md", ".json", ".txt", ".yml", ".yaml"}
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache"}
SKIP_NAMES = {".gitkeep", ".DS_Store"}


def pack_bytes(path):
    data = open(path, "rb").read()
    if os.path.splitext(path)[1].lower() in TEXT_EXT or os.path.basename(path) in {"LICENSE", "NOTICE"}:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return data


def collect():
    """返回 [(zip 内相对路径, 本地绝对路径)]，按 zip 内路径稳定排序。"""
    items = []
    for dp, dn, fn in os.walk(SRC):
        dn[:] = sorted(d for d in dn if d not in SKIP_DIRS)
        for f in sorted(fn):
            if f in SKIP_NAMES or f.startswith("."):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, SRC).replace("\\", "/")
            items.append((OUTER + "/" + rel, p))
    return sorted(items)


def build(out, verify):
    items = collect()
    if not items:
        print("FAIL 专家源码目录为空：%s" % SRC)
        return 1
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, p in items:
            zi = zipfile.ZipInfo(rel, date_time=STAMP)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zi.create_system = 3
            z.writestr(zi, pack_bytes(p))
    print("专家包 : %s" % out)
    print("文件数 : %d" % len(items))
    print("体积   : %d bytes" % os.path.getsize(out))

    if verify:
        with zipfile.ZipFile(out) as z:
            bad = [rel for rel, p in items if z.read(rel) != pack_bytes(p)]
            print("字节一致校验: %s" % ("PASS" if not bad else "FAIL " + str(bad[:5])))
            if bad:
                return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="重建 WorldsTip 旅行规划师专家包")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(ROOT), "dist",
                                                  "worldstip-travel-expert.zip"))
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    return build(a.out, a.verify)


if __name__ == "__main__":
    sys.exit(main())
