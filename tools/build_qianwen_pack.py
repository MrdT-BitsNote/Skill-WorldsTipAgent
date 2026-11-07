#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_qianwen_pack.py — 千问 AI 平台（platform.qianwenai.com）发布包。

官方硬约束：
  1. ZIP 根目录必须有 `SKILL.md`（不能被外层目录包裹）
  2. 整包体积 <= 10 MiB（校验的是 zip，不是解压后）
  3. frontmatter 的 `---` 内必须有 `name` 与 `description`

平台另有「安全绿网」内容扫描，历史驳回集中在四类红线：
  站外引流域名 / 境外地图源 / 领土表述 / 高敏词。
因此本包在 build_workbuddy_pack 的裁剪集之上再确保：
  - 零 http(s) 外链、零 worldstip/qianwen/github 域名
  - 不含 `places_history.json`（含高敏词）
  - 不含自有站点采集脚本与外链清单

与 WorkBuddy 包的唯一差异：不改 `display_name`（千问认 name，不认 display_name）。

用法：
    python tools/build_qianwen_pack.py [--out PATH]
"""
import argparse
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_pack as BP          # noqa: E402
import build_workbuddy_pack as BWB  # noqa: E402

LIMIT = 10 * 1024 * 1024
DOMAIN = re.compile(r"[a-z0-9.\-]*(?:worldstip\.com|qianwenai\.com|github\.com|"
                    r"openstreetmap\.org|unpkg\.com|w3\.org)", re.I)
URL = re.compile(r"https?://")
SENSITIVE = ("政治",)


def scan(out):
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        domains = urls = sensitive = 0
        hits = []
        for n in names:
            if not n.lower().endswith((".md", ".json", ".py", ".txt", ".svg")):
                continue
            t = z.read(n).decode("utf-8", errors="replace")
            d = DOMAIN.findall(t)
            u = URL.findall(t)
            s = sum(t.count(w) for w in SENSITIVE)
            domains += len(d)
            urls += len(u)
            sensitive += s
            if d or u or s:
                hits.append((n, len(d), len(u), s))
        skill = z.read("SKILL.md").decode("utf-8")
    return names, skill, domains, urls, sensitive, hits


def main():
    ap = argparse.ArgumentParser(description="构建千问 AI 平台发布包")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = args.out or os.path.join(
        os.path.dirname(BP.ROOT), "dist",
        "worldstip-travel-planner-v%s-qianwen.zip" % BP.VER)
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    out, _ = BWB.build(out, align_display=False)

    names, skill, domains, urls, sensitive, hits = scan(out)
    size = os.path.getsize(out)
    parts = skill.split("---")
    fm = parts[1] if skill.startswith("---") and len(parts) >= 3 else ""
    checks = [
        ("ZIP 总体积 <= 10MiB", size <= LIMIT, "%d bytes (%.2f MiB)" % (size, size / 1048576.0)),
        ("根目录 SKILL.md", "SKILL.md" in names, "文件数 %d" % len(names)),
        ("无外层目录包裹", not (any("/" in n for n in names) and "SKILL.md" not in names), ""),
        ("frontmatter name", bool(re.search(r"^name:\s*\S+", fm, re.M)), ""),
        ("frontmatter description", bool(re.search(r"^description:\s*\S+", fm, re.M)), ""),
        ("零外链域名", domains == 0, "命中 %d" % domains),
        ("零 http(s) URL", urls == 0, "命中 %d" % urls),
        ("零高敏词", sensitive == 0, "命中 %s" % (SENSITIVE,)),
    ]
    print("包路径 : %s" % out)
    for name, ok, detail in checks:
        print("  %s  %-26s %s" % ("PASS" if ok else "FAIL", name, detail))
    if hits:
        print("命中明细: %s" % hits[:6])
    ok = all(c[1] for c in checks)
    print("RESULT: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
