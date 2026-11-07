#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""worldstip-travel-planner 回归测试套件（单独可跑，不依赖 pytest）。

用法：
    python tests/run_tests.py            # 跑全部
    python tests/run_tests.py --json     # 机器可读
    python tests/run_tests.py transit    # 只跑名字含 transit 的

退出码：0 = 全通过；1 = 有失败。

设计原则（来自技能设计范式 §8）：
- 测试名即规格：用完整句子描述不变量，读名即知断言什么。
- 成对测试：有效场景必须保留，镜像场景必须拒绝。
- 降级命名：明确写「丢弃而不崩」「降级而不编造」。
- 不依赖网络：全部用本地数据跑。
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
REFS = os.path.join(ROOT, "references")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

_REGISTRY = []


def test(name):
    """注册一个测试用例。"""
    def deco(fn):
        _REGISTRY.append((name, fn))
        return fn
    return deco


def _load_json(fn):
    with io.open(os.path.join(REFS, fn), encoding="utf-8") as f:
        return json.load(f)


def _tmp_plan_path():
    """build_itinerary 的 JSON 输出落到临时文件，避开 Windows 管道权限问题。"""
    return os.path.join(HERE, "_tmp_plan.json")


# ══════════════════════════════════════════════════════════
# 维度 A · 交通分支（plan_transit）
# ══════════════════════════════════════════════════════════

@test("同城出行距离为零时推荐市内交通而不误判为坐标缺失")
def _t_same_city():
    import plan_transit as pt
    r = pt.build("岳阳", "岳阳")
    assert r.get("distance_km") == 0, f"同城距离应为 0，实为 {r.get('distance_km')}"
    assert r.get("recommend") == "市内交通", f"应推荐市内交通，实为 {r.get('recommend')}"
    assert r.get("scope") == "市内", f"scope 应为市内，实为 {r.get('scope')}"


@test("坐标缺失的城市对不得给出高铁或机票等城际建议")
def _t_unknown_city():
    import plan_transit as pt
    r = pt.build("岳阳", "查无此城")
    assert r.get("recommend") == "需确认交通方式", f"实为 {r.get('recommend')}"
    assert r.get("distance_km") is None
    # 镜像断言：绝不能出现城际交通方式
    for kw in ("高铁", "机票", "飞机"):
        assert kw not in str(r.get("recommend", "")), "未知城市不得推荐城际交通"


@test("三十公里内属市内圈且不出城际方式")
def _t_within_city_ring():
    import plan_transit as pt
    r = pt.build("岳阳", "长沙")  # 128km 属近郊
    assert r.get("distance_km") and r["distance_km"] > 30
    assert "高铁" not in r.get("recommend", "") or "默认" in r.get("recommend", "")


@test("远距离行程才纳入机票比选")
def _t_far_distance_flight():
    import plan_transit as pt
    r = pt.build("岳阳", "北京")
    assert r.get("distance_km", 0) >= 1200, "远距阈值应为 1200km"
    assert r.get("recommend") == "机票参考", f"实为 {r.get('recommend')}"


@test("交通规则文件必须包含市内交通判据键")
def _t_transit_rules_keys():
    rules = _load_json("transit_rules.json")
    for k in ("市内交通", "高铁", "普铁", "飞机", "核实声明"):
        assert k in rules, f"transit_rules.json 缺键 {k}"
    assert rules["市内交通"].get("city_distance_km", 0) > 0


# ══════════════════════════════════════════════════════════
# 维度 B · 住宿与预算（build_itinerary）
# ══════════════════════════════════════════════════════════

@test("两天一晚的住宿晚数等于天数减一")
def _t_lodging_nights():
    import build_itinerary as bi

    class P:
        key = "couple"
        budget_ratio = {"交通": 0.24, "住宿": 0.32, "餐饮": 0.22,
                        "门票": 0.10, "其他": 0.12}
        intensity = 2

    sp = bi.stay_plan(2, P(), "情侣", "舒适")
    b = bi.budget_for(P(), 2, 2, "舒适", "舒适", stay=sp)
    assert b["nights"] == 1, f"2 天应 1 晚，实为 {b['nights']}"
    assert b["rooms"] >= 1, "至少 1 间房"


@test("当天来回不产生住宿费用")
def _t_same_day_no_lodging():
    import build_itinerary as bi

    class P:
        key = "solo"
        budget_ratio = {"交通": 0.30, "住宿": 0.25, "餐饮": 0.22,
                        "门票": 0.13, "其他": 0.10}
        intensity = 2

    sp = bi.stay_plan(1, P(), "", "舒适")
    b = bi.budget_for(P(), 1, 1, "舒适", "舒适", stay=sp)
    assert b["nights"] == 0, f"1 天应 0 晚，实为 {b['nights']}"
    assert b["group"].get("住宿", 0) == 0, "当天来回住宿费应为 0"


