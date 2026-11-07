#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_pack.py — v0.2.26 发布包构建器（单包 · 千问过审档）

纪律：
  - 包根直接放 SKILL.md（提交包布局，非开发布局）
  - 固定时间戳与稳定排序，同输入产出字节可复现
  - 文本统一 LF，避免工作区 CRLF 带入包
  - 剥离测试、维护期脚本、缓存、临时产物与冗余压缩包
  - --verify 逐条目比对包内字节与源码，不一致即失败
用法：
  python tools/build_pack.py --out <path.zip> --verify
"""
from __future__ import print_function

import argparse
import os
import sys
import zipfile

VER = "0.2.26"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ALLOW_EXT = {".md", ".json", ".py", ".svg", ".txt"}
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache",
             "releases", "worldstip-out",
             # 验证集与维护期脚本不随交付包分发（平台两级目录 + 交付卫生约定）
             "tests", "test"}
SKIP_FILES = {
    "_patch_v022.py", "_verify_v022.py", "_tmp_plan.json",
    "run_all_fused.py", "build_fused_pack.py",
}
MAINT = {"build_geo_admin.py", "enrich_coords.py", "verify_coords.py",
         "sync_check.py", "volatile_verify.py", "build_destination_links.py",
         "build_geo_checklist.py"}


def pack_bytes(p):
    """文本统一 LF；其余类型原样。"""
    data = open(p, "rb").read()
    if os.path.splitext(p)[1].lower() in ALLOW_EXT:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return data


def collect():
    items = []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = sorted(d for d in dn if d not in SKIP_DIRS)
        rel_dir = os.path.relpath(dp, ROOT).replace("\\", "/")
        for f in sorted(fn):
            ext = os.path.splitext(f)[1].lower()
            if ext not in ALLOW_EXT:
                continue
            if f in SKIP_FILES or f in MAINT or f.startswith("test_"):
                continue
            p = os.path.join(dp, f)
            rel = f if rel_dir == "." else rel_dir + "/" + f
            items.append((rel, p))
    return sorted(items)


def build(out, verify):
    items = collect()
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, p in items:
            zi = zipfile.ZipInfo(rel, date_time=(2026, 11, 7, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zi.create_system = 3
            z.writestr(zi, pack_bytes(p))
    print("包路径 : %s" % out)
    print("文件数 : %d" % len(items))
    print("体积   : %s bytes (%.2f MB)" % (os.path.getsize(out), os.path.getsize(out) / 1048576.0))

    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        roots = [n for n in names if "/" not in n]
        print("包根   : SKILL.md=%s" % ("SKILL.md" in roots))
        if verify:
            bad = []
            for rel, p in items:
                if z.read(rel) != pack_bytes(p):
                    bad.append(rel)
            print("字节一致校验: %s" % ("PASS" if not bad else "FAIL " + str(bad[:5])))
            if bad:
                return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="构建 v0.2.26 发布包")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(ROOT),
                                                  "worldstip-travel-planner-v%s.zip" % VER))
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    return build(a.out, a.verify)


if __name__ == "__main__":
    sys.exit(main())
