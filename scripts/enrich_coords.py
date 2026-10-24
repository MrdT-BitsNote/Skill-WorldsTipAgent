#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为 destinations.json 补全经纬度坐标（天气查询的前置依赖）。

用法:
  python enrich_coords.py            # 仅补全缺失坐标的条目
  python enrich_coords.py --force    # 全部重新抓取
  python enrich_coords.py --limit 20 # 试跑前20 条

坐标来源: Open-Meteo Geocoding API (免授权)
天气查询必须有经纬度, 而 234 个目的地的攻略页均不含坐标, 故需离线预置。
坐标会缓存进 destinations.json, 之后查天气无需再联网定位。
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "references" / "destinations.json"
API = "https://geocoding-api.open-meteo.com/v1/search"
UA = "Mozilla/5.0 (compatible; ai-travel-guide/1.0)"
DELAY = 0.35  # 礼貌限速, 避免被限流

# 区域 -> 该区域涵盖的省份简称(取自 sitemap 的 META.full)。
# 用于消歧时拼接到地名前做二次查询, 避免同名地点误配。
# 注意: 只能定位到省级, 无法细化到市/县, 故仅在首次查询无果时启用。
REGION_PROVINCES = {
    "华北": ["北京", "天津", "河北", "山西", "内蒙古"],
    "东北": ["辽宁", "吉林", "黑龙江"],
    "华东": ["上海", "江苏", "浙江", "安徽", "福建", "江西", "山东"],
    "华中": ["河南", "湖北", "湖南"],
    "华南": ["广东", "广西", "海南"],
    "西南": ["四川", "重庆", "贵州", "云南", "西藏"],
    "西北": ["陕西", "甘肃", "宁夏", "青海", "新疆"],
}


# GeoNames feature_code 权重: 行政实体等级越高越可能是用户要找的"城市"。
# 这是实测中最有效的判别依据 —— 省级/市级的城市条目与零散同名村落的
# 区别不在名称, 而在 feature_code 与 population。
FEATURE_RANK = {
    "PPLC": 5,  # 首都
    "PPLA": 5,  # 一级行政区(省/直辖市)
    "PPLA2": 4,  # 二级行政区(地级市)← 绝大多数旅游目的地属此级
    "PPLA3": 3,  # 三级(县级市)
    "PPLA4": 2,
    "PPL": 1,  # 聚居地(无行政层级) ← 同名村落的典型代码
    "PPLL": 0,
    "PPLX": 0,  # 聚居地片段
}