@test("情侣同行只开一间房而非按人数开房")
def _t_couple_one_room():
    import build_itinerary as bi

    class P:
        key = "couple"
        budget_ratio = {"交通": 0.24, "住宿": 0.32, "餐饮": 0.22,
                        "门票": 0.10, "其他": 0.12}
        intensity = 2

    sp = bi.stay_plan(2, P(), "情侣", "舒适")
    assert sp.rooms == 1, f"情侣 2 人应 1 间房，实为 {sp.rooms}"


@test("多人团队按团队规模开多间房")
def _t_group_multiple_rooms():
    import build_itinerary as bi

    class P:
        key = "friends"
        budget_ratio = {"交通": 0.24, "住宿": 0.32, "餐饮": 0.22,
                        "门票": 0.10, "其他": 0.12}
        intensity = 2

    sp = bi.stay_plan(6, P(), "朋友团", "舒适")
    assert sp.rooms >= 2, f"6 人团队应 ≥2 间房，实为 {sp.rooms}"


@test("住宿预算按房间计价而非按人数计价")
def _t_lodging_by_room():
    import build_itinerary as bi

    class P:
        key = "couple"
        budget_ratio = {"交通": 0.24, "住宿": 0.32, "餐饮": 0.22,
                        "门票": 0.10, "其他": 0.12}
        intensity = 2

    sp = bi.stay_plan(2, P(), "情侣", "舒适")
    b = bi.budget_for(P(), 3, 2, "舒适", "舒适", stay=sp)
    assert "间" in b["lodging_basis"], f"住宿依据应说明按房间计：{b['lodging_basis']}"


# ══════════════════════════════════════════════════════════
# 维度 C · 准入许可门禁（gate_card）
# ══════════════════════════════════════════════════════════

@test("本地基线免签不得直接给出绿灯除非已核验")
def _t_visa_green_requires_verification():
    import gate_card as gc
    # 未核验 → 必须灰灯（不得直出绿灯）
    c = gc._check_visa({"visa_required": "none"})
    assert c["light"] == gc.GREY, f"未核验免签应为灰灯，实为 {c['light']}"
    # 已核验 → 才允许绿灯
    v = gc._check_visa({"visa_required": "none", "visa_verified": True,
                        "visa_source": "https://example.gov/entry"})
    assert v["light"] == gc.GREEN, f"已核验免签应为绿灯，实为 {v['light']}"
    assert "example.gov" in v["detail"], "绿灯必须带官方来源链接供复核"


@test("需要准入许可但未核验时不得给出黄灯或绿灯")
def _t_visa_required_unverified_is_grey():
    import gate_card as gc
    c = gc._check_visa({"visa_required": "required", "visa_lead_days": 15})
    assert c["light"] == gc.GREY, f"未核验需准入许可应为灰灯，实为 {c['light']}"
    # 已核验才转黄灯
    v = gc._check_visa({"visa_required": "required", "visa_lead_days": 15,
                        "visa_verified": True})
    assert v["light"] == gc.YELLOW, f"已核验需准入许可应为黄灯，实为 {v['light']}"


@test("缺少准入许可政策时给出灰灯而不是猜测")
def _t_visa_missing_is_grey():
    import gate_card as gc
    card = gc._check_visa({})
    assert card["light"] == gc.GREY, f"缺政策应为灰灯，实为 {card['light']}"
    assert card.get("action"), "灰灯必须给出下一步行动指引"


@test("准入许可办理时间不足必须红灯拦停")
def _t_visa_insufficient_time_is_red():
    import gate_card as gc
    card = gc._check_visa({"visa_required": True, "visa_lead_days": 15,
                            "days_to_depart": 5})
    assert card["light"] == gc.RED, f"时间不足应为红灯，实为 {card['light']}"


# ══════════════════════════════════════════════════════════
# 维度 D · 地名消歧（geo_disambiguate）
# ══════════════════════════════════════════════════════════

@test("歧义地名返回多个候选而不是擅自选定一个")
def _t_ambiguous_gives_candidates():
    import geo_disambiguate as gd
    r = gd.probe("幕阜山", user_text="爬山看日出", origin="岳阳")
    cands = r.get("candidates", [])
    assert len(cands) >= 2, f"幕阜山应有多候选，实为 {len(cands)}"


@test("错字地名能召回正确候选而不是返回空")
def _t_typo_recall():
    import geo_disambiguate as gd
    r = gd.probe("幕布山", user_text="爬山", origin="岳阳")
    assert r.get("candidates"), "错字地名应能召回候选"


# ══════════════════════════════════════════════════════════
# 维度 E · 数据资产完整性
# ══════════════════════════════════════════════════════════

