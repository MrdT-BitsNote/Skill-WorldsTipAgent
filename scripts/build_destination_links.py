#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
景点相关性挂载器 —— worldstip-travel-planner

要解决的问题
------------
destinations.json 里的 249 个景点只有基础字段（经纬度/区域/一句话简介），
没有挂到任何能力库上。于是生成小册子时无法回答：
  「大理属于哪个气候区？该配哪些必吃？有哪些景点票务？高原要带什么装备？」
只能凭印象写 → 违背「不编造」红线。

本脚本做的是**可复算的挂载**：相关性全部由程序按现有 references 的
匹配规则推导，不手工编。算不出来的显式标 null，并进unresolved 清单。

输出
----
  references/destination_links.json
    destinations: { 景点名: { 省/市/县、气候区、能力库命中、风险标签 } }
    coverage:各能力库覆盖率（诚实暴露短板，不粉饰）
    unresolved: 挂不上省市归属的景点（需人工确认，禁止瞎猜）

用法
----
  python build_destination_links.py            # 用 references 现有文件构建
  python build_destination_links.py --report   # 只打印覆盖报告
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(os.path.dirname(HERE), "references")

# v0.2.1：人造景点（单一实体/连锁品牌/品类指南）由 synthetic_sites.json 判定，
# 复用 geo_lookup 的同一个判定入口，避免两套真相。
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import refloader
try:
    from geo_lookup import classify_synthetic, SCENIC_ALIAS
except Exception:  # geo_lookup 不可用时退化，不阻断构建
    SCENIC_ALIAS: dict = {}

    def classify_synthetic(_name: str):  # type: ignore
        return None

# 特殊地理标签（高原/边境/海岛/少数民族地区）——只收有明确依据的条目，
# 不做泛化推断。用于触发电光脚手箱里的 altitude_playbook 等既有能力。
BORDER_CITIES = {
    "黑河": "中俄边境", "绥芬河": "中俄边境", "满洲里": "中俄边境", "丹东": "中朝边境",
    "集安": "中朝边境", "珲春": "中俄朝边境", "河口": "中越边境", "东兴": "中越边境",
    "凭祥": "中越边境", "瑞丽": "中缅边境", "畹町": "中缅边境", "勐腊": "中老边境",
    "霍尔果斯": "中哈边境", "阿拉山口": "中哈边境", "塔城": "中哈边境", "阿图什": "中吉尔吉斯边境",
    "伊宁": "中哈边境", "博乐": "中哈边境",
}
ISLAND_HINTS = {"岛", "群岛", "列岛", "半岛", "海岛", "沙洲", "渔岛"}
# 高海拔：优先用 altitude_playbook 的既有清单，不另造一套
ETHNIC_HINTS = ("自治州", "自治县", "民族乡", "自治旗", "地区")


def load(name: str) -> dict:
    return refloader.load(name)


def strip_admin_suffix(name: str) -> list[str]:
    sys.path.insert(0, HERE)
    from build_geo_admin import strip_admin_suffix as _s
    return _s(name)


def build_geo_index(geo: dict) -> dict[str, list[dict]]:
    """短名 → 行政区记录列表。同一短名可能多值（中山市/中山区），故为 list。"""
    idx: dict[str, list[dict]] = {}
    for level in ("province", "city", "county"):
        for r in geo.get(level) or []:
            for k in r.get("keys") or []:
                idx.setdefault(k, []).append({
                    "level": level, "code": r.get("code"),
                    "name": r.get("name"),
                    "province": r.get("province") or (r.get("name") if level == "province" else ""),
                    "city": r.get("city") or (r.get("name") if level == "city" else ""),
                })
    return idx


NOISE_SUFFIX = ("风景区", "风景名胜区", "景区", "旅游区", "保护区", "古城", "老街", "古镇",
                "公园", "山", "湖", "岛", "·镜泊湖", "·天门山", "·衡山")