def geocode(name: str, region: str) -> dict | None:
    """地理编码。返回 dict 或 None。

    ## 为什么必须多重校验(实测教训)
    免费地理编码接口对中文地名极不可靠。实测三种典型错误:
      1. 跨省同名: 搜"承德" → 吉林某同名点(正确是河北承德)
      2. 同省异型: 搜"大理" → 四川泸州市辖下"大理"(PPL, 无人口)
         正确是云南大理市(PPLA2, 人口 23 万), 需查"大理市"才命中
      3. 主体缺失: 搜"洛阳" → 福建泉州某"洛阳"村(PPL, 人口 6.6万)
         河南洛阳市(PPLA2, 人口 139 万)需查"洛阳市"才命中

    因此策略是: 省份校验 + 名称校验 + feature_code/人口排序, 三者缺一不可。
    全部尝试失败时返回 None —— 留空远好于填入错误坐标(会让用户拿到几百公里外的天气)。
    """
    def q(kw: str) -> list[dict]:
        qs = urllib.parse.urlencode(
            {"name": kw, "count": 10, "language": "zh", "format": "json"}
        )
        # 该接口偶发失败, 重试 2 次再放弃, 否则会误判为"无此地名"
        last_err = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(f"{API}?{qs}", headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.load(r)
                return [x for x in data.get("results", []) if x.get("country_code") == "CN"]
            except Exception as e:
                last_err = e
                time.sleep(0.4 * (attempt + 1))  # 失败退避, 成功无延迟
        if last_err:
            print(f"    [warn] 查询 '{kw}' 失败: {last_err}", file=sys.stderr)
        return []

    provinces = REGION_PROVINCES.get(region, [])

    def acceptable(item: dict) -> bool:
        """结果的省份必须与目标区域辖省一致。"""
        if not provinces:
            return True  # 主题乐园/港澳台/海外等无省份约束
        blob = f"{item.get('admin1','')}{item.get('admin2','')}"
        return any(p in blob for p in provinces)

    def best_of(rows: list[dict], want: str) -> dict | None:
        """从候选中挑最可信的一条。校验两道:
        1) 省份: admin1/admin2 必须落在该区域辖省内(挡掉跨省同名地点)
        2) 名称: 候选的 name 必须与查询词相符(挡掉「洛阳」命中「洛阳村」之类)
        排序: 省级精确命中 > 人口多者。
        例: 搜"包头"会同时返回 内蒙古包头市 与 河北邯郸市,
            前者 admin1 精确命中且人口 215 万, 排序后自然选中前者。
        """
        def name_ok(item: dict) -> bool:
            """候选名须与查询词相符, 允许行政区后缀差异。
            允许: 大理 ↔ 大理市 / 呼伦贝尔 ↔ 呼伦贝尔市
            拒绝: 洛阳 ↔ 洛阳村、洛阳 ↔ 洛阳市某同名外地地点
            """
            n = (item.get("name") or "").rstrip("市县区镇乡村")
            w = want.rstrip("市县区镇乡村")
            return n == w or n in want or want in n

        cands = [
            x for x in rows
            if acceptable(x) and name_ok(x)
        ]
        if not cands:
            return None
        prov_set = set(provinces)
        # 排序优先级: 省级精确命中 > 行政等级(PPLA2 市级优于 PPL 村落) > 人口
        cands.sort(
            key=lambda x: (
                x.get("admin1", "") in prov_set,
                FEATURE_RANK.get(x.get("feature_code", ""), 1),
                x.get("population") or 0,
            ),
            reverse=True,
        )
        top = cands[0]
        # 排除「同名小村落」的判定: 行政等级为聚居地(PPL/PPLX) **且**
        # 无人口数据。景区类目的地(五台山、张家界)本身就是 PPL 级,
        # 但它们通常带人口数据; 而搜"大理"返回的四川某"大理"
        # 是无人口的零散聚居地。故用「无人口」而非「低等级」作为排除条件。
        if (
            FEATURE_RANK.get(top.get("feature_code", ""), 1) <= 1
            and not top.get("population")
        ):
            return None
        return _pack(top)

    # 尝试 1: 裸地名查询(多数城市名可直接命中, 只 1 次请求)
    hit = best_of(q(name), name)
    if hit:
        return hit

    # 尝试 2: 加行政区后缀重试。
    # 实测: 搜"大理"只返回四川泸州辖下的一处"大理"(PPL, 无人口),
    #搜"大理市"才返回云南大理(PPLA2, 人口 23 万)。故必须试后缀变体。
    for suffix in ("市", "县", "自治州"):
        hit = best_of(q(name + suffix), name)
        if hit:
            return hit

    # 尝试 3: 拼接区域名/代表省重试, 省份与名称仍由上面两道校验把关。
    for kw in (region + name, (provinces[0] + name) if provinces else ""):
        if not kw:
            continue
        hit = best_of(q(kw), name)
        if hit:
            return hit

    return None


def _pack(item: dict) -> dict:
    return {
        "lat": item["latitude"],
        "lon": item["longitude"],
        "admin1": item.get("admin1", ""),
        "elevation": item.get("elevation"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="全部重抓")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条")
    ap.add_argument("--workers", type=int, default=4,
                    help="并发数(默认4; 实测 6 会触发接口限流返回空, 不建议调高)")
    args = ap.parse_args()

    with open(DATA, encoding="utf-8") as f:
        db = json.load(f)

    todo = [d for d in db["destinations"] if args.force or not d.get("lat")]
    if args.limit:
        todo = todo[: args.limit]
    print(f"待处理 {len(todo)} / {len(db['destinations'])} 条")

    # 并发处理。串行时未命中条目需 3 请求 x 重试退避, 全量约 2 小时不可接受。
    # 并发数必须保守: 实测 workers=6 会触发接口限流(HTTP 000), 导致本该命中的
    # 条目被记为"未匹配", 甚至因降级查询而写入错误省份坐标。默认 4较稳。
    def work(d: dict) -> tuple[dict, dict | None, str]:
        try:
            return d, geocode(d["name"], d.get("region", "")), ""
        except Exception as e:
            return d, None, str(e)

    ok = miss = done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, d) for d in todo]
        for fut in as_completed(futures):
            d, g, err = fut.result()
            done += 1
            if g:
                d["lat"], d["lon"] = g["lat"], g["lon"]
                d["admin1"] = g["admin1"]
                if g["elevation"] is not None:
                    d["elevation"] = g["elevation"]
                ok += 1
                print(f"  [{done}/{len(todo)}] {d['name']} -> {g['lat']}, {g['lon']} ({g['admin1']})")
            else:
                miss += 1
                reason = f": {err}" if err else ""
                print(f"  [{done}/{len(todo)}] {d['name']}: 未匹配到可靠结果, 留空{reason}")
            # 每 25 条落盘, 防止中断丢失
            if done % 25 == 0:
                with open(DATA, "w", encoding="utf-8") as f:
                    json.dump(db, f, ensure_ascii=False, indent=1)

    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)

    total = len(db["destinations"])
    have = sum(1 for d in db["destinations"] if d.get("lat"))
    print(f"\n完成: 成功 {ok}, 未匹配 {miss}")
    print(f"坐标覆盖: {have}/{total} ({have / total * 100:.0f}%)")
    print("注: 未匹配的目的地仍可查天气, 需在 fetch_weather.py 中手动传 --lat/--lon")
    return 0


if __name__ == "__main__":
    sys.exit(main())
