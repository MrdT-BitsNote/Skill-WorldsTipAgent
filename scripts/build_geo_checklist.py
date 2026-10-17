#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成《国内地名管控清单》Markdown —— worldstip-travel-planner

给人看的：把 references 里机器数据摊成可查阅、可审校的清单。
用于发现「哪里还是空的」，而不是展示成绩。

用法
----
  python build_geo_checklist.py
  python build_geo_checklist.py --out ../../国内地名管控清单.md
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict

import sys
HERE = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(os.path.dirname(HERE), "references")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import refloader

# 大区 → 展示顺序
REGION_ORDER = ["华北", "东北", "华东", "华中", "华南", "西南", "西北"]
PROV2REGION = {
    "北京市": "华北", "天津市": "华北", "河北省": "华北", "山西省": "华北", "内蒙古自治区": "华北",
    "辽宁省": "东北", "吉林省": "东北", "黑龙江省": "东北",
    "上海市": "华东", "江苏省": "华东", "浙江省": "华东", "安徽省": "华东",
    "福建省": "华东", "江西省": "华东", "山东省": "华东",
    "河南省": "华中", "湖北省": "华中", "湖南省": "华中",
    "广东省": "华南", "广西壮族自治区": "华南", "海南省": "华南",
    "重庆市": "西南", "四川省": "西南", "贵州省": "西南", "云南省": "西南", "西藏自治区": "西南",
    "陕西省": "西北", "甘肃省": "西北", "青海省": "西北", "宁夏回族自治区": "西北",
    "新疆维吾尔自治区": "西北",
    "中国香港": "华南", "中国澳门": "华南", "中国台湾": "华东",
}


