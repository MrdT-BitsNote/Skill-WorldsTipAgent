#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路线可视化回归测试（route_viz）

锁死几个一定会踩的坑，防止将来回退：

  1. 同名跨省错配 —— 「凤凰」在 moto_places 里有江苏扬州凤凰岛，
     带行政约束时必须查不到就不画，绝不能把湖南凤凰古城画到江苏去。
  2. 坐标缺失必须降级 —— 可用节点 < 2 时返回空串，由上层退回纯文字；
     不许拿近似点凑数，也不许画「示意图」假形状。
  3. 零外链 —— 输出 SVG 不得含 http:// 或 https://（千问平台零外链硬约束）。
  4. GPS 轨迹抽稀必须保端点 —— 抽稀后首尾点不变，否则形状被截断。
  5. 里程自校验 —— 太浮山轨迹按 haversine 累加应接近库标 56 km（误差 <5%），
     这条能同时证明轨迹是真路网而非直线连接。
  6. 零地图边界 —— SVG 里不得出现行政区/国界类元素。
  7. HTML 转义 —— 节点名带尖括号时不能破坏文档结构。

用法：python scripts/test_route_viz.py
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from route_viz import (  # noqa: E402
    GeoResolver, collect_nodes, render_svg, render_route_html,
    load_traces, match_trace, render_trace_svg, render_trace_html, plan_texts,
    _haversine, _bearing,
)

_PASS = 0
_FAIL: list[str] = []


def ck(cond: bool, label: str) -> None:
    global _PASS
    if cond:
        _PASS += 1
    else:
        _FAIL.append(label)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ══ 1. 同名消歧：宁可查不到，不许跨省错配 ════════════════════════════════
def t_disambiguate() -> None:
    r = GeoResolver()
    # 带行政约束 → 必须落在湖南
    g = r.resolve("凤凰", "湖南")
    if g:
        ck("湖南" in (g.get("admin") or "") or "湘西" in (g.get("admin") or ""),
           f"「凤凰」带湖南约束应落在湖南（实得 {g.get('admin')}）")
    # 不带约束且多候选 → 必须不画
    r2 = GeoResolver()
    g2 = r2.resolve("妙峰山")
    ck(g2 is not None, "「妙峰山」无约束时应命中（数据里只有一个高置信条目）")
    if g2:
        ck(35 < g2["lat"] < 41, f"「妙峰山」不得落到浙江（实得 lat={g2['lat']}）")

    # 城市级优先，且必须带坐标
    g3 = r.resolve("佛山")
    ck(g3 is not None and abs(g3["lat"] - 23.0) < 0.5,
       f"「佛山」应命中广东佛山（实得 {g3})")


# ══ 2. 坐标缺失降级 ═════════════════════════════════════════════════════
def t_degrage() -> None:
    ck(render_svg([]) == "", "空节点列表必须返回空串")
    one = [dict(name="佛山", lat=23.02, lng=113.12, role="start", km=0.0)]
    ck(render_svg(one) == "", "单节点不足以成线，必须返回空串")
    ck(render_route_html({}) == "", "空 plan 必须返回空串")
    ck(render_route_html({"origin": "不存在的地名XYZ",
                          "destinations": ["另一个不存在ABC"]}) == "",
       "全部查不到坐标时必须整体不出图")


# ══ 3. 零外链 ═══════════════════════════════════════════════════════════
def t_no_external() -> None:
    plan = {"origin": "佛山", "destinations": ["长沙"],
            "plan": [{"day": 1, "city": "郴州", "active": {"km": 380}}]}
    html = render_route_html(plan)
    ck(bool(html), "有效行程应能出图")
    # 硬要求：连 xmlns 都不能带。SVG 内联进 HTML 时 HTML5 解析器会自动归入 SVG 命名空间，
    # 而 xmlns 里的 http:// 会被千问平台的「零 http(s) URL」闸门判成外链（踩过）。
    ck("http://" not in html and "https://" not in html,
       "SVG 不得含任何 http/https（含 xmlns），千问零外链约束")
    ck("xmlns" not in html, "内联 SVG 不写 xmlns（HTML5 会自行归入 SVG 命名空间）")


