#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""platform_diff.py — 四平台包的「差异台账」生成与校验。

背景：四个包按平台裁剪了不同文件（WorkBuddy 有 3 MiB 解压上限、千问有零外链与
绿网定位约束），但**差异从来没写过**。结果是使用者拿到某个包，发现文档里提到的
脚本不在包里，只能猜；维护者也不知道哪个包少了什么。

做法：以**实测构建产物**为准（不是凭构建器常量推断），扫出每个包的
scripts/ 与 docs/ 清单，与全量包（SkillHub）对比，生成差异表写进
docs/PLATFORMS.md 的 PLATFORMS:BEGIN / END 之间。

用法：
    python tools/platform_diff.py --write      # 生成并写入 docs/PLATFORMS.md
    python tools/platform_diff.py --check      # 校验文档表与实测包一致（不一致 exit 1）
    python tools/platform_diff.py              # 只打印表格

退出码：0 一致 / 1 不一致或缺包 / 2 参数错误。
"""
from __future__ import print_function

import argparse
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(os.path.dirname(ROOT), "dist")
DOC = os.path.join(ROOT, "docs", "PLATFORMS.md")
BEGIN = "<!-- PLATFORMS:BEGIN 由 tools/platform_diff.py --write 生成，勿手改 -->"
END = "<!-- PLATFORMS:END -->"

# 平台顺序 = 表格行顺序；第一个是「全量基准」，其余按裁剪强度排列
PLATFORMS = ("skillhub", "dumate", "workbuddy", "qianwen")
LABEL = {
    "skillhub": "SkillHub（全量基准）",
    "dumate": "百度 DuMate",
    "workbuddy": "WorkBuddy",
    "qianwen": "千问（零外链 / 国内定位）",
}


def load_version():
    import json
    with open(os.path.join(ROOT, "VERSION.json"), encoding="utf-8") as f:
        return json.load(f)["version"]


def pack_path(dist, plat, ver):
    return os.path.join(dist, "worldstip-travel-planner-v%s-%s.zip" % (ver, plat))


def scan_zip(path):
    """返回 (scripts 集合, docs 集合, 文件总数, 解压后总字节)。"""
    scripts, docs, total, raw = set(), set(), 0, 0
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.filename.endswith("/"):
                continue
            total += 1
            raw += info.file_size
            name = info.filename
            if name.startswith("scripts/") and name.endswith(".py"):
                scripts.add(name[len("scripts/"):])
            elif name.startswith("docs/") and name.endswith(".md"):
                docs.add(name[len("docs/"):])
    return scripts, docs, total, raw


def collect_rows(dist, ver):
    rows, missing = [], []
    for plat in PLATFORMS:
        p = pack_path(dist, plat, ver)
        if not os.path.isfile(p):
            missing.append(os.path.basename(p))
            rows.append({"plat": plat, "zip": os.path.basename(p), "ok": False})
            continue
        scripts, docs, total, raw = scan_zip(p)
        rows.append({"plat": plat, "zip": os.path.basename(p), "ok": True,
                     "scripts": scripts, "docs": docs,
                     "files": total, "bytes": raw,
                     "zip_bytes": os.path.getsize(p)})
    return rows, missing


def signature(rows):
    """参与强校验的结构字段。

    体积列**不入签名**：任何一次文档改写都会让 MiB 小数位抖动，拿它做强校验
    只会天天报「漂移」。真正需要守的是「哪个包缺哪些脚本/文档、文件数多少」。
    """
    base = next((r for r in rows if r["plat"] == "skillhub" and r.get("ok")), None)
    lines = []
    for r in rows:
        if not r.get("ok"):
            lines.append("%s|MISSING" % r["plat"])
            continue
        if base and r["plat"] != "skillhub":
            ms = ",".join(sorted(base["scripts"] - r["scripts"]))
            md = ",".join(sorted(base["docs"] - r["docs"]))
        else:
            ms = md = ""
        lines.append("%s|scripts=%d|docs=%d|files=%d|miss_scripts=%s|miss_docs=%s"
                     % (r["plat"], len(r["scripts"]), len(r["docs"]), r["files"], ms, md))
    return "\n".join(lines)


def render(rows, ver):
    base = next((r for r in rows if r["plat"] == "skillhub" and r.get("ok")), None)
    out = ["", "> 版本 **v%s** ｜ 本表由 `tools/platform_diff.py --write` 实测生成，"
           "由 `--check` 在自检中复算。" % ver, ""]
    out.append("| 平台 | 脚本 | 文档 | 文件数 | 解压后 | zip | 相对全量包的裁剪 |")
    out.append("|---|---|---|---|---|---|---|")
    for r in rows:
        if not r.get("ok"):
            out.append("| %s | — | — | — | — | — | **包未构建** |" % LABEL[r["plat"]])
            continue
        if base and r["plat"] != "skillhub":
            miss_s = sorted(base["scripts"] - r["scripts"])
            miss_d = sorted(base["docs"] - r["docs"])
            extra = sorted((r["scripts"] | r["docs"]) -
                           (base["scripts"] | base["docs"]))
            bits = []
            if miss_s:
                bits.append("缺脚本 %d：%s" % (len(miss_s), "、".join(miss_s)))
            if miss_d:
                bits.append("缺文档 %d" % len(miss_d))
            if extra:
                bits.append("多出 %s" % "、".join(extra))
            cut = "；".join(bits) if bits else "无"
        else:
            cut = "—（基准）"
        out.append("| %s | %d | %d | %d | %.2f MiB | %.2f MiB | %s |" % (
            LABEL[r["plat"]], len(r["scripts"]), len(r["docs"]),
            r["files"], r["bytes"] / 1048576.0, r["zip_bytes"] / 1048576.0, cut))
    out.append("")
    # 缺文档明细单列，避免表格被撑爆
    if base:
        for r in rows:
            if not r.get("ok") or r["plat"] == "skillhub":
                continue
            miss_d = sorted(base["docs"] - r["docs"])
            if miss_d:
                out.append("- **%s 缺的文档**：%s" % (LABEL[r["plat"]], "、".join(miss_d)))
        out.append("")
    out.append("体积列随文档改动浮动，不参与强校验；脚本/文档清单与文件数参与。")
    out.append("")
    out.append("<!-- PLATFORMS-SIG")
    out.append(signature(rows))
    out.append("-->")
    return "\n".join(out)


def write_doc(table):
    with open(DOC, encoding="utf-8") as f:
        doc = f.read()
    i, j = doc.find(BEGIN), doc.find(END)
    if i < 0 or j < 0:
        raise SystemExit("docs/PLATFORMS.md 缺少 %s / %s 标记" % (BEGIN, END))
    new = doc[:i] + BEGIN + "\n" + table + "\n" + doc[j:]
    with open(DOC, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    return new


def extract_block():
    with open(DOC, encoding="utf-8") as f:
        doc = f.read()
    i, j = doc.find(BEGIN), doc.find(END)
    if i < 0 or j < 0:
        return ""
    return doc[i + len(BEGIN):j]


def main(argv=None):
    ap = argparse.ArgumentParser(description="四平台包差异台账")
    ap.add_argument("--dist", default=DIST, help="构建产物目录（默认 ../dist）")
    ap.add_argument("--version", default="", help="版本号（默认读 VERSION.json）")
    ap.add_argument("--write", action="store_true", help="写入 docs/PLATFORMS.md")
    ap.add_argument("--check", action="store_true", help="校验文档与实测包一致")
    a = ap.parse_args(argv)

    ver = a.version or load_version()
    rows, missing = collect_rows(a.dist, ver)
    table = render(rows, ver)
    print(table)

    if missing:
        print("[WARN] 缺包（未构建）：%s" % "、".join(missing))
        if a.check:
            print("PLATFORMS-CHECK: FAIL（包未构建，差异表无从核对）")
            return 1

    if a.write:
        write_doc(table)
        print("[OK] 已写入 docs/PLATFORMS.md")
        return 0

    if a.check:
        block = extract_block()
        if "PLATFORMS-SIG" not in block:
            print("PLATFORMS-CHECK: FAIL（docs/PLATFORMS.md 无差异表签名）")
            return 1
        got = block.split("PLATFORMS-SIG", 1)[1].split("-->", 1)[0].strip()
        want = signature(rows).strip()
        if got != want:
            print("PLATFORMS-CHECK: FAIL（结构与实测包不一致，跑 --write 更新）")
            print("  文档: %s" % got.replace("\n", " / "))
            print("  实测: %s" % want.replace("\n", " / "))
            return 1
        print("PLATFORMS-CHECK: PASS")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
