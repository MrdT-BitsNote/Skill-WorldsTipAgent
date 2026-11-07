#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorldsTip 自有站点数据接入（moto.worldstip.com / fun.worldstip.com）。

零依赖（仅标准库）。按需懒加载 + 本地缓存（默认 24h）+ 显式降级：
  网络失败 → 读本地缓存 → 无缓存则报『数据不可用』（退出码 2），由调用方降级宿主检索，禁止编造。

用法：
  python3 scripts/site_query.py moto --province 湖南 [--city 长沙] [--type 攻山压弯] [--limit 5]
  python3 scripts/site_query.py fun --city 岳阳市 [--section districts|food|leisure|kids|hotels|malls|specialties] [--grade S] [--limit 10]
  python3 scripts/site_query.py fun --stats
  通用：--json 输出机器可读 JSON；--refresh 强制刷新缓存；--offline 只用缓存；--cache-dir 指定缓存目录

坐标系：两站均为 GCJ-02，与 references/destinations.json 同系；禁止直接配 WGS-84 底图。
"""
import argparse
import json
import random
import re
import sys
import time
import urllib.request
import urllib.error
from collections import Counter
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = json.load(open(ROOT / "references" / "worldstip_sites.json", encoding="utf-8"))
CACHE_DIR = ROOT / ".site_cache"
TTL = SPEC["common_policy"]["cache_ttl_hours"] * 3600
TIMEOUT = SPEC["common_policy"]["timeout_seconds"]
RETRIES = SPEC["common_policy"]["retries"]
EXIT_UNAVAILABLE = 2


class SiteUnavailable(Exception):
    """网络与缓存均不可用——调用方必须降级，不得编造。"""


def _cache_path(url: str, cache_dir: Path) -> Path:
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", url.split("://", 1)[-1])
    return cache_dir / name


def _retryable(exc: Exception) -> bool:
    """只重试幂等 GET 的临时故障；4xx（429 除外）与解析错误立即终止。"""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or exc.code >= 500
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def fetch(url: str, cache_dir: Path = CACHE_DIR, refresh: bool = False,
          offline: bool = False, max_age: float = TTL) -> bytes:
    """带缓存的幂等 GET：显式超时、分类重试、指数退避+抖动、墙钟上限与原子写缓存。"""
    cp = _cache_path(url, cache_dir)
    if offline:
        if cp.exists():
            return cp.read_bytes()
        raise SiteUnavailable(f"离线模式且无缓存：{url}")
    if not refresh and cp.exists() and (time.time() - cp.stat().st_mtime) < max_age:
        return cp.read_bytes()
    last_err = None
    deadline = time.monotonic() + SPEC["common_policy"].get("wall_clock_seconds", 45)
    max_bytes = int(SPEC["common_policy"].get("max_response_bytes", 64 * 1024 * 1024))
    for attempt in range(RETRIES + 1):
        if time.monotonic() >= deadline:
            break
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "WorldsTipSkill/site_query"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                body = r.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError(f"响应超过 {max_bytes} 字节上限")
            cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = cp.with_name(cp.name + ".tmp")
            tmp.write_bytes(body)
            tmp.replace(cp)
            return body
        except Exception as e:
            last_err = e
            if attempt >= RETRIES or not _retryable(e):
                break
            delay = min(2 ** attempt, 4) + random.uniform(0, 0.25)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(delay, remaining))
    if cp.exists():
        # 过期缓存只作降级；调用方仍须输出来源日期与 freshness 状态，不冒充实时数据。
        print(f"WARN 站点请求失败，已降级到本地缓存：{url}（{type(last_err).__name__}）", file=sys.stderr)
        return cp.read_bytes()
    raise SiteUnavailable(f"站点不可达且无缓存：{url}（{type(last_err).__name__}）→ 请降级宿主 WebSearch/WebFetch，勿编造")


def _json(url: str, **kw) -> dict:
    return json.loads(fetch(url, **kw).decode("utf-8"))


def freshness(date_text, review_days: int, today: date | None = None) -> dict:
    """来源时效纯函数：只按来源日期判定，不把缓存新旧等同于数据采集时间。"""
    if not date_text:
        return {"status": "unknown", "age_days": None, "label": "来源日期缺失·待复核"}
    try:
        source_date = datetime.strptime(str(date_text)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {"status": "unknown", "age_days": None, "label": "来源日期异常·待复核"}
    age = ((today or date.today()) - source_date).days
    if age < 0:
        return {"status": "invalid", "age_days": age, "label": "来源日期在未来·待复核"}
    if age > review_days:
        return {"status": "stale", "age_days": age, "label": f"采集已 {age} 天·待复核"}
    return {"status": "current", "age_days": age, "label": f"采集 {age} 天·在复核期内"}


def extract_json_block(text: str, key: str) -> dict:
    """从大 JSON 文本头部提取某个对象字段（用于 Range 只取首段时的 stats 概览）。"""
    m = re.search(r'"' + re.escape(key) + r'"\s*:\s*\{', text)
    if not m:
        raise SiteUnavailable(f"首段未找到 {key} 字段")
    i = text.index("{", m.start())
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[i:j + 1])
    raise SiteUnavailable(f"{key} 字段在首段内不完整")


# ────────────────────── MOTO ──────────────────────

def _resolve_province(index: dict, prov: str) -> dict:
    for p in index.get("provinces", []):
        if prov in (p["code"], p["name"]) or p["name"].startswith(prov) or p["name"].rstrip("省") == prov:
            return p
    raise SystemExit(f"未识别省份「{prov}」。可选：" + "、".join(p["name"] for p in index.get("provinces", [])))


def moto_routes(province: str, city: str | None = None, rtype: str | None = None,
                **kw) -> dict:
    """返回 {generated, province, total, routes[]}，routes 已按口径分组标注 cs。"""
    idx = _json(SPEC["moto"]["endpoints"]["index"], **kw)
    p = _resolve_province(idx, province)
    data = _json(SPEC["moto"]["home"] + "/map-data/" + p["file"], **kw)
    routes = data.get("routes", [])
    if city:
        routes = [r for r in routes if r.get("city") == city or city in (r.get("city") or "")]
    if rtype:
        routes = [r for r in routes if r.get("t") == rtype]
    out = []
    for r in routes:
        cs = r.get("cs", "")
        out.append({
            "id": r.get("id"), "name": r.get("n"), "type": r.get("t"),
            "km": r.get("d"), "days": r.get("days"), "highlights": r.get("h") or [],
            "city": r.get("city"),
            "waypoints": len(r.get("w") or []),
            "url": SPEC["moto"]["home"] + (r.get("url") or ""),
            "cs": cs, "srcs": r.get("srcs", 0),
            # 口径纪律：computed 是算法生成的跨市聚合，不称实测
            "credibility": {"verified": "人工撰写+地图服务POI核验", "reviewed": "公开资料改写+附来源",
                            "computed": "算法生成·跨市聚合（非实测）"}.get(cs, "未标注"),
        })
    # 实测/复核在前，算法生成垫后
    out.sort(key=lambda x: ({"verified": 0, "reviewed": 1}.get(x["cs"], 2), -(x["km"] or 0)))
    distances = [float(x["km"]) for x in out if isinstance(x.get("km"), (int, float))]
    analysis = {
        "credibility_counts": dict(Counter(x["cs"] or "unknown" for x in out)),
        "type_counts": dict(Counter(x["type"] or "未分类" for x in out)),
        "distance_km_total": round(sum(distances), 1) if distances else 0,
        "distance_km_avg": round(sum(distances) / len(distances), 1) if distances else None,
        "note": "统计仅针对本次筛选结果，不外推为全省/全国结论",
    }
    generated = idx.get("generated")
    return {"source": SPEC["moto"]["home"], "generated": generated,
            "freshness": freshness(generated, SPEC["moto"].get("review_after_days", 180)),
            "province": p["name"], "total": len(out), "analysis": analysis, "routes": out}


# ────────────────────── FUN ──────────────────────

def _stats_result(meta: dict, stats: dict) -> dict:
    generated = meta.get("generated")
    return {"source": SPEC["fun"]["home"], "generated": generated,
            "freshness": freshness(generated, SPEC["fun"].get("review_after_days", 90)),
            "meta": meta, "stats": stats,
            "analysis": {"scope": "全国站内采集样本概览",
                         "note": "仅反映站内样本覆盖，不外推为全国全量POI"}}


def fun_stats(**kw) -> dict:
    """概览：优先 Range 取首段（省 99.9% 流量）；Range 不被接受时回退全量缓存。"""
    url = SPEC["fun"]["endpoints"]["data"]
    try:
        req = urllib.request.Request(url, headers={"Range": "bytes=0-8191",
                                                   "User-Agent": "WorldsTipSkill/site_query"})
        if kw.get("offline") or kw.get("refresh"):
            raise urllib.error.URLError("offline/refresh 走全量")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            if getattr(r, "status", 200) != 206:
                raise urllib.error.URLError("服务端未接受 Range，回退全量缓存")
            head = r.read(8193).decode("utf-8", "ignore")
        stats = extract_json_block(head, "stats")
        meta = extract_json_block(head, "meta")
        return _stats_result(meta, stats)
    except Exception:
        # 全量路径统一走 fetch：写缓存、限响应大小并具备重试/降级，不另开无保护通道。
        d = _json(url, **kw)
        return _stats_result(d.get("meta", {}), d.get("stats", {}))


def fun_city(city: str, **kw) -> dict:
    d = _json(SPEC["fun"]["endpoints"]["data"], **kw)
    cities = d.get("cities", [])
    exact = [c for c in cities if c.get("city") in (city, city + "市")]
    matches = exact or [c for c in cities if c.get("city", "").rstrip("市") == city.rstrip("市")]
    if len(matches) > 1:
        candidates = "、".join(f"{c.get('city')}（{c.get('province', '未知省份')}）" for c in matches[:8])
        raise SystemExit(f"城市名「{city}」有歧义，请先确认候选：{candidates}。不得默认取第一条。")
    if matches:
        c = dict(matches[0])
        c["_meta_generated"] = d.get("meta", {}).get("generated")
        c["_freshness"] = freshness(c.get("updated"), SPEC["fun"].get("review_after_days", 90))
        return c
    raise SystemExit(f"FUN 库未收录城市「{city}」（共 {len(cities)} 城）。"
                     f"未收录 ≠ 该城没有商圈/美食——请降级宿主检索，勿据此断言。")


def fun_section(c: dict, section: str, grade: str | None = None) -> list:
    if section == "districts":
        items = c.get("districts", [])
        if grade:
            items = [x for x in items if x.get("grade") == grade.upper()]
        return sorted(items, key=lambda x: -(x.get("total") or 0))
    if section in ("leisure", "kids"):
        return (c.get(section) or {}).get("list", [])
    return c.get(section, [])


def fun_analysis(c: dict, section: str, items: list) -> dict:
    """只统计已采集字段；评分缺失不补 0，避免把『无评分』误算成低分。"""
    ratings = [float(x["rating"]) for x in items if isinstance(x.get("rating"), (int, float))]
    out = {
        "section_count": len(items),
        "rated_count": len(ratings),
        "unrated_count": len(items) - len(ratings),
        "rating_avg": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "source_credibility": c.get("credibility") or {},
        "note": "均值仅覆盖有评分条目；样本未覆盖不等于该城没有",
    }
    if section == "districts":
        out["grade_counts"] = dict(Counter(x.get("grade") or "未评级" for x in items))
        out["carrier_counts"] = dict(Counter(x.get("carrier") or "未知载体" for x in items))
    return out


def _limit(value: str) -> int:
    n = int(value)
    if not 1 <= n <= 100:
        raise argparse.ArgumentTypeError("--limit 必须在 1-100 之间")
    return n


# ────────────────────── 输出 ──────────────────────

def _src_line(site: str, generated, updated=None) -> str:
    s = f"\n来源: {site} · 数据生成: {generated or '未知'}"
    if updated:
        s += f" · 该城采集: {updated}（评分为地图服务快照，超 90 天须标『待复核』）"
    return s


def main():
    ap = argparse.ArgumentParser(description="WorldsTip 自有站点数据查询（moto/fun），零依赖+缓存+降级")
    ap.add_argument("site", choices=["moto", "fun"])
    ap.add_argument("--province", help="moto：省份名或拼音 code（如 湖南 / hunan）")
    ap.add_argument("--city", help="moto：按所属城市过滤；fun：目标城市（如 岳阳市）")
    ap.add_argument("--type", help="moto：路线类型（攻山压弯/山林湖泊/文化漫游/近郊休闲/长途环线 等）")
    ap.add_argument("--section", default="districts",
                    choices=["districts", "food", "xiaocan", "leisure", "kids", "hotels", "malls", "specialties", "assoc"],
                    help="fun：数据板块，默认 districts（商圈）")
    ap.add_argument("--grade", help="fun：商圈评级过滤 S/A/B/C（仅 section=districts）")
    ap.add_argument("--stats", action="store_true", help="fun：只取全国概览（Range 首段）")
    ap.add_argument("--limit", type=_limit, default=10, help="返回条数 1-100（默认 10）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--refresh", action="store_true", help="强制刷新缓存")
    ap.add_argument("--offline", action="store_true", help="只用本地缓存，无缓存则报不可用")
    ap.add_argument("--cache-dir", default=str(CACHE_DIR))
    args = ap.parse_args()
    kw = dict(cache_dir=Path(args.cache_dir), refresh=args.refresh, offline=args.offline)

    try:
        if args.site == "moto":
            if not args.province:
                ap.error("moto 需要 --province")
            r = moto_routes(args.province, city=args.city, rtype=args.type, **kw)
            if args.json:
                print(json.dumps(r, ensure_ascii=False, indent=1))
                return
            print(f"# 摩托行 · {r['province']}（{r['total']} 条路线，按可信度排序）")
            a = r["analysis"]
            print(f"分析: 口径 {a['credibility_counts']} · 类型 {a['type_counts']} · "
                  f"合计 {a['distance_km_total']}km · 均值 {a['distance_km_avg']}km（仅本次筛选）")
            for x in r["routes"][:args.limit]:
                print(f"\n· {x['name']}｜{x['type']}｜{x['km']}km｜建议 {x['days']} 天｜{x['city']}")
                print(f"  亮点: {' / '.join(x['highlights'])}")
                print(f"  途经点 {x['waypoints']} 个 · 口径[{x['cs']}: {x['credibility']}]"
                      + (f" 来源 {x['srcs']} 条" if x["cs"] == "reviewed" else ""))
                print(f"  详情: {x['url']}")
            computed = sum(1 for x in r["routes"][:args.limit] if x["cs"] == "computed")
            if computed:
                print(f"\n⚠ 其中 {computed} 条为 computed（算法生成·跨市聚合），不称实测、不标已核验。")
            print(_src_line("moto.worldstip.com", r["generated"]) + f" · {r['freshness']['label']}")
        else:
            if args.stats:
                s = fun_stats(**kw)
                print(json.dumps(s, ensure_ascii=False, indent=1) if args.json else
                      f"# FUN 全国概览\n{json.dumps(s['stats'], ensure_ascii=False)}\n"
                      f"数据版本: {s['meta'].get('version')} · 生成: {s['meta'].get('generated')}\n"
                      f"来源: {s['source']} · {s['freshness']['label']} · {s['analysis']['note']}")
                return
            if not args.city:
                ap.error("fun 需要 --city（或 --stats）")
            c = fun_city(args.city, **kw)
            items = fun_section(c, args.section, args.grade)
            analysis = fun_analysis(c, args.section, items)
            if args.json:
                print(json.dumps({"source": SPEC["fun"]["home"], "city": c["city"],
                                  "updated": c.get("updated"), "freshness": c["_freshness"],
                                  "meta_generated": c.get("_meta_generated"),
                                  "section": args.section, "total": len(items),
                                  "analysis": analysis,
                                  "items": items[:args.limit]}, ensure_ascii=False, indent=1))
                return
            print(f"# FUN · {c['city']}（{c.get('province')}）· {args.section}"
                  + (f" · 仅 {args.grade.upper()} 级" if args.grade else "")
                  + f" · 共 {len(items)} 条")
            print(f"全市 POI {c.get('poi_total')} · 商圈 {c.get('district_count')} 处 · 评级 {c.get('grades')}")
            print(f"分析: 有评分 {analysis['rated_count']} · 无评分 {analysis['unrated_count']} · "
                  f"有评分条目均值 {analysis['rating_avg'] or '无'}（不把无评分计为 0）")
            for x in items[:args.limit]:
                if args.section == "districts":
                    print(f"· [{x.get('grade')}] {x.get('name')}｜{x.get('total')}分｜口碑 {x.get('rating')}"
                          f"｜POI {x.get('poi')}｜美食 {x.get('food')} 休闲 {x.get('leisure')}｜{x.get('carrier')}")
                elif args.section == "assoc":
                    print(f"· {x.get('district')} [{x.get('grade')}] 美食 {x.get('count')} 家")
                    for it in (x.get("items") or [])[:5]:
                        print(f"    - {it.get('name')}｜{it.get('rating')}分｜人均¥{it.get('avg')}｜{it.get('addr')}")
                else:
                    print(f"· {x.get('name')}｜{x.get('rating') or '无评分'}分｜人均¥{x.get('avg') or '未知'}"
                          f"｜{x.get('sub') or x.get('type', '')}｜{x.get('addr', '')}")
            print(_src_line("fun.worldstip.com（地图服务/生活服务平台）", c.get("_meta_generated"), c.get("updated"))
                  + f" · {c['_freshness']['label']}")
    except SiteUnavailable as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(EXIT_UNAVAILABLE)


if __name__ == "__main__":
    main()