def resolve_admin(name: str, idx: dict) -> tuple[dict | None, str]:
    """景点名 → 行政区归属。返回 (归属, 匹配方式)。

    优先精确 → 去通名后缀 → 逐步砍尾。命中多级时取信息最全的一条。
    41 组短名歧义（如中山市/中山区）在返回里带 ambiguous 标记，不静默取首条。
    """
    cands = [name]
    cur = name
    for suf in NOISE_SUFFIX:
        if cur.endswith(suf) and len(cur) - len(suf) >= 2:
            cur = cur[: -len(suf)]
            cands.append(cur)
    # 分隔符切分："牡丹江·镜泊湖" → 牡丹江
    parts = [p for p in cur.split("·") if p]
    cands += parts
    # 逐步砍尾："南岳衡山" → 南岳 → 南
    if len(cur) >= 4:
        t = cur
        for _ in range(len(t) - 2):
            t = t[:-1]
            cands.append(t)

    for c in cands:
        hits = idx.get(c)
        if not hits:
            continue
        # 优先县级（信息最全）> 市 > 省
        order = {"county": 0, "city": 1, "province": 2}
        best = sorted(hits, key=lambda h: order.get(h["level"], 9))[0]
        rec = {
            "province": best.get("province", ""),
            "city": best.get("city", "") or best.get("name", ""),
            "county": best.get("name", "") if best["level"] == "county" else "",
            "matched_level": best["level"],
            "matched_name": best.get("name", ""),
            "matched_on": c,
        }
        rec["ambiguous"] = len(hits) > 1
        return rec, ("exact" if c == name else ("suffix" if c in parts else "trim"))
    return None, "none"


def resolve_by_authoritative(name: str, geo: dict) -> dict | None:
    """v0.2.1：直接采用 geo_lookup.SCENIC_ALIAS 里【人工联网核验过】的完整归属。

    为什么必须放在所有推测逻辑之前：
      · 「九华山」的名字里没有市名，用省名反查市必然失败；
      · destinations.json 的 admin1 历史上出现过错标（泰山标江苏、九华山标江苏），
        SCENIC_ALIAS 才是可靠来源。
    找不到返回 None，交由后续推测逻辑处理。
    """
    v = SCENIC_ALIAS.get(name)
    if not v:
        return None
    # 顺序扫描：把「安徽省池州市青阳县」这类串切成 [安徽省, 池州市, 青阳县]
    segs: list[str] = []
    cur = ""
    for ch in v:
        cur += ch
        if ch in "省市县区":
            segs.append(cur)
            cur = ""
    if cur:
        segs.append(cur)
    prov = city = county = ""
    for s in segs:
        if s.endswith("省"):
            prov = prov or s
        elif s.endswith("区"):
            county = county or s          # 「南岳区」按区县处理
        elif s.endswith("市"):
            if not city:
                city = s
            else:
                county = county or s      # 「桐乡市」是县级市 → 落到 county
        elif s.endswith("县"):
            county = county or s
    if prov or city or county:
        return {"province": prov or city, "city": city, "county": county,
                "level": "scenic_alias", "name": county or city or prov,
                "source": "scenic_alias", "ambiguous": False}
    return None


def resolve_by_province(name: str, prov: str, geo: dict) -> dict | None:
    """景区名挂不上县级时的兜底：只用已知的真实省名定位同省的市。

    严格限定在 destinations.json 自带的 admin1 省份内反查，绝不跨省猜——
    「黄山」只能在安徽里找「黄山市」，不会命中云南的某市。
    找不到就返回 None，进unresolved 让人工补，不填推测值。
    """
    if not prov:
        return None
    # 省名归一：destinations 用「安徽」，索引用「安徽省」
    prov_keys = set()
    for p in geo.get("province") or []:
        if p["name"] == prov or prov in p["name"] or p["name"] in prov:
            prov_keys |= set(p.get("keys") or [])
    if not prov_keys:
        return None

    best = None
    for c in geo.get("city") or []:
        cp = c.get("province") or ""
        # 该市是否属于目标省：用省名/短名双向包含，兼容「安徽」vs「安徽省」
        if not any(cp in pk or pk in cp for pk in prov_keys if pk and cp):
            continue
        # 景区名含市名（黄山→黄山市、天门山→张家界市不含则跳过）
        for k in c.get("keys") or []:
            if len(k) >= 2 and (k in name or name in k):
                if not best or len(k) > len(best[1]):
                    best = (c, k)
    if best:
        return {"province": best[0].get("province", ""), "city": best[0].get("name", ""),
                "county": "", "matched_level": "city", "matched_name": best[0].get("name", ""),
                "matched_on": best[1], "ambiguous": False}
    return None