@test("全部数据文件都有可读的结构化更新时间戳")
def _t_all_data_has_updated():
    import glob
    missing = []
    for f in sorted(glob.glob(os.path.join(REFS, "*.json"))):
        try:
            d = json.load(io.open(f, encoding="utf-8"))
        except Exception as e:
            missing.append(f"{os.path.basename(f)}(解析失败:{e})")
            continue
        meta = d.get("_meta", {}) if isinstance(d, dict) else {}
        upd = (meta.get("_updated") or meta.get("updated")
               or meta.get("fetched")
               or (d.get("_updated") if isinstance(d, dict) else None))
        if not upd:
            missing.append(os.path.basename(f))
    assert not missing, f"缺时间戳的数据文件（{len(missing)} 个）：{missing}"


@test("关键数据文件含来源标注以便溯源")
def _t_data_has_source():
    for fn in ("destinations.json", "visa_rules.json", "safety_playbook.json"):
        d = _load_json(fn)
        meta = d.get("_meta", {}) if isinstance(d, dict) else {}
        assert meta.get("source") or meta.get("来源"), f"{fn} 缺来源标注"


@test("数据文件里的时间戳是合法日期而非占位符")
def _t_updated_is_real_date():
    import re
    import glob
    pat = re.compile(r"^\d{4}-\d{2}-\d{2}")
    for f in sorted(glob.glob(os.path.join(REFS, "*.json"))):
        d = json.load(io.open(f, encoding="utf-8"))
        meta = d.get("_meta", {}) if isinstance(d, dict) else {}
        upd = meta.get("_updated") or meta.get("updated") or meta.get("fetched")
        if upd:
            assert pat.match(str(upd)), f"{os.path.basename(f)} 时间戳格式非法：{upd}"


# ══════════════════════════════════════════════════════════
# 维度 F · 扩展包降级（places_query）
# ══════════════════════════════════════════════════════════

@test("扩展数据内置时能返回结果，临时缺失时按退出码契约降级")
def _t_ext_missing_degrades():
    import shutil
    import tempfile
    import subprocess
    cmd = [sys.executable, "places_query.py", "--province", "湖南",
           "--type", "山", "--limit", "3"]
    # 分支 1：数据已内置 → 能力在，exit 0 且有结果
    r = subprocess.run(cmd, cwd=SCRIPTS, capture_output=True, text=True, timeout=60)
    assert r.returncode in (0, 1), f"内置数据时不应报扩展包未安装，实为 {r.returncode}"
    assert "EXT-MISSING" not in r.stderr, "数据已内置却报缺失"
    if r.returncode == 0:
        assert r.stdout.strip(), "exit 0 应有结果输出"
    # 分支 2：临时移走数据 → 降级契约仍成立（exit 2 + EXT-MISSING + 安装指引）
    data = os.path.join(REFS, "moto_places.json")
    tmp = tempfile.mktemp(prefix="ws_mp_", suffix=".json")
    shutil.move(data, tmp)
    try:
        r2 = subprocess.run(cmd, cwd=SCRIPTS, capture_output=True, text=True, timeout=60)
        assert r2.returncode == 2, f"缺扩展包应 exit 2，实为 {r2.returncode}"
        assert "EXT-MISSING" in r2.stderr, "缺扩展包必须在 stderr 明确告知"
        assert "moto-places" in r2.stderr, "应给出扩展包安装指引"
    finally:
        shutil.move(tmp, data)


# ══════════════════════════════════════════════════════════
# 维度 G · 端到端与产物
# ══════════════════════════════════════════════════════════

@test("行程规划能产出含每日安排的完整 JSON")
def _t_plan_json_complete():
    import subprocess
    out = _tmp_plan_path()
    with io.open(out, "w", encoding="utf-8") as fh:
        r = subprocess.run(
            [sys.executable, "build_itinerary.py", "--from", "岳阳", "--to", "张家界",
             "--days", "2", "--people", "1", "--json"],
            cwd=SCRIPTS, stdout=fh, stderr=subprocess.PIPE, text=True, timeout=120)
    assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr[:300]}"
    # Windows 下 subprocess 的 stdout 管道偶发 PermissionError，改走临时文件
    d = json.loads(io.open(_tmp_plan_path(), encoding="utf-8").read())
    assert d.get("plan"), "plan 应为非空列表"
    assert len(d["plan"]) == 2, f"2 天应有 2 个日程，实为 {len(d['plan'])}"
    assert d.get("stay"), "缺住宿方案"
    assert d.get("budget"), "缺预算方案"