def load(name: str) -> dict:
    return refloader.load(name)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(HERE), "国内地名管控清单.md"))
    args = ap.parse_args()

    geo = load("geo_admin.json")
    links = load("destination_links.json")
    sc = load("seasons_climate.json")
    if not geo:
        raise SystemExit("❌ 缺 geo_admin.json，请先跑 build_geo_admin.py")

    meta = geo.get("_meta", {})
    counts = meta.get("counts", {})
    amb = meta.get("ambiguous_short_names", {})
    L: list[str] = []
    A = L.append

    A("# 国内地名管控清单")
    A("")
    A(f"> 数据构建日期：{meta.get('built_at', '-')}　|　"
      f"省 {counts.get('province')} · 市 {counts.get('city')} · 县 {counts.get('county')}")
    A(">")
    A(f"> **数据源**：{meta.get('source', '-')}")
    A(f">")
    A(f"> **用途**：这是`is_domestic()`（判断一个地名是否在中国境内）的唯一权威来源。"
      "境内判定错了，后果是用户**凭空看到签证与保险门禁卡**——境内行程被误判出境，"
      "所以这份清单宁可多不可少。")
    A("")

    # ── 一、判定规则 ──
    A("## 一、判定链路（从硬到软）")
    A("")
    A("| 顺序 | 命中来源 | 强度 | 说明 |")
    A("|---|---|---|---|")
    A("| 1 | `geo_admin.json` 省/市/县任一级 | 硬事实 | 民政部行政区划代码，34省/366市/3006县 |")
    A("| 2 | `destination_links.json` 249 个景点 | 已知真实 | 已收录的国内目的地 |")
    A("| 3 | `SCENIC_ALIAS` 景区别名表 | 人工补充 | 行政区索引外的景区名（九寨沟、宏村…） |")
    A("| 4 | 剥通名后缀 | 推导 | 黄山风景区→黄山、西湖景区→西湖 |")
    A("| 5 | 剥行政后缀 | 推导 | 岳阳市→岳阳、湘西州→湘西 |")
    A("| 6 | 逐步砍尾（**≥3 字下限**） | 推导 | 张家界天门山→张家界 |")
    A("| 7 | 景点名前缀反查 | 推导 | 茶卡→茶卡盐湖（只对景点名，不对行政区） |")
    A("| — | 都不中 → 判**非境内** | 保守 | 走 unknown 灰灯「待查」，绝不反推国别 |")
    A("")
    A("**为什么不反过来做排除法**（不在出境名单就算境内）："
      "排除法会把拼错或生僻的**境外**地名判成境内，导致出境用户漏掉签证与保险门禁。"
      "那是硬安全风险，比多显示一个待查灯严重得多。")
    A("")

    # ── 二、安全约束 ──
    A("## 二、两条不可放宽的安全约束")
    A("")
    A("### 约束 1：砍尾必须保留 ≥3 字")
    A("")
    A("曾因砍尾无长度下限，导致两个**境外城市被误判为境内**：")
    A("")
    A("| 输入 | 砍尾结果 | 撞上 | 后果 |")
    A("|---|---|---|---|")
    A("| 吉隆坡（马来西亚） | 吉隆 | 西藏日喀则市吉隆县 | 漏掉签证门禁 |")
    A("| 多伦多（加拿大） | 多伦 | 内蒙古锡林郭勒盟多伦县 | 漏掉签证门禁 |")
    A("")
    A("因此砍尾只在**输入 ≥4 字**且**砍完≥3 字**时启用。这两例现在均正确判为出境。")
    A("")
    A("### 约束 2：前缀反查只对景点名生效")
    A("")
    A("`茶卡`→`茶卡盐湖` 这类前缀反查**绝不用于行政区**，"
      "否则「岳」会前缀命中「岳阳」，造成跨省误判。")
    A("")

    # ── 三、分省明细 ──
    A("## 三、分省明细")
    A("")
    cities_by_prov: dict[str, list] = defaultdict(list)
    counties_by_prov: dict[str, int] = defaultdict(int)
    for c in geo.get("city") or []:
        cities_by_prov[c.get("province", "")].append(c)
    for c in geo.get("county") or []:
        counties_by_prov[c.get("province", "")] += 1

    dest_by_prov: dict[str, list] = defaultdict(list)
    for name, rec in (links.get("destinations") or {}).items():
        p = rec.get("province") or rec.get("admin1") or ""
        if p:
            dest_by_prov[p].append((name, rec))

    provs = geo.get("province") or []
    grouped: dict[str, list] = defaultdict(list)
    for p in provs:
        grouped[PROV2REGION.get(p["name"], "其他")].append(p)

    for region in REGION_ORDER + (["其他"] if grouped.get("其他") else []):
        items = grouped.get(region) or []
        if not items:
            continue
        A(f"### {region}")
        A("")
        A("| 省/直辖市/特别行政区 | 地级市 | 县级 | 已收录景点 | 关联能力 |")
        A("|---|---:|---:|---:|---|")
        items_sorted = sorted(items, key=lambda x: -len(dest_by_prov.get(x["name"], [])))
        for p in items_sorted:
            name = p["name"]
            cs = sorted(cities_by_prov.get(name, []), key=lambda x: x["name"])
            ds = dest_by_prov.get(name, [])
            linksum = []
            if any(r.get("linked", {}).get("food_guide") for _, r in ds):
                linksum.append("美食")
            if any(r.get("linked", {}).get("poi") for _, r in ds):
                linksum.append("票务")
            if any(r.get("linked", {}).get("station_codes") for _, r in ds):
                linksum.append("车站")
            if any("高原" in r.get("tags", []) or "高海拔" in r.get("tags", []) for _, r in ds):
                linksum.append("高原")
            if any(any(t.startswith("边境") for t in r.get("tags", [])) for _, r in ds):
                linksum.append("边境")
            city_n = len(cs)
            # 直辖市/特别行政区（如北京）在源数据里市名==省名且被剔除「市辖区」，
            # 会显示为 0；这里补上 1，避免读起来像"没有下辖市"。
            if city_n == 0 and name in ("北京市", "天津市", "上海市", "重庆市",
                                        "中国香港", "中国澳门", "中国台湾"):
                city_n = 1
                shown_cities = "市辖区（直辖）"
            else:
                shown_cities = ("、".join(c["name"] for c in cs[:6]) + ("…" if city_n > 6 else "")) if cs else "—"
            A(f"| {name} | {city_n} | {counties_by_prov.get(name, 0)} | {len(ds)} | {'、'.join(linksum) or '—'} |")
        A("")

    # ── 四、景点相关性 ──
    A("## 四、景点相关性挂载")
    A("")
    if links:
        cov = links.get("coverage", {})
        A(f"已挂载 **{cov.get('total_destinations')}** 个景点到省/市/县与能力库。相关性全部由程序"
          "按现有 references 的匹配规则**复算**，不是手工填写。")
        A("")
        A("| 维度 | 覆盖 | 说明 |")
        A("|---|---:|---|")
        A(f"| 省市归属 | {cov.get('admin_resolved')}/{cov.get('total_destinations')} "
          f"({cov.get('admin_resolved_pct')}%) | 精确 → 去通名 → 大区唯一解三级降级 |")
        A(f"| 气候区 | {cov.get('climate_resolved')}/{cov.get('total_destinations')} "
          f"({cov.get('climate_resolved_pct')}%) | 按 seasons_climate 自带 match_rules 复算 |")
        A(f"| 必吃美食 | {cov.get('has_food_guide')} | 命中 food_guide 的城市 |")
        A(f"| 景点票务 | {cov.get('has_poi')} | 命中 poi 库 |")
        A(f"| 车站/机场 | {cov.get('has_station_codes')} | 按城市名前缀匹配 3404 个站点 |")
        A(f"| 高原/高海拔 | {cov.get('high_altitude')} | 触发 altitude_playbook |")
        A(f"| 边境 | {cov.get('border')} | 触发边境管控提示 |")
        A(f"| 海岛 | {cov.get('island')} | 触发海岛交通/保险提示 |")
        A(f"| 民族地区 | {cov.get('ethnic_region')} | 触发民族文化禁忌与礼仪 |")
        A(f"| 归属存在歧义 | {cov.get('ambiguous_admin')} | 需按全称消歧，不得静默取首个 |")
        A("")

        un = links.get("unresolved_admin") or []
        A(f"### 待人工补录（{len(un)} 个）")
        A("")
        A("这些是**景区级地名**，既不在 3006 个县级行政区里，"
          "`destinations.json` 的 `admin1` 省名又是空的，程序无法可靠推导。")
        A("**必须人工补，不允许用推测值填充**——挂错会让票务/美食/高原数据用错地方。")
        A("")
        if un:
            A("```")
            for i in range(0, len(un), 6):
                A("  ".join(f"{n:<10}" for n in un[i:i + 6]).rstrip())
            A("```")
        A("")

        nc = links.get("unresolved_climate") or []
        if nc:
            A(f"### 气候区未匹配（{len(nc)} 个）")
            A("")
            A("```")
            for i in range(0, len(nc), 6):
                A("  ".join(f"{n:<10}" for n in nc[i:i + 6]).rstrip())
            A("```")
            A("")
            A("> 说明：其中一部分是**主题乐园/综合园区**（迪士尼、欢乐谷、方特），"
              "分属不同城市，按南方估算即可；港澳台三条属行政类别条目，"
              "按各自气候处理（湿热海洋性）。")
            A("")

    # ── 五、歧义 ──
    A("## 五、短名歧义对照表")
    A("")
    A(f"同一短名对应多个同级行政区，共 **{amb.get('count', 0)}** 组。"
      "对境内判定**无影响**（撞车项同属中国），但景点归属到省市时必须按全称或省份消歧。")
    A("")
    amap = amb.get("map") or {}
    if amap:
        A("| 短名 | 对应行政区 |")
        A("|---|---|")
        for k, v in list(amap.items()):
            A(f"| {k} | {'、'.join(v)} |")
    A("")

    # ── 六、维护 ──
    A("## 六、维护方式")
    A("")
    A("```bash")
    A("# 1) 重建行政区索引（需先下载 provinces/cities/areas.json 或用 --fetch 自动下载）")
    A("python scripts/build_geo_admin.py --fetch")
    A("")
    A("# 2) 重算景点相关性")
    A("python scripts/build_destination_links.py")
    A("")
    A("# 3) 重新生成本清单")
    A("python scripts/build_geo_checklist.py")
    A("")
    A("# 4) 验证境内判定（正负样本）")
    A("python scripts/geo_lookup.py")
    A("```")
    A("")
    A("**新增国内景点时**：加进 `destinations.json` 或 `geo_lookup.SCENIC_ALIAS`，"
      "然后重跑第 2、3 步。**不要**再去动已删除的手写白名单。")
    A("")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    size = os.path.getsize(args.out) / 1024
    print(f"✅ 已生成 {args.out}  ({size:.0f} KB, {len(L)} 行)")
    print(f"   分省: {len(provs)} · 待人工补录: {len(links.get('unresolved_admin') or [])} · "
          f"歧义组: {amb.get('count', 0)}")


if __name__ == "__main__":
    main()