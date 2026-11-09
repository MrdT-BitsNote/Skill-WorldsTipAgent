#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.2.1 逻辑缺陷回归断言（纯 stdlib）：每条对应一个已修的真实错判。

这些错判的共同特征：**静态检查全绿、lint A/100 也看不出来**，只有把真实输入
喂进判定函数才会暴露。所以这里的写法是「反例优先」——每条都先写下当年判错的原话。
任一失败 EXIT 1。
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "fixtures"
sys.path.insert(0, str(SCRIPTS))

N = 0
FAIL = []


def ck(ok, label):
    global N
    N += 1
    if not ok:
        FAIL.append(label)
    print(("  PASS " if ok else "  FAIL ") + label)


def _route_json(text):
    r = subprocess.run([sys.executable, str(SCRIPTS / "route.py"), text, "--json"],
                       capture_output=True, text=True, encoding="utf-8", timeout=90)
    return json.loads(r.stdout)


def _cmd_arg(cmd, flag):
    m = re.search(r"--%s\s+(\S+)" % flag, cmd)
    return m.group(1).strip('"') if m else ""


def main():
    import route
    import motofun
    from feasibility import run_feasibility

    print("[L1] 拉丁短词不得子串误命中（E1）")
    for bad in ("any advice for Tokyo trip", "please advance the booking",
                "adventure trip plan"):
        main_i, _, _ = route.classify(bad)
        ck(main_i != "moto", f"「{bad}」不得判摩旅（实得 {main_i}）")
    main_i, _, _ = route.classify("adv 车型适合长途吗")
    ck(main_i == "moto", "单独词 adv 仍应判摩旅")

    print("[L2] 自行车不得被判摩旅（E2）")
    m, a, _ = route.classify("环青海湖骑行怎么安排")
    ck(m != "moto" and "cycling" in a, f"环青海湖骑行 -> cycling（实得 {m}/{a}）")
    ck(route.pick_style(m, a, None) == "cycling", "环青海湖骑行 style=cycling")
    m2, a2, _ = route.classify("骑摩托车环湖")
    ck(m2 == "moto", f"骑摩托车环湖仍是 moto（实得 {m2}/{a2}）")
    ck(route.pick_style(m2, a2, None) == "moto",
       f"主意图强画像不被附加意图覆盖（实得 {route.pick_style(m2, a2, None)}）")

    print("[L3] 日期不得被当天数（E3）")
    ck(route.detect_days("10月3日出发去成都") == "", "单日期不推断天数")
    ck(route.detect_days("帮我订10月3日的房") == "", "订房日期不推断天数")
    ck(route.detect_days("10月3日-10月6日去成都") == "4", "日期区间跨度为 4 天")
    ck(route.detect_days("12月30日-1月2日") == "4", "跨年区间跨度为 4 天")
    ck(route.detect_days("3天2晚去成都") == "3", "显式天数优先")
    ck(route.detect_days("10月3日出发玩3天") == "3", "日期旁有显式天数取天数")
    ck(route.detect_days("骑摩托从岳阳去凤凰古城，3天") == "3", "既有正例不回退")

    print("[L4] 人员构成不得硬编码、假设必须外显（E4）")
    p = route.detect_people("和老婆两个人玩三天")
    c = route.detect_composition("和老婆两个人玩三天", p)
    ck(p == "2" and c == "情侣", f"老婆+两人 -> 2/情侣（实得 {p}/{c}）")
    p2 = route.detect_people("一家三口玩4天")
    ck(route.detect_composition("一家三口玩4天", p2) == "三口", "一家三口 -> 三口")
    j = _route_json("3天2晚去成都")
    ck("独自一人" not in j["steps"][0]["cmd"], "未指定构成时不得写死「独自一人」")
    ck(bool(j.get("assumptions")), "估算必须写进 assumptions")
    j2 = _route_json("10月3日-10月6日和老婆去成都")
    cmd = j2["steps"][0]["cmd"]
    ck(_cmd_arg(cmd, "days") == "4" and _cmd_arg(cmd, "people") == "2",
       f"全信息原话参数正确（实得 {_cmd_arg(cmd,'days')}/{_cmd_arg(cmd,'people')}）")
    ck(j2.get("assumptions") == [], "全信息原话不留假设")

    print("[L5] 摩旅路由不得兜底假阳性（E5）")
    for bad in ("你好", "帮我写一份周报", "明天股票会涨吗", "推荐一部电影"):
        ck(motofun.cmd_route(bad)["intent"] == "none",
           f"「{bad}」-> none（实得 {motofun.cmd_route(bad)['intent']}）")
    ck(motofun.cmd_route("我骑自行车去重庆")["intent"] == "none", "骑自行车 -> none")
    # 既有正例：T9 期望表不得因本次改动回退
    for t, exp in (("摩旅路线吃什么", "cascade"), ("moto 路线", "routes"),
                   ("环青海湖住宿", "cascade"), ("环境不错，附近有什么吃的", "city"),
                   ("全国美食榜", "rank"), ("这个技能有哪些数据", "stats")):
        ck(motofun.cmd_route(t)["intent"] == exp, f"正例「{t}」-> {exp}")

    print("[L6] 末班船断言不得拿末班车时间比对（E6/E7）")
    p_car_first = {"origin": "宜昌", "destinations": ["三峡人家"], "plan": [
        {"day": 1, "city": "三峡人家", "spots": 1,
         "slots": [{"time": "09:00", "label": "游",
                    "desc": "末班车 18:00 返回市区，末班船 17:30 停运"}]}]}
    ck(run_feasibility(p_car_first)["assert"] == [], "末班车在前不得报假冲突")
    p_wrong = {"origin": "宜昌", "destinations": ["三峡人家"], "plan": [
        {"day": 1, "city": "三峡人家", "spots": 1,
         "slots": [{"time": "09:00", "label": "游", "desc": "末班船 18:00 停运"}]}]}
    ck(len(run_feasibility(p_wrong)["assert"]) == 1, "末班船错值仍须报冲突")
    # 时刻越界
    p_bad_time = {"plan": [{"day": 1, "spots": 1,
                            "slots": [{"time": "2100", "label": "x", "desc": "y"}]}]}
    ck(run_feasibility(p_bad_time)["threshold"] == [], "HHMM 写法不得输出「2100:00」")
    p_late = {"plan": [{"day": 1, "spots": 1,
                        "slots": [{"time": "23:30", "label": "x", "desc": "y"}]}]}
    ck(len(run_feasibility(p_late)["threshold"]) == 1, "23:30 仍须报末段偏晚")

    print("[L8] 高反判据须显式契约、不得猜海拔（E8）")
    p_hi = {"plan": [{"day": 1, "spots": 1, "slots": []}], "max_altitude_m": 3650}
    ck(len(run_feasibility(p_hi)["threshold"]) == 1, "海拔 3650 且 1 天须报高反提示")
    p_lo = {"plan": [{"day": 1, "spots": 1, "slots": []}], "max_altitude_m": 800}
    ck(run_feasibility(p_lo)["threshold"] == [], "海拔 800 不得报高反")
    p_none = {"plan": [{"day": 1, "spots": 1, "slots": []}]}
    ck(run_feasibility(p_none)["threshold"] == [], "未给海拔即不判、不猜")

    print("[L9] 版本号与文档契约")
    sk = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    # 版本号从 frontmatter 现读：写死字面量会让每次升版都误报（v0.2.2 就踩过），
    # 断言要锁的是「三处一致」——frontmatter / 正文声明 / CHANGELOG 条目。
    _m = re.search(r"^version:\s*\"?([\d.]+)", sk, re.M)
    ver = _m.group(1) if _m else ""
    ck(bool(ver), "SKILL.md frontmatter 含 version")
    ck(("本地开发包版本号 = %s" % ver) in sk, "SKILL.md 正文版本线 = frontmatter %s" % ver)
    ck(("## v%s" % ver) in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
       "CHANGELOG 含 v%s 条目" % ver)
    ck("intent=none" in sk or "`none`" in sk, "SKILL.md 写明 none 的处置")
    ck("assumptions" in sk, "SKILL.md 写明 assumptions 契约")
    ck("--altitude" in sk, "SKILL.md 写明海拔显式契约")

    print("[L10] 摩旅在途里程必须来自真实距离（v0.2.274）")
    # 当年：ACTIVE_ADDON 直接取画像常量中值，两天行程各写 125km。
    # 结果「佛山→南岳衡山 直线 474km」被标成「两日骑行 125km/天」，
    # 既违背常识，也让 moto_check 的续航门禁永远不触发补油提醒。
    def _moto_plan(frm, to):
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "build_itinerary.py"),
             "--from", frm, "--to", to, "--days", "2", "--style", "moto", "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
        return json.loads(r.stdout)

    mp = _moto_plan("佛山", "南岳衡山")
    kms = [d.get("active", {}).get("km") for d in mp.get("plan", [])]
    ck(all(k and k >= 300 for k in kms),
       f"佛山→南岳衡山 两日摩旅每日里程应≥300km（实得 {kms}）")
    ck(sum(k for k in kms if k) >= 474,
       f"全程里程不得短于直线距离 474km（实得 {sum(k for k in kms if k)}）")
    ck(any("路网系数" in (d.get("active", {}).get("note") or "") for d in mp["plan"]),
       "里程来源要标明「直线 × 路网系数」，不许假装是实测")
    # 坐标查不到时仍要能跑：退回画像经验值并诚实标注
    mp2 = _moto_plan("不存在的城市名", "南岳衡山")
    kms2 = [d.get("active", {}).get("km") for d in mp2.get("plan", [])]
    ck(all(k for k in kms2), f"无坐标时仍要有里程（实得 {kms2}）")
    ck(any("画像经验值" in (d.get("active", {}).get("note") or "") for d in mp2["plan"]),
       "无坐标时必须标注为画像经验值，不得冒充真实里程")

    print("[L11] 人文史缺数据必须优雅降级（v0.2.274）")
    # 当年：WorkBuddy / 千问档为控体积不带 places_history.json，而 SKILL.md 仍指向
    # history_query.py。旧实现对文件直接 open()，用户一查历史就吃 traceback。
    import importlib
    hq = importlib.import_module("history_query")
    _real = hq.PATH
    try:
        hq.PATH = str(SCRIPTS.parent / "references" / "__不存在__.json")
        hq._CACHE = None
        ck(not hq.available(), "缺数据时 available() 应返回 False")
        r = hq.query("岳阳")           # 不得抛异常
        ck(r.get("available") is False and r.get("found") is False,
           f"缺数据应返回 available=false（实得 {r.get('available')}）")
        ck(bool(r.get("reason")), "缺数据必须给出 reason，不许静默返回空")
        # CLI 那份要单独造一个「有脚本、没数据」的临时目录来跑，
        # 否则跑的还是源码树里数据齐全的那份，永远测不出降级。
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "scripts").mkdir()
            (Path(td) / "references").mkdir()
            shutil.copy(str(SCRIPTS / "history_query.py"),
                        str(Path(td) / "scripts" / "history_query.py"))
            rr = subprocess.run(
                [sys.executable, str(Path(td) / "scripts" / "history_query.py"), "岳阳"],
                capture_output=True, text=True, encoding="utf-8", timeout=60)
        ck(rr.returncode == 2, f"CLI 缺数据应退出码 2（实得 {rr.returncode}）")
        ck("Traceback" not in (rr.stderr or ""), "缺数据不得抛 traceback")
    finally:
        hq.PATH = _real
        hq._CACHE = None

    # ── L12 时令上下文接线（v0.2.274）──────────────────────────────
    # 病根：plan_context.py 曾是可跑但无人调用的孤岛，自带一份区域归类与四季表，
    # 与 references/seasons_climate.json 两处事实源——且已漂移：西北（甘青新蒙）
    # 被 REGION_KIND 归成 plateau，敦煌拿到「高原严冬/防高反」建议。
    import plan_context as pc
    ck(pc.available() is True, "季节基线 seasons_climate.json 应可读")
    ck(pc.region_kind("敦煌", "西北") == "northwest",
       f"敦煌应归 northwest（实得 {pc.region_kind('敦煌', '西北')}）")
    ck(pc.region_kind("拉萨", "西藏") == "plateau", "拉萨按 plateau_list 归高原")
    ck(pc.region_kind("大理", "西南") == "southwest", "大理按 southwest_list 归西南城区")
    ck(pc.region_kind("三亚", "海南") == "tropical", "三亚按 tropical_list 归热带")
    ck(pc.season_word(11) == "秋" and pc.season_word(1) == "冬",
       "月份→季档 11=秋 / 1=冬")
    _a = pc.advice("south", 7)
    ck(_a["source"] == "月表", f"南方 7 月应走月表（实得 {_a['source']}）")
    ck(bool(_a.get("highlight")) and bool(_a.get("risk")),
       "月表命中也必须并上基线的当季看点/风险")
    _b = pc.advice("northwest", 7)
    ck(_b["source"] == "季节基线",
       f"西北无月表时必须走基线四季块、不得编月表（实得 {_b['source']}）")
    ck(bool(_b["climate"]) and bool(_b["tips"]), "西北基线块要给出气温与装备")

    # 基线缺失必须显式降级，不许静默
    _keep = pc.REGION_DATA
    try:
        pc.REGION_DATA = {}
        ck(pc.available() is False, "基线清空后 available() 应为 False")
        _r = pc.build(["敦煌"], {"敦煌": "西北"}, "2026-07-15", "", 0, "")
        ck(any("季节基线" in w for w in _r["warnings"]),
           "基线缺失要在 warnings 里说明，不得静默按内置常量出结论")
    finally:
        pc.REGION_DATA = _keep

    # 真正被调用：build_itinerary --date 要把 context 写进 plan，并自动补季节
    _p = subprocess.run(
        [sys.executable, str(SCRIPTS / "build_itinerary.py"),
         "--from", "佛山", "--to", "大理", "--days", "3", "--people", "2",
         "--date", "2026-07-15", "--json"],
        capture_output=True, text=True, encoding="utf-8", timeout=180)
    _j = json.loads(_p.stdout)
    _ctx = _j.get("context") or {}
    ck(bool(_ctx.get("cities")), "build_itinerary --date 必须产出 plan.context.cities")
    ck(_j.get("season") == "夏",
       f"--date 7 月应自动补 --season 为夏（实得 {_j.get('season')!r}）")
    _cv = next(iter(_ctx.get("cities", {}).values()), {})
    ck(_cv.get("region_label") == "西南城区（云贵高原低海拔）",
       f"context 应带气候区全称（实得 {_cv.get('region_label')!r}）")

    # 不给 --date 时不得凭空造季节上下文（老调用方式行为不变）
    _p2 = subprocess.run(
        [sys.executable, str(SCRIPTS / "build_itinerary.py"),
         "--from", "佛山", "--to", "大理", "--days", "3", "--people", "2", "--json"],
        capture_output=True, text=True, encoding="utf-8", timeout=180)
    _j2 = json.loads(_p2.stdout)
    ck(_j2.get("context") in (None, {}), "未给 --date 时 context 应为空，不得臆测季节")

    # ── L13 发行包裁剪后的三条硬约束（v0.2.274）────────────────────
    # 病根①：某些平台包按体积/合规裁剪，把 render_booklet.py 裁掉了，但 SKILL.md
    # 照样公开 --rich。实跑结果是 exit 4 + 0 字节 HTML，调用方只知道「失败」。
    # 现在必须显式降级：产出紧凑卡册 + 自报 degraded，不许假装跑了增强版。
    import os
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        pkg = Path(td) / "pkg"
        ignore = shutil.ignore_patterns("__pycache__", "moto_places.json",
                                        "places_history.json", "worldstip_sites.json")
        shutil.copytree(str(SCRIPTS), str(pkg / "scripts"), ignore=ignore)
        shutil.copytree(str(ROOT / "references"), str(pkg / "references"), ignore=ignore)
        (pkg / "scripts" / "render_booklet.py").unlink()
        r = subprocess.run(
            [sys.executable, str(pkg / "scripts" / "worldstip.py"), "周末去大理",
             "--to", "大理", "--days", "3", "--people", "2", "--rich",
             "--dir", str(pkg / "out"), "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=300)
        ck(r.returncode == 0,
           f"--rich 在缺增强渲染器的包里应降级成功（实得 exit {r.returncode}）")
        _j = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
        ck(_j.get("ok") is True, "降级后仍必须产出成品（ok=true）")
        ck(_j.get("degraded") is True, "JSON 必须自报 degraded=true，不许假装跑了增强版")
        ck(_j.get("renderer") == "render_compact.py",
           f"降级后应回落到紧凑卡册（实得 {_j.get('renderer')!r}）")
        ck((_j.get("outputs") or {}).get("小册子.html", 0) > 1000,
           "降级产物必须是有内容的 HTML，不能是 0 字节")
        ck("[DEGRADED]" in r.stderr, "stderr 必须打 [DEGRADED] 让人看得见降级")
        _man = json.loads((pkg / "out" / "manifest.json").read_text(encoding="utf-8"))
        ck(bool(_man.get("degrade_reason")), "manifest 要留下降级原因，便于事后追溯")

        # 病根②：profile/reflect 直接 open(...,"w")，目录不可写时抛原始 PermissionError
        # traceback，用户看到的是一堆栈而不是「没保存、怎么办」。
        bad = str(ROOT / "VERSION.json") + "/sub"     # 把文件当目录 → 必然写失败
        env_bad = dict(os.environ, AITRIP_HOME=bad)
        for script, argv in (
                ("profile.py", ["--action", "remember", "--field", "pace", "--value", "x"]),
                ("reflect.py", ["--trip", "t", "--field", "accuracy", "--score", "3"])):
            rr = subprocess.run([sys.executable, str(SCRIPTS / script)] + argv,
                                capture_output=True, text=True, encoding="utf-8",
                                env=env_bad, timeout=90)
            ck(rr.returncode == 2, f"{script} 写不进时应退出 2（实得 {rr.returncode}）")
            ck("没有保存" in rr.stderr and "Traceback" not in rr.stderr,
               f"{script} 失败要给明确诊断且不得抛 traceback")

        # 目录可写时必须真写进去（别为了「不报错」把功能做没了）
        ok_dir = Path(td) / "aitrip"
        env_ok = dict(os.environ, AITRIP_HOME=str(ok_dir))
        rr = subprocess.run([sys.executable, str(SCRIPTS / "profile.py"),
                             "--action", "remember", "--field", "pace", "--value", "不赶场"],
                            capture_output=True, text=True, encoding="utf-8",
                            env=env_ok, timeout=90)
        _saved = ok_dir / "profile.json"
        ck(rr.returncode == 0 and _saved.is_file()
           and json.loads(_saved.read_text(encoding="utf-8")).get("pace") == "不赶场",
           "AITRIP_HOME 可写时必须真的落盘，不能只吞异常")

    # 病根③：跨平台包差异与检索层分工「零声明」——文档不说，使用者只能猜。
    plat_doc = (ROOT / "docs" / "PLATFORMS.md").read_text(encoding="utf-8")
    ck("PLATFORMS:BEGIN" in plat_doc and "PLATFORMS:END" in plat_doc,
       "docs/PLATFORMS.md 必须留可机检的差异表标记")
    ck("3 MiB" in plat_doc, "差异表要写清 WorkBuddy 的体积硬约束")
    res_doc = (ROOT / "docs" / "RESOURCES.md").read_text(encoding="utf-8")
    for _s in ("search_dest.py", "places_query.py", "history_query.py",
               "guide_list.py", "guide_digest.py", "site_query.py"):
        ck(_s in res_doc, f"检索层分工表要点名 {_s}")

    # ==== L14 终端分流（v0.2.274）====================================
    # 病根④：两个渲染器都是「一份 HTML 通吃所有屏幕」——compact 没有打印分页，
    # booklet 没有移动断点。用户要的是 PC 出网页+小册子、手机出 HTML5。
    # 这里不看文件名，只认**互斥的 CSS 标记**：三件套必须各含各的、且互不串味。
    print("[L14] 终端分流：PC 网页 / A5 小册子 / 手机 HTML5（v0.2.274）")
    import tempfile

    td14 = tempfile.mkdtemp(prefix="ws-device-")
    PC_ONLY = ("repeat(3,1fr)",)                          # 只有 PC 件目录三列
    A5_ONLY = ("@page{size:A5", "@media print")           # 只有 A5 件真分页
    MOB_ONLY = ("viewport-fit=cover", 'class="to-top"', "min-height:44px")

    def _entry(extra, tag):
        d = Path(td14) / tag
        rr = subprocess.run(
            [sys.executable, str(SCRIPTS / "worldstip.py"), "规划大理三天行程",
             "--to", "大理", "--days", "3", "--dir", str(d), "--json"] + extra,
            capture_output=True, text=True, encoding="utf-8", timeout=180)
        try:
            body = json.loads(rr.stdout)
        except Exception:
            body = {}
        return rr, body, d

    def _read(p):
        return Path(p).read_text(encoding="utf-8")

    _rr, both, bdir = _entry(["--device", "both"], "both")
    htmls = sorted(k for k in both.get("outputs", {}) if k.endswith(".html"))
    ck(both.get("ok") is True, f"both 模式链路应成功（实得 ok={both.get('ok')}）")
    ck(len(htmls) == 3, f"both 模式应产 3 件 HTML（实得 {len(htmls)}：{htmls}）")
    ck(htmls == sorted(["小册子.html", "小册子-A5.html", "小册子-手机.html"]),
       f"三件命名应为 PC/A5/手机（实得 {htmls}）")
    ck(both.get("device_applied") is True, "both 模式 device_applied 应为 true")

    _pc = _read(bdir / "小册子.html")
    _a5 = _read(bdir / "小册子-A5.html")
    _mb = _read(bdir / "小册子-手机.html")

    ck(all(m in _pc for m in PC_ONLY) and not any(m in _pc for m in A5_ONLY + MOB_ONLY),
       "PC 件只含桌面标记（目录三列），不得混入 A5/手机标记")
    ck(all(m in _a5 for m in A5_ONLY) and not any(m in _a5 for m in PC_ONLY + MOB_ONLY),
       "A5 件只含分页标记，不得混入 PC/手机标记")
    ck(all(m in _mb for m in MOB_ONLY) and not any(m in _mb for m in A5_ONLY + PC_ONLY),
       "手机件只含移动标记，不得混入 PC/A5 标记")
    ck(len({len(_pc), len(_a5), len(_mb)}) == 3,
       "三件字节数必须两两不同（同一份改名会相等）")
    ck("viewport-fit=cover" in _mb and "viewport-fit=cover" not in _pc,
       "viewport 安全区只手机件开，PC 件不得开")

    _rr, pc_one, _pd = _entry(["--device", "pc"], "pc")
    ck(len([k for k in pc_one.get("outputs", {}) if k.endswith(".html")]) == 1,
       "单选 pc 只产 1 件，不得偷偷多写")
    _rr, mo_one, _md = _entry(["--device", "mobile"], "mobile")
    _mo_html = [k for k in mo_one.get("outputs", {}) if k.endswith(".html")]
    ck(len(_mo_html) == 1, "单选 mobile 只产 1 件")
    ck(_mo_html and "viewport-fit=cover" in _read(_md / _mo_html[0]),
       "单选 mobile 产出的那份必须真是手机版")

    # rich 分支：增强渲染器不分流，必须如实声明，不许假装给了三件套
    _rr, rich, _rd = _entry(["--rich"], "rich")
    ck(rich.get("device") == "both" and rich.get("device_applied") is False,
       f"--rich 时应记 device_applied=false（实得 {rich.get('device_applied')}）")
    ck("设备" in (rich.get("device_note") or "") or "分流" in (rich.get("device_note") or ""),
       "--rich 未分流时必须给出可读说明，不能静默忽略 --device")

    # 清掉本轮生成的临时目录：测试跑完不该在工作区留垃圾
    shutil.rmtree(td14, ignore_errors=True)

    # ==== L15 不可信输入必须收敛，不裸露 traceback（v0.2.274 自查整改）====
    # 病根⑤：render_compact / render_booklet 直接 json.load(open(...))，
    # 传错路径或坏 JSON 就抛 Python 栈，把本机绝对路径一并打给调用方；
    # 更糟的是空壳 plan（合法 JSON 但无行程）会渲染成空册子并报「✅ 已生成」。
    print("[L15] 不可信输入受控收敛：坏路径 / 坏 JSON / 空壳 plan")
    import tempfile as _tf
    _d15 = Path(_tf.mkdtemp(prefix="ws-fatal-"))
    _good_plan = ROOT / "worldstip-out" / "plan.json"

    def _run_render(script, plan_arg, extra_env=None):
        env = dict(os.environ)
        env.pop("AITRIP_DEBUG", None)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, str(SCRIPTS / script), "--plan", str(plan_arg),
             "--out", str(_d15 / "o.html"), "--title", "坏输入"],
            capture_output=True, text=True, encoding="utf-8", timeout=120, env=env)

    if _good_plan.is_file():
        _badjson = _d15 / "bad.json"
        _badjson.write_text("{bad json", encoding="utf-8")
        _shell = _d15 / "shell.json"
        _shell.write_text('{"a": 1}', encoding="utf-8")

        for _script in ("render_compact.py", "render_booklet.py"):
            miss = _run_render(_script, _d15 / "nope.json")
            ck(miss.returncode == 2,
               f"{_script} 文件不存在应 exit 2（实得 {miss.returncode}）")
            ck("Traceback" not in miss.stderr,
               f"{_script} 坏路径不得裸露 traceback")
            ck("[ERROR]" in miss.stderr, f"{_script} 坏路径应给一行中文诊断")

            bad = _run_render(_script, _badjson)
            ck(bad.returncode == 2,
               f"{_script} 坏 JSON 应 exit 2（实得 {bad.returncode}）")
            ck("Traceback" not in bad.stderr, f"{_script} 坏 JSON 不得裸露 traceback")

            shell = _run_render(_script, _shell)
            ck(shell.returncode == 2,
               f"{_script} 空壳 plan 应 exit 2，不得渲染空册子并谎报成功"
               f"（实得 {shell.returncode}）")
            ck("没有可用行程数据" in shell.stderr,
               f"{_script} 空壳 plan 应指明缺的是行程数据")

        # 反向对照：合法 plan 必须仍然 exit 0，证明上面的拦截不是无脑拒绝
        okrun = _run_render("render_compact.py", _good_plan)
        ck(okrun.returncode == 0,
           f"合法 plan 仍应 exit 0（实得 {okrun.returncode}），拦截不得误伤")

        # 调试开关：AITRIP_DEBUG=1 时必须真的抛出，否则等于死代码
        dbg = _run_render("render_compact.py", _d15 / "nope.json",
                          {"AITRIP_DEBUG": "1"})
        ck(dbg.returncode != 2 and "Traceback" in dbg.stderr,
           "AITRIP_DEBUG=1 应恢复原始异常，供现场调试")
    else:
        ck(False, f"缺样例 plan，L15 无法验证：{_good_plan}")
    shutil.rmtree(_d15, ignore_errors=True)

    # ==== L16 合规检查器的反向自证（v0.2.274 自查整改）====
    # 一个永远 PASS 的自检等于没有自检。这里喂故意违规的 plugin.json 副本，
    # 证明 check_compliance() 的每条判据都真的会报错。
    print("[L16] 专家包合规检查器的反向自证")
    import contextlib
    import importlib.util
    import io as _io

    _spec = importlib.util.spec_from_file_location(
        "bep", ROOT / "tools" / "build_expert_pack.py")
    _bep = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_bep)
    _plug = ROOT / "expert" / "worldstip-travel-expert" / ".codebuddy-plugin" / "plugin.json"
    _orig = json.loads(_plug.read_text(encoding="utf-8"))
    _d16 = Path(tempfile.mkdtemp(prefix="ws-comp-"))

    def _probe(label, mutate, expect_fail=True):
        d = json.loads(json.dumps(_orig))
        mutate(d)
        p = _d16 / "plugin.json"
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        with contextlib.redirect_stdout(_io.StringIO()):
            rc = _bep.check_compliance(str(p))
        ck((rc == 1) == expect_fail,
           f"合规检查器对「{label}」应{'报错' if expect_fail else '放行'}（实得 rc={rc}）")

    _probe("原样不动", lambda d: None, expect_fail=False)
    _probe("displayName.zh 含空格",
           lambda d: d["displayName"].__setitem__("zh", "WorldsTip 旅行规划师"))
    _probe("displayName.zh 含括号",
           lambda d: d["displayName"].__setitem__("zh", "旅行规划师（专业版）"))
    _probe("displayName.zh 超 15 字",
           lambda d: d["displayName"].__setitem__("zh", "超长超长超长超长超长超长超长的名字"))
    _probe("displayDescription.zh 超 100 字",
           lambda d: d["displayDescription"].__setitem__("zh", "长" * 101))
    _probe("tags 不是 3 个",
           lambda d: d["tags"].append({"zh": "多出来的", "en": "extra"}))
    _probe("defaultInitPrompt 与 quickPrompts[0] 不一致",
           lambda d: d["quickPrompts"][0].__setitem__(
               "zh", d["quickPrompts"][0]["zh"] + "！"))
    # v0.2.275 自查新增：声明的包内路径必须真实存在。
    # 「字段填了但文件不在」是解析层不报、装完才炸的缺陷，必须机检。
    _probe("avatar 指向不存在的文件",
           lambda d: d.__setitem__("avatar", "avatars/not-there.png"))
    _probe("avatar 字段被删", lambda d: d.pop("avatar", None))
    _probe("agents 指向不存在的文件",
           lambda d: d.__setitem__("agents", ["./agents/not-there.md"]))
    _probe("agents 数组为空", lambda d: d.__setitem__("agents", []))

    # 根标志判据：原实现排在 json.load 之后，文件缺失时先抛 FileNotFoundError，
    # 那条判据永远 PASS、永不 FAIL。现改为最先单独判，这里证明它真的返回 1 而不崩。
    with contextlib.redirect_stdout(_io.StringIO()):
        _rc_missing = _bep.check_compliance(str(_d16 / "no-such" / "plugin.json"))
    ck(_rc_missing == 1,
       f"plugin.json 缺失时应 rc=1 而非抛异常（实得 rc={_rc_missing}）")
    shutil.rmtree(_d16, ignore_errors=True)

    # ==== 内嵌技能版本漂移的机检（v0.2.275 自查）====
    # 旧正则写死 0\.2\.(\d+)，技能升到 0.3.x 就匹配不到、永远 PASS。
    # 这里复制一份专家包、把内嵌技能版本改旧，证明通用正则真的会抓出来。
    # 版本号动态从 VERSION.json 取：写死会在下次 bump 时静默空转、测试变假绿。
    _cur_ver = json.loads((ROOT / "VERSION.json").read_text(encoding="utf-8"))["version"]
    _d17 = Path(tempfile.mkdtemp(prefix="ws-drift-"))
    try:
        _copy = _d17 / "worldstip-travel-expert"
        shutil.copytree(ROOT / "expert" / "worldstip-travel-expert", _copy)
        _skill_md = _copy / "skills" / "worldstip-travel-planner" / "SKILL.md"
        _raw = _skill_md.read_text(encoding="utf-8")
        assert _cur_ver in _raw, f"内嵌技能入口未出现当前版本号 {_cur_ver}，漂移用例前置条件不成立"
        _skill_md.write_text(_raw.replace(_cur_ver, "0.0.1"), encoding="utf-8")
        _real_src = _bep.SRC
        _bep.SRC = str(_copy)
        try:
            with contextlib.redirect_stdout(_io.StringIO()):
                _rc_drift = _bep.check_versions()
        finally:
            _bep.SRC = _real_src
        ck(_rc_drift == 1,
           f"内嵌技能版本残留旧号时应 rc=1（实得 rc={_rc_drift}）")
    finally:
        shutil.rmtree(_d17, ignore_errors=True)

    print(f"\nLOGIC-FIX: {N - len(FAIL)} / {N} PASS, {len(FAIL)} FAIL")
    for f in FAIL:
        print("  FAILED:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