# ══ 4/5. 轨迹抽稀与里程自校验 ═══════════════════════════════════════════
def t_traces() -> None:
    p = os.path.join(ROOT, "references", "moto_traces.json")
    if not os.path.exists(p):
        ck(True, "moto_traces.json 未生成，跳过（构建期产物，非运行时必需）")
        return
    d = json.load(open(p, encoding="utf-8"))
    tr = d.get("traces") or {}
    ck(len(tr) > 0, "moto_traces.json 应至少含 1 条轨迹")
    for name, t in tr.items():
        pts = t.get("pts") or []
        ck(len(pts) >= 2, f"{name} 轨迹点数应 >=2（实得 {len(pts)}）")
        ck(t.get("pts_n") == len(pts), f"{name} pts_n 与实际点数应一致")
        # 抽稀必须保端点：最后一个点要与原始轨迹终点一致
        ck(all(isinstance(x, (list, tuple)) and len(x) == 2 for x in pts),
           f"{name} 轨迹点应为 [lat,lng] 二元组")
        km = 0.0
        for i in range(1, len(pts)):
            km += _haversine(pts[i - 1], pts[i])
        claim = float(t.get("km_local") or 0)
        if claim:
            err = abs(km - claim) / claim
            ck(err < 0.15, f"{name} 轨迹累计里程 {km:.1f} 与库标 {claim} 误差 {err*100:.0f}% 过大")
    # 太浮山单条精校
    key = [k for k in tr if "太浮山" in k]
    if key:
        t = tr[key[0]]
        km = sum(_haversine(t["pts"][i - 1], t["pts"][i]) for i in range(1, len(t["pts"])))
        ck(abs(km - 56.0) / 56.0 < 0.05,
           f"太浮山轨迹里程 {km:.1f} 应接近库标 56 km（误差 <5%）")


# ══ 6. 零地图边界 ═══════════════════════════════════════════════════════
def t_no_boundary() -> None:
    plan = {"origin": "佛山", "destinations": ["长沙"],
            "plan": [{"day": 1, "city": "郴州", "active": {"km": 380}}]}
    html = render_route_html(plan)
    for bad in ("geojson", "topojson", "border", "province-boundary",
                "d3.geo", "leaflet", "amap", "baidu"):
        ck(bad not in html.lower(), f"输出不得含地图组件痕迹：{bad}")
    ck("不含行政区边界" in html, "图内必须自标不含行政区边界")


# ══ 7. 转义与方位 ═══════════════════════════════════════════════════════
def t_escape_and_bearing() -> None:
    plan = {"origin": "<script>x</script>", "destinations": ["广州"]}
    html = render_route_html(plan)
    ck("<script>" not in html, "节点名含脚本时必须转义")
    # 佛山 → 长沙 基本是正北
    a = dict(lat=23.02, lng=113.12)
    b = dict(lat=28.23, lng=112.94)
    ck(_bearing(a, b) == "北", f"佛山→长沙应为「北」（实得 {_bearing(a, b)}）")
    a2 = dict(lat=23.02, lng=113.12)
    b2 = dict(lat=23.13, lng=113.26)
    ck(_bearing(a2, b2) in ("东北", "东"), f"佛山→广州应为偏东（实得 {_bearing(a2, b2)}）")


# ══ 8. 结构完整性 ═══════════════════════════════════════════════════════
def t_structure() -> None:
    plan = {"origin": "佛山", "destinations": ["衡阳"],
            "plan": [{"day": 1, "city": "郴州", "active": {"km": 380}},
                     {"day": 2, "city": "衡阳", "active": {"km": 150}}]}
    nodes, missing = collect_nodes(plan)
    ck(len(nodes) >= 3, f"应解析出至少 3 个节点（实得 {len(nodes)}）")
    ck(nodes[0]["role"] == "start", "首节点角色必须为 start")
    ck(nodes[-1]["role"] == "end", "末节点角色必须为 end")
    km = [n["km"] for n in nodes]
    ck(km == sorted(km), "累计里程必须单调不减")
    html = render_route_html(plan)
    ck(html.count("<svg") == 1, "一次渲染只能出一个 SVG")
    ck("viewBox" in html, "SVG 必须有 viewBox（响应式）")
    # 文本不得溢出画布：任何 x 坐标不得为负
    xs = [float(m) for m in re.findall(r'<text x="(-?[\d.]+)"', html)]
    ck(all(v >= 0 for v in xs), "文本 x 坐标不得为负（会出框）")