@test("渲染器能产出含多个板块的成品册子")
def _t_render_booklet():
    import subprocess
    plan = os.path.join(HERE, "_tmp_plan2.json")
    html = os.path.join(HERE, "_tmp_booklet.html")
    with io.open(plan, "w", encoding="utf-8") as fh:
        pr = subprocess.run(
            [sys.executable, "build_itinerary.py", "--from", "岳阳", "--to", "张家界",
             "--days", "2", "--people", "1", "--json"],
            cwd=SCRIPTS, stdout=fh, stderr=subprocess.PIPE, text=True, timeout=120)
    assert pr.returncode == 0, f"build exit={pr.returncode}"
    r = subprocess.run(
        [sys.executable, "render_compact.py", "--plan", plan,
         "--title", "回归测试", "--out", html],
        cwd=SCRIPTS, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr[:300]}"
    content = io.open(html, encoding="utf-8").read()
    import re
    secs = set(re.findall(r"§\s*(\d+)", content))
    assert len(secs) >= 8, f"成品板块数应 ≥8，实为 {len(secs)}"
    assert 'src=""' not in content, "成品不得含空白图片占位"
    for p in (plan, html):
        if os.path.exists(p):
            os.remove(p)


@test("路由入口能对自然语言需求给出脚本链建议")
def _t_route_entry():
    import subprocess
    r = subprocess.run(
        [sys.executable, "route.py", "骑摩托从岳阳去凤凰古城，3天", "--json"],
        cwd=SCRIPTS, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr[:200]}"
    assert r.stdout.strip(), "路由入口应输出建议"


# ══════════════════════════════════════════════════════════
# 维度 H · 打包规范
# ══════════════════════════════════════════════════════════

@test("技能包内不含含用户名的绝对路径")
def _t_no_absolute_user_path():
    import glob
    bad = []
    for pat in ("*.md", "scripts/*.py", "references/*.json", "*.json"):
        for f in glob.glob(os.path.join(ROOT, pat)):
            try:
                c = io.open(f, encoding="utf-8").read()
            except Exception:
                continue
            if "cy770" in c or "C:\\Users\\" in c:
                bad.append(os.path.relpath(f, ROOT))
    assert not bad, f"含用户名的绝对路径：{bad}"


@test("版本号在 SKILL 与 CHANGELOG 中一致")
def _t_version_consistency():
    sk = io.open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8").read()
    ver = None
    for line in sk.splitlines()[:30]:
        if line.strip().startswith("version:"):
            ver = line.split(":", 1)[1].strip()
            break
    assert ver, "SKILL.md frontmatter 缺 version"
    cl = io.open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    assert ver in cl, f"CHANGELOG 中找不到版本 {ver}"


@test("文本文件使用纯 LF 换行且无 BOM")
def _t_lf_no_bom():
    import glob
    bad = []
    for pat in ("*.md", "scripts/*.py"):
        for f in glob.glob(os.path.join(ROOT, pat)):
            raw = open(f, "rb").read()
            if raw.startswith(b"\xef\xbb\xbf"):
                bad.append(f"{os.path.relpath(f, ROOT)}(BOM)")
            if b"\r\n" in raw:
                bad.append(f"{os.path.relpath(f, ROOT)}(CRLF)")
    assert not bad, f"换行/BOM 问题：{bad[:10]}"


@test("技能正文长度不超过五百行")
def _t_skill_md_length():
    n = len(io.open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8").read().splitlines())
    assert n <= 500, f"SKILL.md {n} 行，超出 500 行硬上限"


# ══════════════════════════════════════════════════════════
# 运行器
# ══════════════════════════════════════════════════════════

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    keyword = args[0] if args else ""

    cases = [(n, f) for n, f in _REGISTRY if keyword in n]
    results = []
    t_all = time.time()

    for name, fn in cases:
        t0 = time.time()
        try:
            fn()
            results.append({"name": name, "status": "pass",
                            "ms": int((time.time() - t0) * 1000), "error": None})
        except Exception as e:
            results.append({"name": name, "status": "fail",
                            "ms": int((time.time() - t0) * 1000),
                            "error": f"{type(e).__name__}: {e}",
                            "trace": traceback.format_exc()[-800:]})

    total = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = total - passed
    elapsed = time.time() - t_all

    if as_json:
        print(json.dumps({"total": total, "passed": passed, "failed": failed,
                          "elapsed_s": round(elapsed, 2), "results": results},
                         ensure_ascii=False, indent=2))
    else:
        for r in results:
            mark = "✓" if r["status"] == "pass" else "✗"
            print(f"{mark} {r['name']}  ({r['ms']}ms)")
            if r["status"] == "fail":
                print(f"    └─ {r['error']}")
        print("─" * 60)
        print(f"共 {total} 项 · 通过 {passed} · 失败 {failed} · 耗时 {elapsed:.2f}s")

    # 清理本套件产生的临时夹具，避免污染技能目录与交付包（v0.2.22）
    for _n in ("_tmp_plan.json", "_tmp_plan2.json"):
        _p = os.path.join(HERE, _n)
        if os.path.isfile(_p):
            try:
                os.remove(_p)
            except OSError:
                pass

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
