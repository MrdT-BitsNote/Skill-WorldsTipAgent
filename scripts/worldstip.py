#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""worldstip.py — v0.2.22 统一入口（ONE COMMAND）

把 v0.2.x 需要人工串起来的 4~5 条命令收敛成一条：
    route(参数解析) -> build_itinerary -> plan_transit -> [check_weather] -> render

设计要点（相对 A/B 两个版本的增量）：
  1. 负向闸门前置：非出行请求在此被确定性拦下，不再回落 domestic 生成废册子。
  2. 同进程编排：用 runpy 复用各脚本既有 CLI 契约，不新造一套 API，
     也不启动 4 次解释器，冷启动开销从 N 次降为 1 次。
  3. 每步可验证：输出 manifest.json，逐记录退出码、耗时、产物字节与参数，
     不做「看起来成功」的静默降级。
  4. 离线优先：天气默认不跑（需联网且波动），--with-weather 显式开启；
     全程无网络时仍可产出完整册子。
  5. 双渲染：默认紧凑卡册（快/小）；--rich 切 9 风格增强渲染器。
  6. 纯标准库、零第三方依赖、零子进程、零写死路径。

退出码：0 成功 / 2 参数错误 / 3 非出行请求被拦 / 4 链路步骤失败。
"""
from __future__ import print_function

import argparse
import contextlib
import io
import json
import os
import runpy
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import intent_guard  # noqa: E402
import route as router  # noqa: E402
import geo_extract  # noqa: E402


def _script(name):
    return os.path.join(HERE, name)


def _run(name, argv):
    """同进程执行一个既有脚本，返回 (exit_code, stdout, stderr, seconds)。

    用 runpy 以 __main__ 身份运行，保留各脚本原有 argparse / main 契约；
    捕获 SystemExit 以免某一步终止整条链路；stdout/stderr 各自收集，
    便于把 JSON 产物原样落盘、把诊断信息写进 manifest。
    """
    path = _script(name)
    if not os.path.isfile(path):
        return 127, "", "缺少脚本 %s" % name, 0.0
    out, err = io.StringIO(), io.StringIO()
    old_argv = sys.argv
    code = 0
    t0 = time.time()
    try:
        sys.argv = [path] + [str(x) for x in argv]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                runpy.run_path(path, run_name="__main__")
            except SystemExit as e:
                c = e.code
                code = 0 if c is None else (c if isinstance(c, int) else 1)
    except Exception as e:
        code = 1
        err.write("%s: %s" % (type(e).__name__, e))
    finally:
        sys.argv = old_argv
    return code, out.getvalue(), err.getvalue(), round(time.time() - t0, 3)


def _parse(text, a, geo=None):
    """复用 route.py 的确定性解析器 + 新增地名抽取，不重复实现推断逻辑。"""
    main_i, addons, is_out = router.classify(text, a.to or None)
    geo = geo if geo is not None else geo_extract.extract(text, a.to or "", a.frm or "")
    days = a.days or router.detect_days(text)
    people = a.people or router.detect_people(text)
    comp = a.composition or router.detect_composition(text, people)
    style = a.style or router.pick_style(main_i, addons, "")
    return {
        "intent": main_i, "addons": addons, "is_outbound": is_out,
        "to": geo["to"], "days": days, "people": people,
        "composition": comp, "style": style,
        "from": geo["from_city"] or a.frm or "",
        "geo": {"confidence": geo["confidence"], "matched_via": geo["matched_via"],
                "candidates": geo["candidates"], "ambiguous": geo["ambiguous"]},
    }


def main():
    ap = argparse.ArgumentParser(
        description="WorldsTip 统一入口：一句话生成可直接照着走的行程小册子")
    ap.add_argument("text", nargs="?", default="", help="用户原话 / 出行需求")
    ap.add_argument("--from", dest="frm", default="", help="出发地")
    ap.add_argument("--to", default="", help="目的地（不填则从原话推断）")
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--people", type=int, default=0)
    ap.add_argument("--composition", default="")
    ap.add_argument("--style", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--out", default="", help="输出 HTML 路径")
    ap.add_argument("--dir", default="", help="产物目录（默认 ./worldstip-out）")
    ap.add_argument("--rich", action="store_true", help="启用 9 风格增强渲染器")
    ap.add_argument("--rich-style", default="apple", help="增强渲染风格")
    ap.add_argument("--variant", choices=["full", "light"], default="full")
    ap.add_argument("--feasibility", choices=["none", "advisory", "strict"],
                    default="advisory", help="可执行性体检档位")
    ap.add_argument("--with-weather", action="store_true", help="显式开启联网天气预检")
    ap.add_argument("--json", action="store_true", help="仅输出结构化结果")
    a = ap.parse_args()

    # ---- 0/1. 闸门与地名抽取协同 ----------------------------------------
    # 先取权威地名结果，再把它作为闸门的一个输入信号：避免「带天数但没有玩法动词」
    # 的口语请求（如「从岳阳出发到张家界，2天1晚」）被误拒。
    geo = geo_extract.extract(a.text, a.to or "", a.frm or "")
    verdict, reason, hits = intent_guard.judge(
        a.text, getattr(router, "OUTBOUND_HINT", ()), geo["to"])
    if verdict != "pass":
        res = {"ok": False, "stage": "intent_guard", "verdict": "reject",
               "reason": reason, "hits": hits,
               "hint": "本技能只处理出行规划。文档写作、代码、报表等请直接使用通用能力。"}
        print(json.dumps(res, ensure_ascii=False, indent=2) if a.json
              else "[REJECT] %s\n%s" % (reason, res["hint"]))
        return 3

    # ---- 2. 参数解析（复用路由） ----------------------------------------
    p = _parse(a.text, a, geo)
    # 跨省同名地名：先列候选，请用户选定后再生成，绝不静默挑一个。
    amb = p["geo"]["ambiguous"]
    if amb and not amb["locked"]:
        res = {"ok": False, "stage": "disambiguate", "verdict": "need_choice",
               "name": amb["name"], "hit": amb["hit"],
               "reason": "「%s」为跨省同名地名，需先确认具体所指" % amb["name"],
               "candidates": amb["candidates"], "hint": amb["hint"],
               "next": "请用 --to 指定上列候选之一，或补充县名/镇名作为锚点"}
        print(json.dumps(res, ensure_ascii=False, indent=2) if a.json
              else "[NEED_CHOICE] %s\n候选：%s" %
              (res["reason"], "、".join(str(c["name"]) for c in amb["candidates"])))
        return 3
    if not p["to"]:
        res = {"ok": False, "stage": "parse", "reason": "未能从原话识别目的地，请用 --to 指定",
               "geo": p["geo"]}
        print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else "[ERROR] " + res["reason"])
        return 2

    outdir = os.path.abspath(a.dir or os.path.join(os.getcwd(), "worldstip-out"))
    os.makedirs(outdir, exist_ok=True)
    plan = os.path.join(outdir, "plan.json")
    transit = os.path.join(outdir, "transit.json")
    weather = os.path.join(outdir, "weather.json")
    research = os.path.join(outdir, "research.json")
    html = os.path.abspath(a.out) if a.out else os.path.join(outdir, "小册子.html")
    title = a.title or ("%s %s日行程" % (p["to"], p["days"] or 2))

    with open(research, "w", encoding="utf-8") as f:
        json.dump({"ugc": []}, f, ensure_ascii=False)

    manifest = {
        "version": "0.2.27", "engine": "worldstip.py", "offline_default": True,
        "input": a.text, "parsed": p, "steps": [], "outputs": {},
    }

    def step(name, argv, outfile=None, allow_fail=False):
        code, so, se, dt = _run(name, argv)
        rec = {"script": name, "argv": [str(x) for x in argv],
               "exit": code, "seconds": dt,
               "stdout_bytes": len(so.encode("utf-8")),
               "stderr": se.strip()[:300]}
        if outfile and code == 0 and so.strip():
            with open(outfile, "w", encoding="utf-8") as f:
                f.write(so)
            rec["output"] = os.path.basename(outfile)
            rec["output_bytes"] = os.path.getsize(outfile)
            manifest["outputs"][os.path.basename(outfile)] = os.path.getsize(outfile)
        manifest["steps"].append(rec)
        return code if not allow_fail else 0

    # ---- 2. 行程编排 ----------------------------------------------------
    bi = ["--from", p["from"] or "本地", "--to", p["to"],
          "--days", str(p["days"] or 2), "--people", str(p["people"] or 1),
          "--composition", p["composition"] or "独自一人",
          "--style", p["style"], "--json",
          "--hint", a.text, "--tag", p["style"]]
    if step("build_itinerary.py", bi, plan):
        return _finish(manifest, outdir, a, ok=False, code=4)

    # ---- 3. 交通比选 ----------------------------------------------------
    if step("plan_transit.py", ["--from", p["from"] or "本地", "--to", p["to"], "--json"], transit):
        return _finish(manifest, outdir, a, ok=False, code=4)

    # ---- 4. 天气（显式开启，失败仅记录不中断） --------------------------
    weather_ok = False
    if a.with_weather:
        c = step("check_weather.py", ["--to", p["to"], "--style", p["style"],
                                      "--days", str(p["days"] or 2), "--json"], weather)
        weather_ok = (c == 0 and os.path.getsize(weather) > 2) if os.path.exists(weather) else False
        manifest["weather_live"] = weather_ok

    # ---- 5. 渲染 --------------------------------------------------------
    if a.rich:
        rv = ["--plan", plan, "--transit", transit, "--research", research,
              "--out", html, "--title", title, "--style", a.rich_style,
              "--variant", a.variant, "--feasibility", a.feasibility]
        if weather_ok:
            rv += ["--weather", weather]
        renderer = "render_booklet.py"
    else:
        rv = ["--plan", plan, "--transit", transit, "--research", research,
              "--out", html, "--title", title, "--feasibility", a.feasibility]
        renderer = "render_compact.py"
    rc = step(renderer, rv)

    ok = (rc == 0 and os.path.isfile(html) and os.path.getsize(html) > 0)
    manifest["renderer"] = renderer
    manifest["outputs"]["小册子.html"] = os.path.getsize(html) if os.path.isfile(html) else 0
    return _finish(manifest, outdir, a, ok=ok, code=0 if ok else 4)


def _finish(manifest, outdir, a, ok, code):
    mp = os.path.join(outdir, "manifest.json")
    manifest["ok"] = ok
    manifest["html"] = os.path.join(outdir, "小册子.html") if not a.out else os.path.abspath(a.out)
    manifest["elapsed_seconds"] = round(sum(s["seconds"] for s in manifest["steps"]), 3)
    manifest["steps_count"] = len(manifest["steps"])
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    if a.json:
        print(json.dumps({"ok": ok, "html": manifest["html"], "manifest": mp,
                          "steps": manifest["steps_count"],
                          "elapsed_seconds": manifest["elapsed_seconds"],
                          "outputs": manifest["outputs"],
                          "parsed": manifest["parsed"]}, ensure_ascii=False, indent=2))
    else:
        print("[OK] %s" % manifest["html"] if ok else "[FAIL] 链路未产出成品，详见 %s" % mp)
        print("     steps=%d  elapsed=%ss  outputs=%s" %
              (manifest["steps_count"], manifest["elapsed_seconds"], manifest["outputs"]))
    return code


if __name__ == "__main__":
    sys.exit(main())
