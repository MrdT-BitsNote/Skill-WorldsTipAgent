#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.2.22 统一回归总入口：一条命令跑完所有既有套件 + 新增机制用例。

    python tests/run_all.py            # 任一失败 EXIT 1
    python tests/run_all.py --json     # 机器可读结果

既有套件（来自 A/B/S，原样保留其判据，不因合并放宽）：
  tests/run_tests.py              行程编排回归
  tests/test_visa_gate_merged.py  灰灯专项
  tests/test_logic_fixes.py       逻辑反例
  tests/test_fusion.py            融合专项（基线已改为实读 description）
  test/run_all.py                 数据引擎边界验证集
  scripts/test_*.py               12 个脚本级回归

新增机制用例在本文件内直接断言，覆盖：负向闸门、地名抽取、跨省同名、
锚点锁定、人文 sidecar、版本真源、双渲染、manifest 可复核性。
每条关键判据都配一个「该失败」的负向夹具，确认判据真的拦得住。
"""
from __future__ import print_function

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

SUITES = [
    ("行程编排回归", "tests/run_tests.py"),
    ("灰灯专项", "tests/test_visa_gate_merged.py"),
    ("逻辑反例", "tests/test_logic_fixes.py"),
    ("融合专项", "tests/test_fusion.py"),
    ("数据引擎边界验证集", "test/run_all.py"),
]

UNIT = []
_FAILED_UNIT = []


def ck(name, cond, detail=""):
    UNIT.append({"name": name, "ok": bool(cond), "detail": str(detail)[:160]})
    if not cond:
        _FAILED_UNIT.append(name)
    print("  %s  %-58s %s" % ("PASS" if cond else "FAIL", name,
                              "" if cond else detail))


def run_suites():
    out = []
    for name, rel in SUITES:
        p = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            out.append({"suite": name, "exit": 127, "tail": "文件不存在 " + rel})
            continue
        try:
            r = subprocess.run([sys.executable, "-B", p], cwd=ROOT,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=300)
            tail = " | ".join((r.stdout + r.stderr).strip().splitlines()[-3:])
            out.append({"suite": name, "exit": r.returncode, "tail": tail[:300]})
        except Exception as e:
            out.append({"suite": name, "exit": 1, "tail": str(e)[:200]})
    # 12 个脚本级回归（B 版资产）
    sd = os.path.join(ROOT, "scripts")
    for f in sorted(os.listdir(sd)):
        if not (f.startswith("test_") and f.endswith(".py")):
            continue
        p = os.path.join(sd, f)
        try:
            r = subprocess.run([sys.executable, "-B", p], cwd=ROOT,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=180)
            tail = " | ".join((r.stdout + r.stderr).strip().splitlines()[-2:])
            out.append({"suite": "脚本级 " + f, "exit": r.returncode, "tail": tail[:240]})
        except Exception as e:
            out.append({"suite": "脚本级 " + f, "exit": 1, "tail": str(e)[:160]})
    return out


def run_units():
    import intent_guard
    import geo_extract
    import history_query

    print("\n=== 新增机制：正向用例 ===")
    for text in ("从岳阳出发，周末去张家界爬山看日出", "骑摩托从岳阳去凤凰古城，3天",
                 "桂林3天怎么玩", "周末想去哪玩，2天1晚"):
        v, _, _ = intent_guard.judge(text)
        ck("放行出行请求：" + text[:20], v == "pass", v)

    print("\n=== 新增机制：负向夹具（必须证红）===")
    for text in ("帮我写一份本周工作总结", "帮我重构这段 Python 代码",
                 "帮我安排一下", "做一份财务报表"):
        v, _, _ = intent_guard.judge(text)
        ck("拦截非出行：" + text[:20], v == "reject", v)
    v, _, _ = intent_guard.judge("")
    ck("拦截空输入", v == "reject", v)
    # 覆盖边界：本版国内单模式，境外请求要明确说明而不是含糊拒绝
    import route as router
    v2, reason2, _ = intent_guard.judge("想去日本玩5天", getattr(router, "OUTBOUND_HINT", ()))
    ck("境外请求拒绝且理由明确", v2 == "reject" and "境外" in reason2, reason2)
    # 规则缺口回归：带出行参数但无玩法动词，须靠权威地名放行；无地名则仍拦
    _q = "从岳阳出发到张家界，2天1晚"
    _g = geo_extract.extract(_q)
    v3, r3, _ = intent_guard.judge(_q, getattr(router, "OUTBOUND_HINT", ()), _g["to"])
    ck("参数+权威地名共现放行", v3 == "pass" and _g["to"] == "张家界", "%s %s" % (v3, _g["to"]))
    v4, _, _ = intent_guard.judge("从某地出发到某处，2天1晚", (), "")
    ck("同结构但无权威地名仍拦", v4 == "reject", v4)

    print("\n=== 地名抽取 / 消歧 ===")
    r = geo_extract.extract("从岳阳出发，周末去张家界爬山看日出")
    ck("出发地=岳阳", r["from_city"] == "岳阳", r["from_city"])
    ck("目的地=张家界", r["to"] == "张家界", r["to"])
    r2 = geo_extract.extract("想去幕阜山爬山看日出")
    ck("跨省同名不硬判", r2["confidence"] == "ambiguous" and not r2["to"], str(r2["confidence"]))
    ck("候选 >= 5 条", len(r2["ambiguous"]["candidates"]) >= 5,
       str(len(r2["ambiguous"]["candidates"])))
    r3 = geo_extract.extract("想去幕阜山看日出，平江县南江镇那边")
    ck("锚点锁定后收敛到单一候选", r3["ambiguous"]["locked"] and bool(r3["to"]), str(r3["to"]))
    # 反向：给了 --to 就应当直接采信，不再问
    r4 = geo_extract.extract("想去幕阜山", explicit_to="九宫山")
    ck("显式 --to 优先且不再询问", r4["to"] == "九宫山" and r4["ambiguous"] is None, str(r4["to"]))

    print("\n=== 人文 sidecar / 版本真源 / 契约 ===")
    h = history_query.query("张家界", contains=True, max_items=3)
    ck("人文史索引 >= 1000 条", h["total_indexed"] >= 1000, str(h["total_indexed"]))
    ck("人文史查询命中", h["found"], str(h["matched"]))
    h2 = history_query.query("火星上不存在的地名XYZ")
    ck("查不到如实 found=false", not h2["found"])
    ver = json.load(open(os.path.join(ROOT, "VERSION.json"), encoding="utf-8"))["version"]
    ck("版本真源符合 x.y.z 格式", len(ver.split(".")) == 3
       and all(x.isdigit() for x in ver.split(".")), ver)
    fm = open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8").read().split("---", 2)[1]
    ck("SKILL.md 版本与真源一致", ("version: " + ver) in fm)
    mp = os.path.join(ROOT, "references", "moto_places.json")
    md = json.load(open(mp, encoding="utf-8"))
    ck("主数据不含 his（sidecar 隔离生效）",
       all(not p.get("his") for p in md.get("places", [])[:50]))

    print("\n=== 统一入口产物契约（同进程实跑）===")
    import contextlib
    import io
    import runpy
    script = os.path.join(ROOT, "scripts", "worldstip.py")
    outdir = os.path.join(os.path.dirname(ROOT), "_m030", "regression")
    for name, argv, want in (
        ("放行", ["从岳阳出发，周末去张家界爬山看日出，2天1晚", "--dir", outdir, "--json"], 0),
        ("拦截", ["帮我写一份本周工作总结", "--json"], 3),
        ("歧义", ["想去幕阜山爬山看日出", "--json"], 3),
        ("增强渲染", ["从岳阳出发去张家界爬山，2天1晚", "--rich",
                    "--dir", os.path.join(os.path.dirname(ROOT), "_m030", "regression-rich"),
                    "--json"], 0),
    ):
        old, buf, err = sys.argv, io.StringIO(), io.StringIO()
        code = -1
        try:
            sys.argv = [script] + argv
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                try:
                    runpy.run_path(script, run_name="__main__")
                except SystemExit as e:
                    code = 0 if e.code is None else (e.code if isinstance(e.code, int) else 1)
        except Exception as e:
            err.write(str(e))
        finally:
            sys.argv = old
        ck("统一入口 %s → EXIT %d" % (name, want), code == want,
           "rc=%s %s" % (code, err.getvalue()[:100]))
    mf = os.path.join(outdir, "manifest.json")
    ck("manifest 落盘", os.path.isfile(mf))
    if os.path.isfile(mf):
        m = json.load(open(mf, encoding="utf-8"))
        ck("manifest 逐步记录退出码/耗时", all("exit" in s and "seconds" in s for s in m["steps"]))
        ck("manifest 产物字节可复核", m["outputs"].get("小册子.html", 0) > 5000,
           str(m["outputs"]))
        ck("manifest 声明离线默认", m.get("offline_default") is True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        suites = run_suites()
        print("\n=== 新增机制单元用例 ===")
        run_units()
    report = buf.getvalue()

    suite_fail = [s for s in suites if s["exit"] != 0]
    unit_pass = len(UNIT) - len(_FAILED_UNIT)
    ok = not suite_fail and not _FAILED_UNIT
    if a.json:
        _ver = json.load(open(os.path.join(ROOT, "VERSION.json"), encoding="utf-8"))["version"]
        print(json.dumps({"version": _ver, "ok": ok,
                          "suites_total": len(suites),
                          "suites_pass": len(suites) - len(suite_fail),
                          "units_total": len(UNIT), "units_pass": unit_pass,
                          "failed_suites": suite_fail,
                          "failed_units": _FAILED_UNIT,
                          "suites": suites}, ensure_ascii=False, indent=2))
    else:
        print(report, end="")
        print("=" * 72)
        for s in suites:
            print("  %s  %-34s EXIT %d  %s" % ("PASS" if s["exit"] == 0 else "FAIL",
                                               s["suite"], s["exit"], s["tail"][:90]))
        print("-" * 72)
        print("套件 %d/%d 通过 | 新增用例 %d/%d 通过" %
              (len(suites) - len(suite_fail), len(suites), unit_pass, len(UNIT)))
        print("REGRESSION: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