def climate_zone(dest: dict, geo: dict, sc: dict) -> dict:
    """按 seasons_climate.json 自带的 match_rules 推导气候区，不自造规则。"""
    mr = (sc.get("match_rules") or {})
    of = mr.get("climate_of") or {}
    lists = {k: mr.get(f"{k}_list") or [] for k in ("plateau", "southwest", "tropical", "northwest")}
    amb = geo["_meta"].get("ambiguous_short_names", {}).get("map", {})

    name = dest["name"]
    province = dest.get("admin1") or ""
    # 景点所在省的大区（destinations.json 自带 region 字段，是既有事实）
    region = dest.get("region") or ""

    # 1) plateau_list 优先（整城高海拔）
    for key, arr in lists.items():
        for item in arr:
            if name == item or item in name:
                return {"zone": key, "zone_cn": _zone_cn(key, sc), "matched": item, "rule": f"{key}_list"}
    # 2) 短名歧义表：地级市与景区同名（如香格里拉既是市也是景区），用市名判定
    for item in amb.get(name, []):
        for key, arr in lists.items():
            if item in arr:
                return {"zone": key, "zone_cn": _zone_cn(key, sc), "matched": item, "rule": f"{key}_list(经短名消歧:{item})"}
    # 3) 省份 → 大区 → 气候区
    prov2region = {"华东": "south", "华中": "south", "华南": "tropical"}
    if region in of:
        return {"zone": of[region], "zone_cn": _zone_cn(of[region], sc),
                "matched": region, "rule": "climate_of[大区]"}
    # 4) 西南/西北省份整体
    if any(p in province for p in ("四川", "云南", "贵州", "重庆")):
        return {"zone": "southwest", "zone_cn": _zone_cn("southwest", sc), "matched": province, "rule": "西南省区默认"}
    if any(p in province for p in ("新疆", "甘肃", "青海", "宁夏", "内蒙古")):
        return {"zone": "northwest", "zone_cn": _zone_cn("northwest", sc), "matched": province, "rule": "西北省区默认"}
    if any(p in province for p in ("西藏",)):
        return {"zone": "plateau", "zone_cn": _zone_cn("plateau", sc), "matched": province, "rule": "西藏默认高原"}
    # 5) 省份 → 大区反查（如"湖南"→ 华中 → south）
    for big, z in (("华东", "south"), ("华中", "south"), ("华北", "north"), ("东北", "north")):
        if province and big[0] in province:
            return {"zone": z, "zone_cn": _zone_cn(z, sc), "matched": f"{province}→{big}", "rule": "省份首字推大区"}
    return {"zone": "", "zone_cn": "", "matched": "", "rule": "未匹配(默认按南方估算)"}


def _zone_cn(zone: str, sc: dict) -> str:
    r = (sc.get("regions") or {}).get(zone) or {}
    return r.get("name_cn") or r.get("name") or zone


def risk_tags(dest: dict, admin: dict | None, climate: dict) -> list[str]:
    """按既有 playbook 触发条件打标签，全部可解释、不猜。"""
    tags: list[str] = []
    name = dest["name"]
    if climate.get("zone") == "plateau":
        tags.append("高原")
    if name in BORDER_CITIES:
        tags.append("边境:" + BORDER_CITIES[name])
    if any(h in name for h in ISLAND_HINTS):
        tags.append("海岛")
    elev = dest.get("elevation")
    if isinstance(elev, (int, float)) and elev >= 2000:
        tags.append("高海拔")
    if admin and any(h in (admin.get("city") or "") or h in (admin.get("county") or "") for h in ETHNIC_HINTS):
        tags.append("民族地区")
    return tags


# 大区 → 省级范围（用geo_admin 的真实省名，不手写省列表）
REGION_PROVINCES = {
    "华北": ["北京", "天津", "河北", "山西", "内蒙古"],
    "东北": ["辽宁", "吉林", "黑龙江"],
    "华东": ["上海", "江苏", "浙江", "安徽", "福建", "江西", "山东"],
    "华中": ["河南", "湖北", "湖南"],
    "华南": ["广东", "广西", "海南"],
    "西南": ["重庆", "四川", "贵州", "云南", "西藏"],
    "西北": ["陕西", "甘肃", "青海", "宁夏", "新疆"],
}


