#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doctor.py — 离线自检（v0.2.22 新增，一条命令给出可否交付的结论）

把 A/B 时代散落在多个临时脚本里的验收动作收敛成一个确定性入口：

  1. 版本真源：VERSION.json.version 与 8 个文件的当前版本号逐一对齐
  2. 结构：目录深度 <= 1、SKILL.md 在根、无临时产物夹带
  3. 字段：frontmatter 必填 5 项、description 单行且 <= 200 字、权限非空
  4. 脚本：全部 .py 通过语法解析
  5. 数据：全部 .json 可解析、关键数据文件条目数达标
  6. 引用：SKILL.md / README.md 里反引号引用的 scripts|references|docs 文件真实存在
  7. 冒烟：统一入口三条分支（放行 / 拦截 / 歧义）实跑并断言退出码
  8. 词表（可选）：--lexicon <文件> 注入外部词表后逐文件扫描；不注入则跳过并如实标注

纪律：纯标准库、零联网、零修改被检文件；任何一项失败即 EXIT 1，
不输出「看起来通过」的结论。--json 出机器可读结果。
"""
from __future__ import print_function

import argparse
import ast
import contextlib
import io
import json
import os
import re
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

VERSION_FILES = [
    "SKILL.md", "README.md", "CHANGELOG.md", "INSTALL.md",
    "QC_REPORT.md", "DoD.md", "scripts/worldstip.py", "tools/build_pack.py",
]
KEY_DATA = {
    "references/moto_places.json": 2000,
    "references/destinations.json": 300,
    "references/places_history.json": 1000,
}
FM_REQUIRED = ("description", "description_zh", "description_en", "version", "author")
TEMP_MARK = ("worldstip-out", "__pycache__", ".pytest_cache",
             "_tmp_", ".bak", ".zip")
# 与 tools/build_pack.SKIP_DIRS 保持一致：本地版本库、归档位与独立专家包
# 都不进技能交付包，因此不参与技能包的目录深度 / 临时产物检查。
# expert/ 是 WorkBuddy 专家包源码（自带 .codebuddy-plugin/ 与 agents/ 子目录），
# 其结构由 tools/verify_backup.py 单独校验，不适用技能包的两级约束。
SKIP_WALK = {".git", "releases", "worldstip-out", "__pycache__",
             ".pytest_cache", ".mypy_cache", "expert"}

results = []


def ck(name, ok, detail=""):
    results.append({"item": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print("  %s  %-42s %s" % ("PASS" if ok else "FAIL", name, detail if not ok else ""))
    return bool(ok)


def _read(rel):
    with open(os.path.join(ROOT, rel.replace("/", os.sep)), encoding="utf-8") as f:
        return f.read()


def check_version():
    v = json.loads(_read("VERSION.json"))["version"]
    bad = []
    for rel in VERSION_FILES:
        p = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            bad.append(rel + "(缺文件)")
            continue
        s = open(p, encoding="utf-8").read()
        # 当前版本必须以 v0.2.22 / 0.2.22 / "0.2.22" 形式出现；CHANGELOG 只需含标题行
        if rel == "CHANGELOG.md":
            ok = bool(re.search(r"^##\s*v?" + re.escape(v), s, re.M))
        else:
            ok = (v in s)
        if not ok:
            bad.append(rel)
    ck("版本真源：%s 全文件对齐" % v, not bad, ", ".join(bad))


def check_structure():
    deep, temp = [], []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = sorted(d for d in dn if d not in SKIP_WALK)
        rel = os.path.relpath(dp, ROOT).replace("\\", "/")
        if any(m == part for m in TEMP_MARK for part in rel.split("/")):
            temp.append(rel)
            continue
        for f in fn:
            r = (rel + "/" + f) if rel != "." else f
            if r.count("/") > 1:
                deep.append(r)
            if f == ".git" or any(m in f for m in TEMP_MARK):
                temp.append(r)
    ck("目录深度 <= 1（平台两级约束）", not deep, str(deep[:4]))
    ck("无临时产物 / 缓存夹带", not temp, str(temp[:4]))
    ck("SKILL.md 在包根", os.path.isfile(os.path.join(ROOT, "SKILL.md")))
    raw = open(os.path.join(ROOT, "SKILL.md"), "rb").read()
    ck("SKILL.md 纯 LF", b"\r" not in raw)


def check_frontmatter():
    raw = _read("SKILL.md")
    fm = raw.split("---", 2)[1]
    fields = {}
    for line in fm.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    miss = [k for k in FM_REQUIRED if not fields.get(k)]
    ck("frontmatter 必填 5 项", not miss, str(miss))
    d = fields.get("description", "").strip('"')
    ck("description 单行且 <= 200 字", 20 <= len(d) <= 200, "实际 %d 字" % len(d))
    ck("description 含触发词与负向边界", "触发词" in d and "不触发" in d)
    ck("allowed-tools 已声明且非空", bool(fields.get("allowed-tools", "").strip("[] ")))
    ck("license = MIT", fields.get("license") == "MIT", fields.get("license", ""))
    ck("name 与目录名一致", fields.get("name") == os.path.basename(ROOT),
       "%s vs %s" % (fields.get("name"), os.path.basename(ROOT)))


def check_scripts():
    bad = []
    n = 0
    for dp, dn, fn in os.walk(os.path.join(ROOT, "scripts")):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if not f.endswith(".py"):
                continue
            n += 1
            p = os.path.join(dp, f)
            try:
                ast.parse(open(p, encoding="utf-8").read())
            except Exception as e:
                bad.append("%s: %s" % (f, str(e)[:60]))
    ck("scripts/*.py 语法全通过（%d 个）" % n, not bad, str(bad[:3]))


def check_data():
    bad = []
    n = 0
    for dp, dn, fn in os.walk(os.path.join(ROOT, "references")):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if not f.endswith(".json"):
                continue
            n += 1
            rel = "references/" + f
            try:
                d = json.load(open(os.path.join(dp, f), encoding="utf-8"))
                floor = KEY_DATA.get(rel)
                if floor:
                    arr = d.get("places") or d.get("destinations") or d.get("items") or []
                    if isinstance(d, dict) and not arr and "items" in d:
                        arr = d["items"]
                    cnt = len(arr) if isinstance(arr, (list, dict)) else 0
                    if cnt < floor:
                        bad.append("%s 条目 %d < %d" % (rel, cnt, floor))
            except Exception as e:
                bad.append("%s: %s" % (f, str(e)[:60]))
    ck("references/*.json 可解析且条目达标（%d 个）" % n, not bad, str(bad[:3]))


def check_refs():
    missing = []
    pat = re.compile(r"`((?:scripts|references|docs|tools|examples|fixtures|test|tests)/[^`\s]+\.[A-Za-z0-9]+)`")
    for doc in ("SKILL.md", "README.md", "INSTALL.md", "DoD.md"):
        p = os.path.join(ROOT, doc)
        if not os.path.isfile(p):
            continue
        for rel in pat.findall(open(p, encoding="utf-8").read()):
            if "*" in rel:
                continue
            if not os.path.isfile(os.path.join(ROOT, rel.replace("/", os.sep))):
                missing.append(doc + "->" + rel)
    ck("文档反引号引用无幽灵", not missing, str(missing[:5]))


def check_smoke():
    """同进程冒烟：复用 worldstip.py 的 main 契约，不启动子进程。"""
    script = os.path.join(HERE, "worldstip.py")
    cases = [
        ("放行", ["从岳阳出发，周末去张家界爬山看日出，2天1晚",
                  "--dir", os.path.join(os.path.dirname(ROOT), "_m030", "doctor-smoke"),
                  "--json"], 0),
        ("拦截", ["帮我写一份本周工作总结", "--json"], 3),
        ("歧义", ["想去幕阜山爬山看日出", "--json"], 3),
    ]
    for name, argv, want in cases:
        old = sys.argv
        out, err = io.StringIO(), io.StringIO()
        code = -1
        try:
            sys.argv = [script] + argv
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    runpy.run_path(script, run_name="__main__")
                except SystemExit as e:
                    code = 0 if e.code is None else (e.code if isinstance(e.code, int) else 1)
        except Exception as e:
            err.write("%s: %s" % (type(e).__name__, e))
        finally:
            sys.argv = old
        ok = code == want
        detail = "" if ok else "rc=%s want=%d %s" % (code, want, err.getvalue()[:100])
        ck("统一入口冒烟：%s" % name, ok, detail)


def check_lexicon(path):
    if not path:
        print("  SKIP 外部词表扫描（未注入 --lexicon，本项不声称通过）")
        return
    words = [w.strip() for w in open(path, encoding="utf-8").read().splitlines()
             if w.strip() and not w.startswith("#")]
    hits = []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in ("__pycache__", ".git")]
        for f in fn:
            if not f.endswith((".md", ".json", ".py", ".txt", ".html")):
                continue
            s = open(os.path.join(dp, f), encoding="utf-8", errors="ignore").read()
            for w in words:
                if w in s:
                    hits.append("%s:%s" % (f, w))
    ck("外部词表零命中（%d 词）" % len(words), not hits, str(hits[:6]))


def main():
    ap = argparse.ArgumentParser(description="WorldsTip 离线自检")
    ap.add_argument("--lexicon", default="", help="可选：外部词表文件（每行一个词）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--no-smoke", action="store_true", help="跳过实跑冒烟")
    a = ap.parse_args()

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        check_version()
        check_structure()
        check_frontmatter()
        check_scripts()
        check_data()
        check_refs()
        if not a.no_smoke:
            check_smoke()
        check_lexicon(a.lexicon)
    report = buf.getvalue()

    passed = sum(1 for r in results if r["ok"])
    failed = [r for r in results if not r["ok"]]
    if a.json:
        print(json.dumps({"version": json.loads(_read("VERSION.json"))["version"],
                          "total": len(results), "passed": passed,
                          "failed": len(failed), "items": results},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 68)
        print("WorldsTip 离线自检 · v%s" % json.loads(_read("VERSION.json"))["version"])
        print("=" * 68)
        print(report, end="")
        print("-" * 68)
        print("合计 %d 项：通过 %d / 失败 %d" % (len(results), passed, len(failed)))
        print("DOCTOR: %s" % ("PASS" if not failed else "FAIL"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
