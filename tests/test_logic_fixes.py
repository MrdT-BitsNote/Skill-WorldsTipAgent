#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.2.1 逻辑缺陷回归断言（纯 stdlib）：每条对应一个已修的真实错判。

这些错判的共同特征：**静态检查全绿、lint A/100 也看不出来**，只有把真实输入
喂进判定函数才会暴露。所以这里的写法是「反例优先」——每条都先写下当年判错的原话。
任一失败 EXIT 1。
"""
import json
import re
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

    print(f"\nLOGIC-FIX: {N - len(FAIL)} / {N} PASS, {len(FAIL)} FAIL")
    for f in FAIL:
        print("  FAILED:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
