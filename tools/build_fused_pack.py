#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""固定时间戳打包 + 包内文件与源码字节一致校验（纯标准库）。

产物：worldstip-travel-planner-v0.2.1-fused.zip（根目录含 SKILL.md，时间戳固定可复现）。
"""
import argparse, hashlib, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VER = "0.2.1"
STAMP = (2026, 11, 5, 0, 0, 0)
SKIP = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", "releases",
        "examples", "agents"}

# 扩展名白名单：与 _out/fuse/pack_rules.py 保持一致。
# 包内工具必须自包含、不能 import 包外模块，故此处内联同一份规则。
# LICENSE / .gitignore / .skillhubignore 无扩展名，均被白名单拦下；
# 开源协议由各端 frontmatter 的 license 字段声明。
ALLOW_EXT = {".md", ".json", ".py", ".svg"}


def packable(p: Path) -> bool:
    rel = p.relative_to(ROOT)
    if any(x in rel.parts for x in SKIP):
        return False
    if p.name == "_build_manifest.json":
        return False
    if p.name.startswith("_tmp_") or p.suffix in {".tmp", ".log", ".pyc"}:
        return False
    return p.suffix.lower() in ALLOW_EXT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT.parents[3] / "packs" /
                                        f"worldstip-travel-planner-v{VER}-fused.zip"))
    ap.add_argument("--verify", action="store_true", help="只校验已有包，不重写")
    a = ap.parse_args()
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and packable(p))
    blocked = sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                     if p.is_file() and not packable(p)
                     and p.suffix.lower() not in ALLOW_EXT)
    if blocked:
        print("白名单拦截（不进包）：")
        for b in blocked:
            print("  -", b)
    if not a.verify:
        out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in files:
                rel = p.relative_to(ROOT).as_posix()
                zi = zipfile.ZipInfo(rel, date_time=STAMP)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = 0o644 << 16
                zi.flag_bits |= 0x800  # UTF-8 名称标志
                z.writestr(zi, p.read_bytes())
    z = zipfile.ZipFile(a.out)
    names = set(z.namelist())
    bad = [p.relative_to(ROOT).as_posix() for p in files
           if p.relative_to(ROOT).as_posix() not in names
           or z.read(p.relative_to(ROOT).as_posix()) != p.read_bytes()]
    print(f"zip={a.out} entries={len(names)} src_files={len(files)} byte_mismatch={len(bad)}")
    for b in bad[:10]: print("  MISMATCH", b)
    print("SKILL.md in root:", "SKILL.md" in names)
    print("sha256:", hashlib.sha256(Path(a.out).read_bytes()).hexdigest()[:16])
    return 0 if not bad and "SKILL.md" in names else 1

if __name__ == "__main__":
    raise SystemExit(main())