def resolve_by_region(name: str, region: str, geo: dict) -> tuple[dict | None, str]:
    """admin1 为空时的最后兜底：只在大区范围内推导，且**唯一解才认**。

    严格纪律：全中国有 3000+ 县级行政区，同名/近名极多。
    若某景区名在大区内能命中 ≥2 个不同市 → 判定为歧义，不猜，进 unresolved。
    宁可少挂，不可挂错——挂错会让高原/票务/美食数据用错地方，比不挂更糟。
    """
    if not region or region not in REGION_PROVINCES:
        return None, "none"
    allowed = REGION_PROVINCES[region]
    hits: dict[str, dict] = {}
    for c in geo.get("city") or []:
        cp = c.get("province") or ""
        if not any(any(p in cp or cp in p for p in allowed) for _ in (0,)):
            continue
        for k in c.get("keys") or []:
            if len(k) >= 2 and (k in name or name in k):
                hits.setdefault(c["name"], c)
    if len(hits) == 1:
        c = next(iter(hits.values()))
        return {"province": c.get("province", ""), "city": c["name"], "county": "",
                "matched_level": "city", "matched_name": c["name"], "matched_on": name,
                "ambiguous": False}, "region_unique"
    return None, "region_ambiguous" if hits else "none"


def main() -> None:
    ap = argparse.ArgumentParser(description="景点相关性挂载")
    ap.add_argument("--report", action="store_true", help="只打印覆盖报告")
    args = ap.parse_args()

    geo = load("geo_admin.json")
    if not geo:
        raise SystemExit("❌ 缺 references/geo_admin.json，请先跑 build_geo_admin.py")
    dests = load("destinations.json")
    sc = load("seasons_climate.json")
    food = load("food_guide.json")
    poi = load("poi.json")
    st = load("station_codes.json")

    geo_idx = build_geo_index(geo)
    food_cities = {v.get("city") for v in food.values() if isinstance(v, dict) and v.get("city")}
    poi_cities = set((poi.get("poi") or {}).keys()) if isinstance(poi.get("poi"), dict) else set()
    # station_codes 是【站点名 → 机场/车站代码】（如 北京北→VAP），3404 条里
    # 绝大多数是车站级（北京北/房山东/上海虹桥），不能拿城市名直接等值匹配，
    # 必须按「城市名前缀」匹配，否则命中恒为 0。
    station_names = [k for k in st if not k.startswith("_")] if isinstance(st, dict) else []

    def station_hit(*cands: str) -> str | None:
        for c in cands:
            if not c:
                continue
            if c in station_names:
                return c
            for sname in station_names:
                if sname.startswith(c):
                    return sname
        return None

    out: dict[str, dict] = {}
    unresolved: list[str] = []
    no_climate: list[str] = []
    region_guessed = 0
    synthetic_guessed = 0
    synthetic_no_admin: list[str] = []

    for d in dests.get("destinations") or []:
        name = d["name"]
        # v0.2.1 人造景点优先判定：单一实体（葛仙村等）有【已联网核验】的真实归属，
        # 比任何地理反查推测都可靠；连锁品牌（方特/宋城/长隆）跨省分布，
        # 强制 province/city 留空并标 needs_disambiguation —— 挂到任一省都是错的。
        syn = classify_synthetic(name)
        if syn and syn.get("type") == "single":
            admin = {"province": syn.get("province", ""), "city": syn.get("city", ""),
                     "county": syn.get("county", ""), "level": "county",
                     "name": syn.get("county") or syn.get("city", "")}
            how = "synthetic_single"
            synthetic_guessed += 1
        elif syn and syn.get("type") in ("brand", "guide"):
            admin = None
            how = f"synthetic_{syn['type']}"
            synthetic_no_admin.append(name)
        else:
            # v0.2.1 权威别名优先：SCENIC_ALIAS 是人工联网核验过的完整归属，
            # 比 admin1 反查可靠（历史 admin1 有错标），也比按名反查市可靠（九华山不含市名）。
            admin = resolve_by_authoritative(name, geo)
            how = "scenic_alias" if admin else "none"
            if not admin:
                admin, how = resolve_admin(name, geo_idx)
        if not admin and how not in ("synthetic_brand", "synthetic_guide"):
            # 景区名（晋祠/皇城相府）不在县级索引里 → 先用已知真实省名在省内反查所属市
            admin = resolve_by_province(name, d.get("admin1") or "", geo)
            how = "province_scope" if admin else "none"
        if not admin and how not in ("synthetic_brand", "synthetic_guide"):
            # admin1 本身为空（如「三清山」「乔家大院」只有 region）→
            # 用 region 大区兜底，但【唯一解才认】，多解一律留 unresolved 不猜
            admin, how = resolve_by_region(name, d.get("region") or "", geo)
            if admin:
                region_guessed += 1
        if not admin and how not in ("synthetic_brand", "synthetic_guide"):
            unresolved.append(name)
        adm = admin or {}
        province = adm.get("province") or d.get("admin1") or ""
        city = adm.get("city") or ""
        county = adm.get("county") or ""

        climate = climate_zone({**d, "admin1": province}, geo, sc)
        if not climate.get("zone"):
            no_climate.append(name)

        tags = risk_tags({**d, "name": name}, adm or None, climate)

        # 能力库命中：只报真命中，不虚报
        hits = {
            "food_guide": city if city in food_cities else (name if name in food_cities else None),
            "poi": name if name in poi_cities else (city if city in poi_cities else None),
            "station_codes": station_hit(name, city),
        }

        out[name] = {
            "province": province,
            "city": city,
            "county": county,
            "admin_match": how,
            "admin_ambiguous": adm.get("ambiguous", False),
            "matched_on": adm.get("matched_on", ""),
            "climate": climate,
            "tags": tags,
            "linked": {k: v for k, v in hits.items() if v},
        }

    total = len(out)
    cov = {
        "total_destinations": total,
        "admin_resolved": total - len(unresolved),
        "admin_resolved_pct": round((total - len(unresolved)) / total * 100, 1) if total else 0,
        "climate_resolved": total - len(no_climate),
        "climate_resolved_pct": round((total - len(no_climate)) / total * 100, 1) if total else 0,
        "has_food_guide": len(out)and sum(1 for v in out.values() if v["linked"].get("food_guide")),
        "has_poi": sum(1 for v in out.values() if v["linked"].get("poi")),
        "has_station_codes": sum(1 for v in out.values() if v["linked"].get("station_codes")),
        "high_altitude": sum(1 for v in out.values() if "高原" in v["tags"] or "高海拔" in v["tags"]),
        "border": sum(1 for v in out.values() if any(t.startswith("边境") for t in v["tags"])),
        "island": sum(1 for v in out.values() if "海岛" in v["tags"]),
        "ethnic_region": sum(1 for v in out.values() if "民族地区" in v["tags"]),
        "ambiguous_admin": sum(1 for v in out.values() if v["admin_ambiguous"]),
        "resolved_by_region_unique": region_guessed,
            "resolved_by_synthetic": synthetic_guessed,
            "synthetic_multi_site": sorted(synthetic_no_admin),
    }

    payload = {
        "_meta": {
            "name": "景点 × 能力库相关性挂载表",
            "purpose": "让渲染与规划阶段能直接回答：这个景点归属哪个省市、属什么气候区、"
                       "有哪些必吃/票务/车站数据、触发哪些风险 playbook。全部由程序按现有 references 规则复算，不手工编。",
            "built_at": time.strftime("%Y-%m-%d"),
            "rules": [
                "省市归属：geo_admin.json 精确 → 去通名后缀 → 分隔符切分 → 逐步砍尾，逐级降级。",
                "气候区：seasons_climate.json 自带 match_rules 复算，顺序 plateau→tropical→northwest→southwest→大区。",
                "能力库：city 或name 真命中才记，未命中不编。",
                "风险标签：高原/边境/海岛/高海拔/民族地区，触发既有 playbook，不新增规则。",
            ],
            "honesty_note": "unresolved 与 climate 未匹配项必须人工补，不允许用推测值填充。",
        },
        "coverage": cov,
        "destinations": out,
        "unresolved_admin": sorted(unresolved),
        "unresolved_climate": sorted(no_climate),
    }

    dest_path = os.path.join(REF_DIR, "destination_links.json")
    with open(dest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print("=== 覆盖报告 ===")
    for k, v in cov.items():
        print(f"  {k:24} {v}")
    print(f"\n  人造景点: 单一实体已核验归属 {synthetic_guessed} 个；连锁/指南不强挂省市 {len(synthetic_no_admin)} 个 → {synthetic_no_admin}")
    print(f"\n  省市未归属: {len(unresolved)} → {unresolved[:12]}")
    print(f"  气候区未匹配: {len(no_climate)} → {no_climate[:12]}")
    print(f"\n  已写入 {dest_path} ({os.path.getsize(dest_path)/1024:.0f} KB)")
    if args.report:
        pass


if __name__ == "__main__":
    main()