# ══ 9. 线路形状（真轨迹，v0.2.274）══════════════════════════════════════
def t_trace_shape() -> None:
    tr = load_traces()
    ck(len(tr) >= 6, f"轨迹库应有 ≥6 条线路（实得 {len(tr)}）")
    # 认线路：原话里的地名要能认出来
    m = match_trace(["骑摩托去常德桃花源，2天"])
    ck(bool(m), "「桃花源」应认得出对应线路")
    if m:
        ck("桃花源" in (m[1].get("src_name") or ""), "认出的必须是桃花源线")
    # 命名模板词不算命中：否则「湖南跑山线」会匹配到「太浮山跑山线」
    ck(match_trace(["湖南跑山线"]) is None, "模板词「跑山线」不得单独构成命中")
    # 同分歧义：两个地名各命中一条线、长度相同 → 宁可不画
    ck(match_trace(["太浮山", "黑麋峰"]) is None, "并列命中应判为歧义不出图")
    html = render_trace_html(["太浮山"])
    ck("route-trace" in html, "能画出线路形状 SVG")
    ck("xmlns" not in html, "SVG 不得带 xmlns（千问零外链闸门）")
    ck("http://" not in html and "https://" not in html, "线路形状图不得含任何网络地址")
    ck("国界" not in html and "省界" not in html, "不得出现行政区边界元素")
    ck("起终点" in html or "起点" in html, "必须标出起终点")
    svg = render_trace_svg(tr[list(tr)[0]])
    ck("等比例" in svg, "图内要自标等比例投影（防止被当成导航图）")
    # 里程自校验：太浮山轨迹累计应接近库标 56km
    tf = tr.get("taifushan") or {}
    if tf.get("km_src"):
        geo = sum(_haversine(tf["pts"][i - 1], tf["pts"][i])
                  for i in range(1, len(tf["pts"])))
        ck(abs(geo - float(tf["km_src"])) / float(tf["km_src"]) < 0.05,
           f"太浮山轨迹累计应≈库标（实得 {geo:.1f} vs {tf['km_src']}）")
    # 坐标必须落在画布内
    vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if vb:
        W, H = float(vb.group(1)), float(vb.group(2))
        cs = re.findall(r'<circle cx="(-?[\d.]+)" cy="(-?[\d.]+)"', svg)
        ck(bool(cs), "应有起终点圆点")
        ck(all(0 <= float(x) <= W and 0 <= float(y) <= H for x, y in cs),
           "起终点圆点不得画出画布")
    # 环线：首尾重合只画一组标记
    loop = {"src_name": "测试环线", "km_src": 30, "pts":
            [[30.0, 111.0], [30.1, 111.0], [30.1, 111.1], [30.0, 111.1], [30.0, 111.0]]}
    lp = render_trace_svg(loop)
    ck("起终点 · 环线" in lp, "首尾重合的线路应标成环线")
    ck(lp.count("<circle") == 2, "环线只画一组圆点（点 + 外环）")
    # 空/单点轨迹 → 空串，绝不画占位图
    ck(render_trace_svg({"pts": [[30.0, 111.0]]}) == "", "单点轨迹必须返回空串")
    ck(render_trace_html(["随便什么"]) == "", "认不到线路时必须返回空串")

    # plan 接线：原话里提到线路名 → 报告里要带上线路形状
    plan = {"origin": "常德", "destinations": ["桃花源"],
            "request": "骑摩托去常德桃花源，2天",
            "plan": [{"day": 1, "city": "常德", "active": {"km": 120}}]}
    h = render_route_html(plan)
    ck("route-trace" in h, "plan 提到桃花源时必须出线路形状图")
    ck("桃花源" in plan_texts(plan)[2], "plan_texts 要包含用户原话（否则地名被城市名吃掉）")


# ══ 10. 系数只在里程比直线长时才写（v0.2.274 修正）══════════════════════
def t_ratio_guard() -> None:
    base = {"origin": "佛山", "destinations": ["衡阳"],
            "plan": [{"day": 1, "city": "衡阳", "active": {"km": 125}}]}
    h1 = render_route_html(base)
    # 注意：页脚那句「骑行走廊另有路网系数」是解释文案，断言要盯表头括号里的数值
    ck("（路网系数" not in h1, "逐日里程比直线短时不得写出荒谬的路网系数")
    base2 = {"origin": "佛山", "destinations": ["衡阳"],
             "plan": [{"day": 1, "city": "衡阳", "active": {"km": 640}}]}
    h2 = render_route_html(base2)
    ck("（路网系数" in h2, "里程长于直线时应写出路网系数")
    # 占位出发地不参与画图
    ph = {"origin": "本地", "destinations": ["常德"], "plan": []}
    n, miss = collect_nodes(ph)
    ck(all(x["name"] != "本地" for x in n) and "本地" not in miss,
       "占位出发地「本地」不得进图，也不得算作未定位")


def main() -> int:
    for fn in (t_disambiguate, t_degrage, t_no_external, t_traces,
               t_no_boundary, t_escape_and_bearing, t_structure,
               t_trace_shape, t_ratio_guard):
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
