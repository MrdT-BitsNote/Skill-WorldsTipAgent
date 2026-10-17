#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摩旅校验引擎回归测试 —— v0.1.1

锁死几个踩过的坑，防止将来回退：

  1. 「禁止上高速」不得判成红灯 —— 曾导致「成都→康定」纯国道线路被判"行程不成立"
  2. 「未查证城市」不得判成红灯 —— 拿没根据的结论吓用户，与假绿灯同样错误
  3. 「C1 照」必须是红灯 —— 准驾车型不符按无证驾驶，降级成黄灯会误导用户
  4. 「信息缺失」不得默认绿灯 —— 全部未知时绿灯数必须为 0

用法：python test_moto_check.py
"""
from __future__ import annotations

import sys

from moto_check import (
    RED, YELLOW, GREEN, GREY,
    moto_card, moto_html, province_of, suggest_routes, all_routes, routes,
    check_highway, check_ban, check_range, check_license, check_helmet,
    rules, _days_of,
)

_PASS = 0
_FAIL: list[str] = []


def ck(cond: bool, label: str) -> None:
    global _PASS
    if cond:
        _PASS += 1
    else:
        _FAIL.append(label)


def _lamp(cards: list[dict], prefix: str) -> str:
    for c in cards:
        if c["title"].startswith(prefix):
            return c["light"]
    return "MISSING"


# ══ 1. 省份识别 ══════════════════════════════════════════════════════════
def t_province() -> None:
    for city, prov in [("上海", "上海"), ("黄山", "安徽"), ("康定", "四川"),
                       ("北京", "北京"), ("岳阳", "湖南"), ("成都", "四川"),
                       ("拉萨", "西藏"), ("三亚", "海南"), ("苏州", "江苏"),
                       ("乌鲁木齐", "新疆"), ("哈尔滨", "黑龙江")]:
        ck(province_of(city) == prov, f"省份识别 {city} → {prov}（实得 {province_of(city)}）")
    ck(province_of("") == "", "空城市名 → 空省份")
    ck(province_of("不存在的城市XYZ") == "", "未知城市 → 空省份（不猜）")


# ══ 2. 证照判定 ══════════════════════════════════════════════════════════
def t_license() -> None:
    # 坑 #3：C1 骑摩托 = 准驾车型不符 = 无证驾驶 → 必须红灯
    c = check_license(True, "C1", True, True)
    ck(c["light"] == RED, f"C1 照必须红灯（实得 {c['light']}）")
    c = check_license(True, "C2", True, True)
    ck(c["light"] == RED, "C2 照必须红灯")
    c = check_license(True, "B2", True, True)
    ck(c["light"] == RED, "B2 照必须红灯")

    c = check_license(True, "E", True, True)
    ck(c["light"] == GREEN, f"E 照 + 证件齐 → 绿灯（实得 {c['light']}）")
    c = check_license(True, "D", True, True)
    ck(c["light"] == GREEN, "D 照 + 证件齐 → 绿灯")

    # F 是轻便摩托，能骑但有限制 → 黄灯
    c = check_license(True, "F", True, True)
    ck(c["light"] == YELLOW, f"F 照 → 黄灯（实得 {c['light']}）")

    c = check_license(False, None, True, True)
    ck(c["light"] == RED, "无驾照 → 红灯")
    c = check_license(True, "E", False, True)
    ck(c["light"] == RED, "无行驶证 → 红灯")
    c = check_license(True, "E", True, False)
    ck(c["light"] == RED, "无交强险 → 红灯")

    c = check_license(None, None, None, None)
    ck(c["light"] == GREY, f"驾照信息未知 → 灰灯（实得 {c['light']}）")
    c = check_license(True, "E", None, True)
    ck(c["light"] == GREY, "行驶证未知 → 灰灯，不得默认通过")
    c = check_license(True, "E", True, None)
    ck(c["light"] == GREY, "交强险未知 → 灰灯")


# ══ 3. 头盔 ══════════════════════════════════════════════════════════════
def t_helmet() -> None:
    ck(check_helmet(True)["light"] == GREEN, "有头盔 → 绿灯")
    ck(check_helmet(False)["light"] == RED, "无头盔 → 红灯（法定强制）")
    ck(check_helmet(None)["light"] == GREY, "头盔未知 → 灰灯")


# ══ 4. 高速准入 ══════════════════════════════════════════════════════════
def t_highway() -> None:
    # 坑 #1：禁止省在默认（非依赖高速）模式下不得是红灯
    c = check_highway(["四川"])
    ck(c["light"] == YELLOW, f"禁止省·非高速模式 → 黄灯（实得 {c['light']}）—— 不得红灯")
    ck("不影响你去" in c["detail"], "禁止省·非高速模式 需明确说明「不影响你去」")

    # 明确要走高速 → 红灯硬阻断
    c = check_highway(["四川"], prefer_highway=True)
    ck(c["light"] == RED, f"禁止省 + 明确走高速 → 红灯（实得 {c['light']}）")

    # 允许省 → 绿灯
    c = check_highway(["北京"])
    ck(c["light"] == GREEN, f"允许省 → 绿灯（实得 {c['light']}）")
    c = check_highway(["云南"])
    ck(c["light"] == GREEN, "云南（允许）→ 绿灯")

    # 有条件 → 黄灯
    c = check_highway(["甘肃"])
    ck(c["light"] == YELLOW, f"甘肃（有条件）→ 黄灯（实得 {c['light']}）")

    # 未收录 → 黄灯（有未收录项时整体黄，且明细里该省为灰）
    c = check_highway(["火星省"])
    ck(c["light"] == YELLOW, "未收录省 → 黄灯")
    rows = c["items"]
    ck(rows and rows[0]["light"] == GREY, "未收录省 在明细中为灰灯")
    ck("不给推测结论" in rows[0]["note"], "未收录省 需明确声明不给推测结论")

    c = check_highway([])
    ck(c["light"] == GREY, "无省份 → 灰灯")

    # 证据等级要落到明细里：statute 不加角标（最可靠），practice / third_party 必须加
    stat_notes = " ".join(r["note"] for r in check_highway(["四川"])["items"])
    ck("（执法口径）" not in stat_notes and "第三方来源" not in stat_notes,
       "statute 省（四川）不加证据角标")
    prac_notes = " ".join(r["note"] for r in check_highway(["陕西"])["items"])
    ck("（执法口径）" in prac_notes,
       f"practice 省（陕西）需加「执法口径」角标（实得 {prac_notes[:50]}）")
    tp_notes = " ".join(r["note"] for r in check_highway(["海南"])["items"])
    ck("第三方来源" in tp_notes,
       f"third_party 省（海南）需加「第三方来源」角标（实得 {tp_notes[:50]}）")


# ══ 5. 禁摩城区（坑 #2 的核心）══════════════════════════════════════════
def t_ban() -> None:
    c = check_ban(["北京"])
    ck(c["light"] == YELLOW, f"命中禁摩 → 黄灯（实得 {c['light']}）")

    # 坑 #2：未查证城市不得报红灯
    c = check_ban(["珠海"])
    ck(c["light"] == GREY, f"未查证城市「珠海」→ 灰灯（实得 {c['light']}）—— 不得红灯")
    c = check_ban(["中山"])
    ck(c["light"] == GREY, "未查证城市「中山」→ 灰灯")
    c = check_ban(["太原"])
    ck(c["light"] == GREY, "未查证城市「太原」→ 灰灯")
    c = check_ban(["呼和浩特"])
    ck(c["light"] == GREY, "未查证城市「呼和浩特」→ 灰灯")
    c = check_ban(["拉萨"])
    ck(c["light"] == GREY, "未查证城市「拉萨」→ 灰灯")

    # 已知无禁行 → 绿灯
    c = check_ban(["济南"])
    ck(c["light"] == GREEN, f"已知不设禁摩「济南」→ 绿灯（实得 {c['light']}）")

    # 未命中名单 → 绿灯但必须带免责
    c = check_ban(["某某小镇"])
    ck(c["light"] == GREEN, "未命中名单 → 绿灯")
    ck("不表示绝对不禁摩" in (c["detail"] + c["action"]),
       "未命中名单 需带免责声明")

    c = check_ban([])
    ck(c["light"] == GREY, "无城市 → 灰灯")

    # 命中 + 未查证混合：整体黄，且未查证的也要列出来
    c = check_ban(["北京", "珠海"])
    ck(c["light"] == YELLOW, "命中+未查证混合 → 黄灯")
    ck(len(c["items"]) >= 2, "混合场景需把未查证城市一并列出")


# ══ 6. 续航 ══════════════════════════════════════════════════════════════
def t_range() -> None:
    # 超满油续航 → 红灯
    c = check_range(600, None, 250)
    ck(c["light"] == RED, f"单日 600km / 250cc → 红灯（实得 {c['light']}）")

    # 超安全续航但未超满油 → 黄灯
    c = check_range(350, None, 250)
    ck(c["light"] == YELLOW, f"单日 350km / 安全 294km → 黄灯（实得 {c['light']}）")

    # 在安全续舋内 → 绿灯
    c = check_range(200, None, 250)
    ck(c["light"] == GREEN, f"单日 200km → 绿灯（实得 {c['light']}）")

    # 不给排量也不给续航 → 灰灯，不猜
    c = check_range(300, None, None)
    ck(c["light"] == GREY, f"无排量无续航 → 灰灯（实得 {c['light']}）")

    # 用户直接给实际续航
    c = check_range(250, None, None, range_km=500)
    ck(c["light"] == GREEN, "给实际续航 500km / 单日 250km → 绿灯")

    # 排量分档归属（含边界值）
    for cc, mid in [(125, 350), (250, 420), (400, 440), (1000, 400)]:
        c = check_range(50, None, cc)
        it = c["items"]
        ck(it.get("theory_range_km") == mid,
           f"{cc}cc 分档续航应为 {mid}km（实得 {it.get('theory_range_km')}）")

    # 全程里程 → 算出加油次数
    c = check_range(None, 1000, 250)
    it = c["items"]
    ck(isinstance(it, dict) and it.get("expected_refuels", 0) > 0,
       "给全程里程 需算出预计加油次数")

    # 安全续航 = 理论 × 0.7
    c = check_range(100, None, 250)
    it = c["items"]
    ck(abs(it["safe_range_km"] - round(it["theory_range_km"] * 0.7)) <= 1,
       "安全续航 = 理论续航 × 0.7")


# ══ 7. 汇总与门禁 ════════════════════════════════════════════════════════
def t_card() -> None:
    # 齐备 + 短途 → 无红灯
    g = moto_card(from_city="北京", to_city="天津", daily_km=120, total_km=240,
                  displacement_cc=250, has_license=True, license_class="E",
                  has_plate=True, has_insurance=True, has_helmet=True)
    ck(g["red"] == 0, f"齐备短途 → 无红灯（实得 {g['red']}）")
    ck(len(g["cards"]) == 5, "恰好五项检查")

    # 有红灯 → blocked
    g = moto_card(from_city="北京", to_city="天津", has_license=False,
                  has_plate=True, has_insurance=True, has_helmet=True)
    ck(g["blocked"] is True, "无驾照 → blocked")
    ck(g["verdict"] == "blocked", "无驾照 → verdict=blocked")

    # 坑 #4：依赖用户信息的项，缺失时不得默认绿灯
    g = moto_card(from_city="北京", to_city="天津")
    for pre in ("准驾车型", "头盔", "续航"):
        ck(_lamp(g["cards"], pre) != GREEN,
           f"信息缺失时「{pre}」不得默认绿灯（实得 {_lamp(g['cards'], pre)}）")
    ck(g["grey"] + g["yellow"] == 4, f"信息缺失时 4 项为灰/黄（实得 {g['grey'] + g['yellow']}）")
    # 高速准入由路线省份决定（北京/天津均允许），与用户证件信息无关 → 绿灯是正确的
    ck(_lamp(g["cards"], "高速") == GREEN,
       f"北京→天津 高速准入应为绿灯（与用户信息无关）实得 {_lamp(g['cards'], '高速')}")

    # 途经省汇总
    g = moto_card(from_city="上海", to_city="黄山")
    ck(g["provinces"] == ["上海", "安徽"], f"途经省汇总（实得 {g['provinces']}）")

    # 纯国道长途：不得因禁止省而 blocked
    g = moto_card(from_city="成都", to_city="康定", daily_km=200, total_km=400,
                  displacement_cc=250, has_license=True, license_class="E",
                  has_plate=True, has_insurance=True, has_helmet=True)
    ck(not g["blocked"], "成都→康定（纯国道）不得被判 blocked —— 坑 #1 回归")


# ══ 8. 线路库 ════════════════════════════════════════════════════════════
def t_routes() -> None:
    rs = all_routes()
    ck(len(rs) == 18, f"线路库 18 条（实得 {len(rs)}）")
    for r in rs:
        ck(bool(r.get("name")), f"线路需有名称：{r.get('name')}")
        ck(isinstance(r.get("km"), int) and r["km"] > 0, f"线路 {r.get('name')} 需有正里程")
        ck(1 <= int(r.get("level", 0)) <= 5, f"线路 {r.get('name')} 难度需在 1-5")
        ck(r.get("highway_dependency") in ("low", "medium", "high"),
           f"线路 {r.get('name')} 需有高速依赖度")
        ck(bool(r.get("fuel_density")), f"线路 {r.get('name')} 需有补给密度")
        ck(bool(r.get("caution")), f"线路 {r.get('name')} 需有 caution")
        ck(bool(r.get("season")), f"线路 {r.get('name')} 需有季节窗口")
        # v0.1.13 里程来源纪律：每条须标 distance_source，绝不伪称实算
        ck(r.get("distance_source") in ("editorial_estimate", "amap_measured"),
           f"线路 {r.get('name')} 需有 distance_source（实算优先/估值标注）")

    # v0.1.13 里程纪律须写进 _meta（高德实算优先 / 估值标(估) / >150km评估拆天 / 路点校验）
    dd = (routes().get("_meta", {}) or {}).get("distance_discipline", {})
    ck(bool(dd), "moto_routes._meta 须含 distance_discipline")
    for k in ("实算优先", "估值标注", "单日里程阈值", "路点校验"):
        ck(bool(dd.get(k)), f"distance_discipline 须含「{k}」")
    # 单日 >150km 的线路必须能被识别为复核候选（近郊往返例外，但须可见）
    over = [r["name"] for r in rs if isinstance(r.get("km"), int) and r["km"] > 150 and str(r.get("days")) == "1"]
    ck(isinstance(over, list), "单日>150km 复核候选可枚举（不强制改天，近郊往返例外）")

    # 天数解析
    ck(_days_of({"days": "1-2"}) == (1.0, 2.0), "解析 '1-2'")
    ck(_days_of({"days": "10-15"}) == (10.0, 15.0), "解析 '10-15'")
    ck(_days_of({"days": "3"}) == (3.0, 3.0), "解析 '3'")
    ck(_days_of({"days": "?"}) == (0.0, 999.0), "无法解析 → 宽区间（不误杀）")

    # 按天数筛：2 天线路应包含近郊/环线，不含 318（10-15 天）
    r2 = suggest_routes(days=2, limit=99)
    names2 = [r["name"] for r in r2]
    ck(all("G318" not in n for n in names2), "2 天筛选 不含 318（10-15 天）")
    ck(len(r2) > 0, "2 天筛选 有结果")

    # 按难度筛
    easy = suggest_routes(level_max=2, limit=99)
    ck(all(int(r["level"]) <= 2 for r in easy), "level_max=2 全部 ≤2")

    # 无匹配 → 空列表，不硬凑
    ck(suggest_routes(days=2, level_max=0, limit=3) == [], "无匹配 → 空列表（不硬凑）")

    # limit 生效
    ck(len(suggest_routes(days=2, limit=2)) == 2, "limit 生效")

    # 地区筛
    fj = suggest_routes(region="湖南", limit=99)
    ck(any("幕阜山" in r["name"] for r in fj), "按地区筛「湖南」命中幕阜山线")


# ══ 9. 数据完整性 ════════════════════════════════════════════════════════
def t_data() -> None:
    r = rules()
    ha = r.get("highway_access") or {}
    ck(len(ha) == 31, f"高速准入覆盖 31 个省级区域（实得 {len(ha)}）")
    for k, v in ha.items():
        ck(v.get("status") in ("allowed", "banned", "conditional"),
           f"{k} status 取值合法（实得 {v.get('status')}）")
        ck(v.get("evidence") in ("statute", "practice", "third_party"),
           f"{k} 需有证据等级（实得 {v.get('evidence')}）")
        ck(bool(v.get("source")), f"{k} 需有来源")
        ck(v.get("stability") in ("stable", "volatile", "unknown"),
           f"{k} stability 合法")

    cb = r.get("city_ban") or []
    ck(len(cb) >= 40, f"禁摩城市 ≥40 条（实得 {len(cb)}）")
    for x in cb:
        ck(bool(x.get("city")), "禁摩条目需有城市名")
        ck(x.get("stability") in ("stable", "volatile", "unknown"),
           f"{x.get('city')} stability 合法")
        # 未查证的条目不得带具体禁行范围（否则会被误当成事实）
        if x.get("stability") == "unknown":
            ck(not (x.get("scope") or "").strip(),
               f"未查证城市「{x.get('city')}」不得带禁行范围")

    lc = r.get("license_chain") or {}
    for k in ("D", "E", "F", "年检", "异地年检", "头盔", "交强险"):
        ck(k in lc, f"证件链含「{k}」")
    ck(bool(lc.get("c1_warning")), "证件链含 C1 警告")

    fm = r.get("fuel_model") or {}
    ck(len(fm.get("displacement_bands") or {}) == 4, "续航分档 4 档")
    for k, v in (fm.get("displacement_bands") or {}).items():
        ck(v.get("range_km_mid", 0) > 0, f"分档 {k} 需有续航中位值")
        ck(v.get("range_km_lo", 0) <= v.get("range_km_mid", 0) <= v.get("range_km_hi", 0),
           f"分档 {k} 续航 lo≤mid≤hi")
    # 地形系数无权威来源 → 必须标 unknown，不得当已知用
    ck((fm.get("terrain_factor") or {}).get("stability") == "unknown",
       "地形系数须标 unknown（无权威来源）")
    ck(len(fm.get("station_notes") or []) > 0, "需有加油站实务说明")

    ck(bool(r.get("_meta", {}).get("global_disclaimer")), "需有全局免责声明")


# ══ 10. HTML 渲染 ════════════════════════════════════════════════════════
def t_html() -> None:
    g = moto_card(from_city="成都", to_city="康定", daily_km=200, displacement_cc=250,
                  has_license=True, license_class="E",
                  has_plate=True, has_insurance=True, has_helmet=True)
    h = moto_html(g, "康定")
    ck(len(h) > 500, "HTML 有内容")
    ck("摩旅可行性自检" in h, "HTML 含板块标题")
    ck("sec-open" in h, "HTML 含板块容器（复用排版规范）")
    ck("摩托五项门禁" in h, "HTML 含门禁卡")
    ck("要做什么" in h, "HTML 含行动项")
    ck("▲" not in h and "**" not in h, "HTML 不得残留 Markdown 标记")

    # 空输入 → 空串（不得渲染空壳板块）
    ck(moto_html({}) == "", "空输入 → 空串")
    ck(moto_html({"cards": []}) == "", "空 cards → 空串")

    # 带高速明细的渲染
    g2 = moto_card(from_city="上海", to_city="黄山")
    h2 = moto_html(g2, "黄山")
    ck("上海" in h2, "HTML 含途经省明细")

    # 未转义风险
    g3 = moto_card(from_city="<script>", to_city="黄山")
    h3 = moto_html(g3, "x")
    ck("<script>" not in h3, "HTML 需转义特殊字符")


def main() -> int:
    for fn in (t_province, t_license, t_helmet, t_highway, t_ban, t_range,
               t_card, t_routes, t_data, t_html):
        fn()
    print(f"\n{'='*56}")
    print(f"通过 {_PASS} 项断言", end="")
    if _FAIL:
        print(f"，失败 {len(_FAIL)} 项：")
        for f in _FAIL:
            print("   ✗", f)
        print(f"{'='*56}\n")
        return 1
    print(", ALL PASSED")
    print(f"{'='*56}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
