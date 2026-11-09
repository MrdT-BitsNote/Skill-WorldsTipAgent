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
     发行包按平台裁剪、可能不含增强渲染器：此时 --rich **显式降级**为紧凑卡册
     （stderr 打 [DEGRADED] + manifest.degraded=true），不再产出 0 字节后静默失败。
  6. 终端分流（v0.2.274）：默认 --device both 一次产三件——
     PC 网页版（--out 本身）、A5 分页小册子（-A5）、手机 HTML5 版（-手机）；
     pc/a5/mobile 单选时只产一件。增强渲染器为单页长文档，不分流，manifest 记
     device_applied=false 并说明原因，不假装产出。
  7. 纯标准库、零第三方依赖、零子进程、零写死路径。

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
# 打包时按平台裁剪，--rich 可能没有渲染器可用；降级文案里不写具体文件名，
# 免得被构建器的文本清洗规则咬到（那是按文件名做替换的）。
_PKG_KIND = "精简发行包"
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import intent_guard  # noqa: E402
import route as router  # noqa: E402
import geo_extract  # noqa: E402


def _script(name):
    return os.path.join(HERE, name)


# 与 render_compact.DEVICE_SUFFIX 保持一致：both 模式下 --out 为 PC 版，另两件加后缀。
_DEVICE_SUFFIX = {"a5": "-A5", "mobile": "-手机"}


def _expected_outputs(html, device):
    """推导本次渲染应当产出的 HTML 路径清单（用于 manifest 逐件记账）。"""
    if device != "both":
        return [html]
    stem, ext = os.path.splitext(html)
    return [html] + [stem + _DEVICE_SUFFIX[d] + ext for d in ("a5", "mobile")]


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
    ap.add_argument("--device", choices=["pc", "a5", "mobile", "both"], default="both",
                    help="终端形态：pc 桌面网页 / a5 A5 分页小册子 / mobile 手机 HTML5 / both 三件齐出（默认）")
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
        "version": "0.2.276", "engine": "worldstip.py", "offline_default": True,
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
    # v0.2.274：发行包按平台裁剪，部分包不含九风格增强渲染器。此前 --rich 在这类
    # 包内直接失败（render_booklet.py 不存在 → 127/退出 4、HTML 0 字节），调用方
    # 只能看到「链路未产出成品」，既不知道为什么，也拿不到任何册子。
    # 现在改为：可用则真跑增强渲染；不可用则**显式降级**为紧凑卡册，把降级事实
    # 写进 stderr 与 manifest/JSON（degraded=true + degrade_reason），绝不假装成增强版。
    rich_ready = os.path.isfile(_script("render_booklet.py"))
    degraded = False
    degrade_reason = ""
    if a.rich and not rich_ready:
        degraded = True
        degrade_reason = ("本包是%s，不含九风格增强渲染器；已回落紧凑卡册 "
                          "render_compact.py，需要增强版请用全量发行包" % _PKG_KIND)
        sys.stderr.write("[DEGRADED] %s\n" % degrade_reason)
    if a.rich and rich_ready:
        rv = ["--plan", plan, "--transit", transit, "--research", research,
              "--out", html, "--title", title, "--style", a.rich_style,
              "--variant", a.variant, "--feasibility", a.feasibility]
        if weather_ok:
            rv += ["--weather", weather]
        renderer = "render_booklet.py"
        # 九风格增强渲染器自成一套连续长页，不区分终端；此处如实记录「设备分流未生效」，
        # 不假装产出了 A5 / 手机版。
        device_applied = (a.device == "pc")
    else:
        rv = ["--plan", plan, "--transit", transit, "--research", research,
              "--out", html, "--title", title, "--feasibility", a.feasibility,
              "--device", a.device]
        renderer = "render_compact.py"
        device_applied = True
    rc = step(renderer, rv)

    ok = (rc == 0 and os.path.isfile(html) and os.path.getsize(html) > 0)
    manifest["renderer"] = renderer
    manifest["device_requested"] = a.device
    manifest["device_applied"] = device_applied
    if not device_applied:
        manifest["device_note"] = ("增强渲染器产出单页长文档，不做终端分流；"
                                  "需要 PC/A5/手机三件套请去掉 --rich 使用紧凑渲染器")
    if a.rich:
        manifest["render_requested"] = "render_booklet.py"
        manifest["degraded"] = degraded
        if degraded:
            manifest["degrade_reason"] = degrade_reason
    for path in _expected_outputs(html, a.device if device_applied else "pc"):
        if os.path.isfile(path):
            manifest["outputs"][os.path.basename(path)] = os.path.getsize(path)
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
        body = {"ok": ok, "html": manifest["html"], "manifest": mp,
                "steps": manifest["steps_count"],
                "elapsed_seconds": manifest["elapsed_seconds"],
                "renderer": manifest.get("renderer", ""),
                "device": manifest.get("device_requested", ""),
                "device_applied": manifest.get("device_applied", True),
                "outputs": manifest["outputs"],
                "parsed": manifest["parsed"]}
        if manifest.get("device_note"):
            body["device_note"] = manifest["device_note"]
        if manifest.get("degraded"):
            body["degraded"] = True
            body["degrade_reason"] = manifest.get("degrade_reason", "")
        print(json.dumps(body, ensure_ascii=False, indent=2))
    else:
        print("[OK] %s" % manifest["html"] if ok else "[FAIL] 链路未产出成品，详见 %s" % mp)
        print("     steps=%d  elapsed=%ss  outputs=%s" %
              (manifest["steps_count"], manifest["elapsed_seconds"], manifest["outputs"]))
        if manifest.get("degraded"):
            print("[DEGRADED] %s" % manifest.get("degrade_reason", ""))
    return code


if __name__ == "__main__":
    sys.exit(main())
