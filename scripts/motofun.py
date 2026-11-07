# -*- coding: utf-8 -*-
"""WorldsTip 骑游城市通 —— 摩托路线 x 城市生活数据 联动查询引擎。

数据源均为只读静态 JSON（无鉴权、无频控、无跨域限制）：
  A. https://moto.worldstip.com/map-data/index.json
     https://moto.worldstip.com/map-data/provinces/{code}.json
  B. https://fun.worldstip.com/data.json

设计纪律：
  - 纯标准库，零第三方依赖；离线可用（--data-dir 指向夹具目录）
  - 确定性：排序稳定、不写入运行时钟、同输入同输出
  - 不可信输入统一收敛为受控错误码，绝不裸露 traceback
  - 未匹配数据诚实降级，绝不编造
字段口径详见 @references/api-spec.md，降级规则详见 @references/data-quality.md。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---- 常量（不含密钥；数据源为公开只读端点） ----
MOTO_BASE = "https://moto.worldstip.com/map-data"
FUN_URL = "https://fun.worldstip.com/data.json"
DEFAULT_CACHE = Path.home() / ".cache" / "worldstip-moto-fun"
TIMEOUT = 60
MAX_TEXT = 200
CODE_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
NO_RECOMMEND_RE = re.compile(r"仅登记不推荐")

# v0.1.2 全维度数据口径（实测 389 城）：
#   food/xiaocan/malls/specialties/hotels 为 list；
#   leisure/kids 为 {subcats:[...], list:[...]} 的 dict，旧版按 list 判定会谎报 0 条。
POI_DIMS = ("food", "xiaocan", "leisure", "kids", "malls", "specialties", "hotels")
DIM_TYPE_MAIN = {"food": "餐饮服务", "hotels": "住宿服务"}
DIM_LABELS = {
    "food": "美食", "xiaocan": "小吃/苍蝇馆", "leisure": "休闲娱乐",
    "kids": "亲子", "malls": "商场", "specialties": "特产", "hotels": "酒店",
}
MAX_TOP = 20

# 受控错误码：统一走 ErrorCode，禁止裸 traceback
EXIT_OK = 0
EXIT_INPUT = 1        # 参数/输入非法
EXIT_NOT_FOUND = 2    # 查无此项（正常业务结果，非崩溃）
EXIT_UNAVAILABLE = 3  # 网络/缓存/数据不可用
EXIT_CORRUPT = 4      # 数据结构异常


class DataError(Exception):
    def __init__(self, code: str, msg: str, exit_code: int = EXIT_INPUT):
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.exit_code = exit_code


# ---- 数据加载 ----

def _read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise DataError("E_DATA_CORRUPT", f"本地数据不可读或损坏：{path.name}", EXIT_CORRUPT) from e


def _download(url: str, cache_path: Path) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "worldstip-moto-fun/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
        data = json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise DataError("E_NETWORK", f"数据获取失败，请检查网络后重试：{url}", EXIT_UNAVAILABLE) from e
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise DataError("E_DATA_CORRUPT", f"远端数据格式异常：{url}", EXIT_CORRUPT) from e
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写：先写临时文件再替换，失败不留半成品
        tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
        tmp.write_bytes(raw)
        tmp.replace(cache_path)
    except OSError:
        pass  # 缓存写入失败不影响本次查询
    return data


def _load(name: str, url: str, data_dir: Path | None, offline: bool,
          refresh: bool = False) -> dict:
    """data_dir 存在时走纯本地夹具（离线模式）；否则走缓存 + 联网。

    refresh=True 时跳过本地缓存强制回源（离线模式下仍只读缓存，绝不偷偷联网）。
    """
    if data_dir is not None:
        p = data_dir / name
        if not p.is_file():
            raise DataError("E_DATA_UNAVAILABLE",
                            f"离线数据缺失：{name}（目录 {data_dir}）", EXIT_UNAVAILABLE)
        return _read_json(p)
    p = DEFAULT_CACHE / name
    if p.is_file() and not refresh:
        return _read_json(p)
    if offline:
        if p.is_file():
            return _read_json(p)
        raise DataError("E_DATA_UNAVAILABLE",
                        f"离线模式下无缓存：{name}；请先联网运行一次", EXIT_UNAVAILABLE)
    return _download(url, p)


def load_index(data_dir=None, offline=False, refresh=False) -> dict:
    d = _load("moto_index.json", f"{MOTO_BASE}/index.json", data_dir, offline, refresh)
    if not isinstance(d.get("provinces"), list) or not d["provinces"]:
        raise DataError("E_DATA_CORRUPT", "moto 索引结构异常：provinces 缺失", EXIT_CORRUPT)
    return d


def load_province(code: str, data_dir=None, offline=False, refresh=False) -> dict:
    if not isinstance(code, str) or not CODE_RE.match(code):
        raise DataError("E_INPUT", "省份代码非法：仅允许小写字母/数字/连字符，长度 ≤32")
    idx = load_index(data_dir, offline, refresh)
    prov = next((p for p in idx["provinces"] if p.get("code") == code), None)
    if prov is None:
        raise DataError("E_NOT_FOUND",
                        f"省份代码不存在：{code}（索引共 {len(idx['provinces'])} 省）", EXIT_NOT_FOUND)
    d = _load(f"moto_{code}.json", f"{MOTO_BASE}/{prov['file']}", data_dir, offline, refresh)
    if not isinstance(d.get("routes"), list):
        raise DataError("E_DATA_CORRUPT", f"省份数据结构异常：{code}", EXIT_CORRUPT)
    return d


def load_fun(data_dir=None, offline=False, refresh=False) -> dict:
    d = _load("fun_data.json", FUN_URL, data_dir, offline, refresh)
    if not isinstance(d.get("cities"), list) or not isinstance(d.get("stats"), dict):
        raise DataError("E_DATA_CORRUPT", "fun 数据结构异常：cities/stats 缺失", EXIT_CORRUPT)
    return d


# ---- 名称归一化与分级匹配 ----

SUFFIXES = ("自治州", "地区", "盟", "市", "区")
MUNICIPALITIES = ("北京市", "天津市", "上海市", "重庆市")
# 人工确认的县级市 → fun 库中实际存在的上级政区（需在数据更新时复核）
CITY_ALIASES = {
    "敦煌": ("酒泉市", "甘肃省"),
    "靖西": ("百色市", "广西壮族自治区"),
    "都匀": ("黔南布依族苗族自治州", "贵州省"),
    "凯里": ("黔东南苗族侗族自治州", "贵州省"),
}
# 跨省歧义简称（全量扫描 29 个「子串兜底」命中中唯一跨省的一例，2026-11-04 实测）。
# 不带省份信息时不擅自选定，按「先查后问」返回候选；带省份且同省候选存在时正常命中。
AMBIGUOUS_SHORT_NAMES = {
    "海南": ["海南藏族自治州（青海省）", "海南省（省级，无同名单城档案）"],
}


def normalize_city(name: str) -> str:
    """去政区后缀得到基名：常德市 -> 常德；黔东南苗族侗族自治州 -> 黔东南苗族侗族。"""
    if not name:
        return ""
    n = name.strip()
    for suf in SUFFIXES:
        if n.endswith(suf) and len(n) > len(suf) + 1:
            return n[: -len(suf)]
    return n


def _city_index(fun: dict) -> dict:
    return {c.get("city", ""): c for c in fun["cities"] if c.get("city")}


def match_city(name: str, fun: dict, province: str | None = None,
               is_loop: bool = False) -> dict:
    """分级匹配，返回 {city, match_level, note}。全程不编造，失败如实返回 found=False。

    match_level: exact | normalized | alias | municipality | province | none

    is_loop 必须由调用方依据路线的 citySlug == 'loops' 显式传入。
    v0.1.1 修正：旧版用「省份名前缀」猜测环线，会把「重庆 + 重庆市」误判成省级汇总，
    导致明明有「重庆市」档案却谎报无单城档案（真实数据 387 组合实测）。
    """
    if not isinstance(name, str) or not name.strip():
        return {"found": False, "city": name, "match_level": "none",
                "note": "城市名为空"}
    name = name.strip()
    by_name = _city_index(fun)

    # 0. 长途环线：只认调用方传入的权威信号，不靠名字前缀猜
    if is_loop:
        pbase = normalize_city(province or "")[:2]
        prov_row = next((p for p in fun.get("provinces", [])
                         if province and (p.get("province", "") == province
                                          or (pbase and p.get("province", "").startswith(pbase))
                                          or p.get("province", "").startswith(name))), None)
        if prov_row:
            return {"found": True, "city": name, "match_level": "province",
                    "note": "跨市长途环线，挂省级汇总而非单城档案",
                    "province_summary": prov_row}
        return {"found": False, "city": name, "match_level": "none",
                "note": "省级长途环线，fun 库无对应省级汇总"}

    # 1. 精确
    if name in by_name:
        return {"found": True, "city": name, "match_level": "exact", "note": ""}

    base = normalize_city(name)

    # 2. 基名等价匹配：候选城市去政区后缀后的基名必须「完全等于」输入基名。
    # 用等价而非子串，避免「鞍山」被子串误命中「马鞍山市」（真实数据回归发现的缺陷）。
    base_hits = [c for c in by_name if base and normalize_city(c) == base]
    if len(base_hits) > 1:
        return {"found": False, "city": name, "match_level": "none",
                "note": "地名存在歧义，候选：" + "、".join(sorted(base_hits)[:6]) + "；请用户指定"}
    if len(base_hits) == 1:
        return {"found": True, "city": base_hits[0], "match_level": "normalized",
                "note": f"按政区后缀归一化匹配：{name} -> {base_hits[0]}"}

    # 3. 人工确认的县级市别名
    if name in CITY_ALIASES:
        target, prov = CITY_ALIASES[name]
        row = by_name.get(target)
        if row and (not province or row.get("province") == province or prov == province):
            return {"found": True, "city": target, "match_level": "alias",
                    "note": f"县级市无单独档案，降级到上级政区：{name} -> {target}（精度降级）"}
        if row:
            return {"found": True, "city": target, "match_level": "alias",
                    "note": f"县级市降级到 {target}（省份标注为 {row.get('province')}，与路线省份 {province} 不一致，请复核）"}

    # 4. 直辖市区县降级
    if province in MUNICIPALITIES and province in by_name:
        return {"found": True, "city": province, "match_level": "municipality",
                "note": f"区县无单独档案，降级到直辖市：{name} -> {province}（精度降级）"}

    # 5. 宽松子串兜底：自治州简称 -> 全称（真实数据 29 例中 28 例同省正确）。
    #    v0.1.1 加省份硬闸：带省份时只接受同省候选，跨省子串一律不采用，
    #    否则「海南 + 海南省」会静默挂到青海「海南藏族自治州」。
    subs = [c for c in by_name if name in c or (base and base in c)]
    if province:
        same_prov = [c for c in subs if by_name[c].get("province") == province]
        subs = same_prov if same_prov else []
    elif name in AMBIGUOUS_SHORT_NAMES:
        return {"found": False, "city": name, "match_level": "none",
                "note": "地名简称存在歧义，候选：" +
                        "、".join(AMBIGUOUS_SHORT_NAMES[name]) + "；请指定省份或全称"}
    if len(subs) == 1:
        return {"found": True, "city": subs[0], "match_level": "normalized",
                "note": f"唯一子串匹配：{name} -> {subs[0]}"}
    if len(subs) > 1:
        return {"found": False, "city": name, "match_level": "none",
                "note": "地名存在歧义，候选：" + "、".join(sorted(subs)[:6]) + "；请用户指定"}

    return {"found": False, "city": name, "match_level": "none",
            "note": f"fun 库未覆盖此城（共 {len(by_name)} 城档案）；仅返回 moto 路线数据"}


# ---- 维度取值 / 脏数据清洗（v0.1.2） ----

def dim_pois(row: dict, dim: str) -> list:
    """统一取出某维度的 POI 记录，兼容两种真实形态：
      - list：[poi, ...]                       food/xiaocan/malls/specialties/hotels
      - dict：{subcats:[...], list:[poi,...]}  leisure/kids
    旧版只认 list，把 leisure/kids 全库 40601 条谎报为 0。
    """
    v = row.get(dim) if isinstance(row, dict) else None
    if isinstance(v, list):
        raw = v
    elif isinstance(v, dict):
        # subcats 是「分类→数量」统计，不是 POI 记录，混入会虚增计数。
        # 优先取语义明确的 list 键；无该键时遍历其余 list 值但跳过 subcats。
        if isinstance(v.get("list"), list):
            raw = v["list"]
        else:
            raw = []
            for key, vv in v.items():
                if key == "subcats":
                    continue
                if isinstance(vv, list):
                    raw.extend(vv)
    else:
        return []
    return [p for p in raw if isinstance(p, dict)]


def dim_count(row: dict, dim: str) -> int:
    return len(dim_pois(row, dim))


def _main_type(poi: dict) -> str:
    """地图服务多段类型串取首段主类：分号与全角竖线都可能是分隔符。"""
    t = poi.get("type")
    if not isinstance(t, str) or not t.strip():
        return ""
    return t.split(";")[0].split("｜")[0].strip()


def is_food(poi: dict) -> bool:
    """仅保留餐饮主类 POI。实测 fun.food[] 31021 条里混入 777 条非餐饮（2.5%）。
    「住宿服务;.../餐饮服务;...」按首段判为住宿，剔除。"""
    return _main_type(poi) == "餐饮服务"


def is_hotel(poi: dict) -> bool:
    """仅保留住宿主类 POI。实测 hotels[] 12097 条里混入 262 条非住宿（2.2%），
    如「宏豪浦江一号(陆家嘴店)」首段为餐饮服务，旧版会当酒店推荐。"""
    return _main_type(poi) == "住宿服务"


def clean_pois(poi_list, dim: str = "food", top: int = 5) -> list:
    """按维度清洗：类型闸门 → 数据自带『不推荐』标记 → 去重 → 评分降序 → 截断。

    - food 走 is_food；hotels 走 is_hotel；xiaocan/malls/kids/leisure/specialties
      的 type 多为空，不按类型过滤（实测空的占 100% / 100% / 100% / 17.8% / 0%）。
    - xiaocan 的 sub 里有 2090 条「评分…超出苍蝇馆常见区间，仅登记不推荐」，
      数据方明确标注不推荐，直接推给用户会违背口径，一律剔除。
    - 全库实测 431 条同城同维度同名重复（223/389 城），按 (name, addr) 去重。
    """
    if not isinstance(poi_list, list):
        return []
    if not isinstance(top, int) or top < 1:
        top = 5
    main = DIM_TYPE_MAIN.get(dim)
    out, seen = [], set()
    for p in poi_list:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        if main == "餐饮服务" and not is_food(p):
            continue
        if main == "住宿服务" and not is_hotel(p):
            continue
        if dim == "xiaocan" and NO_RECOMMEND_RE.search(str(p.get("sub") or "")):
            continue
        key = (name.strip(), str(p.get("addr") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    def score(p):  # 类型保护：rating 可能是 None / 字符串 / 布尔

        r = p.get("rating")
        if isinstance(r, bool) or not isinstance(r, (int, float)):
            return 0.0
        return -float(r)
    out.sort(key=lambda p: (score(p), str(p.get("name") or "")))
    return [{
        "name": p.get("name"), "rating": p.get("rating"), "avg": p.get("avg"),
        "addr": p.get("addr"), "type": p.get("type"), "sub": p.get("sub"),
    } for p in out[:top]]


def clean_food(food_list, top=5) -> list:
    """兼容入口：行为等价于 clean_pois(..., dim='food')。"""
    return clean_pois(food_list, "food", top)


def city_poi_view(row: dict, dims, top: int = 5) -> dict:
    """按请求的维度组返回清洗后的 TOP POI；未知维度忽略并标注，不报错。"""
    requested = [d for d in (dims or []) if isinstance(d, str) and d.strip()]
    unknown = [d for d in requested if d not in POI_DIMS]
    valid = [d for d in dict.fromkeys(requested) if d in POI_DIMS]
    view = {}
    for dim in valid:
        view[dim] = {"label": DIM_LABELS[dim],
                     "count": dim_count(row, dim),
                     "items": clean_pois(dim_pois(row, dim), dim, top)}
    if unknown:
        view["_unknown_dims"] = sorted(unknown)
    return view


def _text(v, limit=MAX_TEXT):
    """不可信文本：截断 + 校验长度，不执行、不落地为路径。"""
    if v is None:
        return None
    if not isinstance(v, str):
        raise DataError("E_INPUT", "参数必须是字符串")
    if len(v) > limit:
        raise DataError("E_INPUT", f"输入过长（>{limit} 字符），请精简后重试")
    return v.strip()


# ---- 查询动作 ----

def _cache_view() -> list:
    """本地缓存清单（不含 mtime，保证同输入同输出）。"""
    if not DEFAULT_CACHE.is_dir():
        return []
    return [{"file": p.name, "bytes": p.stat().st_size}
            for p in sorted(DEFAULT_CACHE.glob("*.json"))]


def cmd_stats(data_dir=None, offline=False, refresh=False) -> dict:
    idx = load_index(data_dir, offline, refresh)
    fun = load_fun(data_dir, offline, refresh)
    dims = {}
    for dim in POI_DIMS:
        counts = [dim_count(c, dim) for c in fun["cities"]]
        dims[dim] = {"label": DIM_LABELS[dim], "cities_with_data": sum(1 for n in counts if n),
                     "poi_total": sum(counts)}
    return {
        "moto": {"generated": idx.get("generated"), "totalRoutes": idx.get("totalRoutes"),
                 "totalWaypoints": idx.get("totalWaypoints"), "totalCities": idx.get("totalCities"),
                 "provinces": len(idx["provinces"]), "route_fields_unused_by_default": ["p", "w", "c"]},
        "fun": {"version": fun.get("meta", {}).get("version"),
                "generated": fun.get("meta", {}).get("generated"),
                "stats": fun.get("stats"), "dimensions": dims,
                "auxiliary": {"provinces": len(fun.get("provinces", [])),
                              "food_top": len(fun.get("food_top", [])),
                              "districts_top": len(fun.get("districts_top", []))}},
        "cache": {"dir": str(DEFAULT_CACHE), "files": _cache_view(),
                  "note": "缓存命中即返回；线上数据更新后需显式 --refresh 回源"},
    }


def cmd_routes(code, route_type=None, max_n=10, data_dir=None, offline=False,
               refresh=False, with_track=False) -> dict:
    if not isinstance(max_n, int) or max_n < 1 or max_n > 100:
        raise DataError("E_INPUT", "--max 需为 1..100 的整数")
    route_type = _text(route_type)
    d = load_province(code, data_dir, offline, refresh)
    routes = [r for r in d["routes"] if isinstance(r, dict)]
    if route_type:
        routes = [r for r in routes if r.get("t") == route_type]
    page = routes[:max_n]
    out = [{
        "id": r.get("id"), "name": r.get("n"), "type": r.get("t"),
        "km": r.get("d"), "days": r.get("days"), "highlights": r.get("h"),
        "city": r.get("city"), "citySlug": r.get("citySlug"),
        "waypoints": r.get("wn"), "url": r.get("url"),
        "cs": r.get("cs"), "srcs": r.get("srcs", 0),
    } for r in page]
    if with_track:
        # p=抽稀轨迹坐标(GCJ-02)、w=途经点坐标、c=路线配色，实测每条路线 100% 具备
        for o, r in zip(out, page):
            o["color"] = r.get("c")
            o["track_coords"] = r.get("p")
            o["waypoint_coords"] = r.get("w")
    return {"province": d.get("province"), "code": code,
            "total": len(routes), "returned": len(out), "routes": out}


def _parse_dims(raw) -> list:
    """--dims 'malls,leisure' -> ['malls','leisure']；空则返回 []。"""
    if raw is None:
        return []
    s = _text(raw, limit=200)
    return [x.strip() for x in s.split(",") if x.strip()]


def _check_top(top) -> int:
    if not isinstance(top, int) or top < 1 or top > MAX_TOP:
        raise DataError("E_INPUT", f"--top 需为 1..{MAX_TOP} 的整数")
    return top


def cmd_city(name, data_dir=None, offline=False, refresh=False,
             dims=None, top=5, detail=False) -> dict:
    name = _text(name)
    if not name:
        raise DataError("E_INPUT", "城市名不能为空")
    top = _check_top(top)
    fun = load_fun(data_dir, offline, refresh)
    m = match_city(name, fun)
    if not m["found"]:
        return {"found": False, "city": name, "note": m["note"], "match_level": m["match_level"]}
    row = _city_index(fun).get(m["city"])
    if not row:
        return {"found": False, "city": name, "note": "省级汇总，无单城档案",
                "match_level": "province", "province_summary": m.get("province_summary")}
    out = {
        "found": True, "city": row["city"], "province": row.get("province"),
        "adcode": row.get("adcode"), "poi_total": row.get("poi_total"),
        "match_level": m["match_level"], "note": m["note"],
        # v0.1.2：兼容 dict 型维度，补 xiaocan；不再把 leisure/kids 谎报为 0
        "dims": {k: dim_count(row, k) for k in POI_DIMS},
        "grades": row.get("grades"),
        "food": clean_pois(dim_pois(row, "food"), "food", top),
        # v0.1.2：酒店清洗 262 条非住宿 + 去重 + 补齐 rating/avg/addr（对齐输出规范）
        "hotels": clean_pois(dim_pois(row, "hotels"), "hotels", top),
        "page": row.get("page"),
    }
    req = _parse_dims(dims)
    if req:
        out["poi_view"] = city_poi_view(row, req, top)
    if detail:
        ov = row.get("overview") if isinstance(row.get("overview"), dict) else {}
        out["detail"] = {
            "admin": ov.get("admin"),
            "district_poi": (ov.get("district_poi") or [])[:5],
            "credibility": row.get("credibility"),
            "districts": [{"name": d.get("name"), "grade": d.get("grade"),
                           "poi": d.get("poi"), "total": d.get("total")}
                          for d in (row.get("districts") or [])[:5]
                          if isinstance(d, dict)],
        }
    return out


def cmd_cascade(keyword=None, route_id=None, code=None, data_dir=None, offline=False,
                refresh=False, dims=None, top=5, detail=False, with_track=False) -> dict:
    """路线 -> 所属城市 fun 档案 + 途经景点。核心联动动作。"""
    keyword = _text(keyword)
    route_id = _text(route_id)
    if not keyword and not route_id:
        raise DataError("E_INPUT", "需提供 --keyword 或 --route-id")
    top = _check_top(top)
    idx = load_index(data_dir, offline, refresh)
    codes = [code] if code else [p["code"] for p in idx["provinces"]]
    target, prov_code, prov_name = None, None, None
    for c in codes:
        d = load_province(c, data_dir, offline, refresh)
        for r in d["routes"]:
            if not isinstance(r, dict):
                continue
            if route_id and r.get("id") == route_id:
                target, prov_code, prov_name = r, c, d.get("province")
                break
            if keyword and isinstance(r.get("n"), str) and keyword in r["n"]:
                target, prov_code, prov_name = r, c, d.get("province")
                break
        if target:
            break
    if not target:
        raise DataError("E_NOT_FOUND", "未找到匹配路线，请换关键词或用 routes 命令确认",
                        EXIT_NOT_FOUND)

    fun = load_fun(data_dir, offline, refresh)
    is_loop = target.get("citySlug") == "loops"
    route_view = {
        "id": target.get("id"), "name": target.get("n"), "type": target.get("t"),
        "km": target.get("d"), "days": target.get("days"),
        "highlights": target.get("h"), "city": target.get("city"),
        "citySlug": target.get("citySlug"), "url": target.get("url"),
        "cs": target.get("cs"), "srcs": target.get("srcs", 0),
        "quality_note": ("算法生成的跨市长途环线，非实测，引用时须与市区周边短途分开口径"
                         if target.get("cs") == "computed" else ""),
        "province": prov_name, "province_code": prov_code,
    }
    if with_track:
        route_view["color"] = target.get("c")
        route_view["track_coords"] = target.get("p")
        route_view["waypoint_coords"] = target.get("w")

    m = match_city(target.get("city") or "", fun, province=prov_name, is_loop=is_loop)
    if is_loop:
        city_view = {"found": False, "city": target.get("city"),
                     "match_level": "province",
                     "note": f"跨市长途环线（{prov_name or target.get('city')}），不做单城联动；"
                             f"请按 {prov_name or '该省'} 省级汇总查沿途城市",
                     "province_summary": m.get("province_summary")}
    elif m["found"] and m["match_level"] == "province":
        city_view = {"found": False, "city": m["city"], "match_level": "province",
                     "note": m["note"], "province_summary": m.get("province_summary")}
    elif not m["found"]:
        city_view = {"found": False, "city": m["city"],
                     "match_level": m["match_level"], "note": m["note"]}
    else:
        row = _city_index(fun)[m["city"]]
        city_view = {
            "found": True, "city": row["city"], "province": row.get("province"),
            "poi_total": row.get("poi_total"), "match_level": m["match_level"],
            "note": m["note"], "grades": row.get("grades"),
            "dims": {k: dim_count(row, k) for k in POI_DIMS},
            "food": clean_pois(dim_pois(row, "food"), "food", top),
            "hotels": clean_pois(dim_pois(row, "hotels"), "hotels", top),
            "page": row.get("page"),
        }
        req = _parse_dims(dims)
        if req:
            city_view["poi_view"] = city_poi_view(row, req, top)
        if detail:
            city_view["detail"] = {
                "credibility": row.get("credibility"),
                "districts": [{"name": x.get("name"), "grade": x.get("grade"),
                               "poi": x.get("poi"), "total": x.get("total")}
                              for x in (row.get("districts") or [])[:5]
                              if isinstance(x, dict)],
            }

    wps = target.get("wn") if isinstance(target.get("wn"), list) else []
    coords = target.get("w") if isinstance(target.get("w"), list) else []
    # v0.1.2：w 与 wn 一一对应（实测 1713 条路线 100% 具备），补坐标；
    # 旧版给每个途经点重复塞同一份 city_food_hint，改为顶层只给一次。
    waypoints = [{"name": w, "coord": coords[i] if i < len(coords) else None}
                 for i, w in enumerate(wps) if isinstance(w, str)]
    hint = [f["name"] for f in city_view.get("food", [])[:2]] if city_view.get("found") else []
    return {"found": True, "route": route_view, "city_fun": city_view,
            "waypoints": waypoints, "food_hint": hint}


def cmd_top_cities(n=15, data_dir=None, offline=False, refresh=False) -> list:
    if not isinstance(n, int) or n < 1 or n > 100:
        raise DataError("E_INPUT", "--n 需为 1..100 的整数")
    fun = load_fun(data_dir, offline, refresh)
    ranked = sorted(fun["cities"],
                    key=lambda c: (-(c.get("district_count") or 0), str(c.get("city") or "")))
    return [{"city": c.get("city"), "province": c.get("province"),
             "districts": c.get("district_count"), "poi": c.get("poi_total"),
             "grades": c.get("grades")} for c in ranked[:n]]


def cmd_rank(kind="food", n=10, city=None, prov=None,
             data_dir=None, offline=False, refresh=False) -> dict:
    """全国榜查询：food_top（800 条）/ districts_top（703 条 S/A 商圈）。

    实测 food_top 里有 15 条首段非餐饮，按与 food[] 相同的口径清洗，不照单全收。
    """
    if kind not in ("food", "districts"):
        raise DataError("E_INPUT", "--kind 仅支持 food | districts")
    if not isinstance(n, int) or n < 1 or n > 100:
        raise DataError("E_INPUT", "--n 需为 1..100 的整数")
    city = _text(city)
    prov = _text(prov)
    fun = load_fun(data_dir, offline, refresh)
    if kind == "food":
        raw = fun.get("food_top") or []
        rows = [p for p in raw if isinstance(p, dict) and is_food(p)]
        if city:
            rows = [p for p in rows if p.get("city") == city]
        if prov:
            rows = [p for p in rows if p.get("province") == prov]
        rows.sort(key=lambda p: (-(p.get("rating") or 0) if isinstance(p.get("rating"), (int, float))
                                 and not isinstance(p.get("rating"), bool) else 0,
                                 str(p.get("name") or "")))
        items = [{"name": p.get("name"), "city": p.get("city"),
                  "province": p.get("province"), "rating": p.get("rating"),
                  "avg": p.get("avg"), "addr": p.get("address"),
                  "type": p.get("type"), "mark": p.get("mark"),
                  "page": p.get("city_page")} for p in rows[:n]]
        return {"kind": kind, "raw_total": len(raw), "cleaned_total": len(rows),
                "returned": len(items), "items": items,
                "note": "已按 type 首段=餐饮服务清洗；评分为采集时快照"}
    raw = fun.get("districts_top") or []
    rows = [p for p in raw if isinstance(p, dict)]
    if city:
        rows = [p for p in rows if p.get("city") == city]
    if prov:
        rows = [p for p in rows if p.get("province") == prov]
    rows.sort(key=lambda p: (-(p.get("total") or 0) if isinstance(p.get("total"), (int, float))
                             and not isinstance(p.get("total"), bool) else 0,
                             str(p.get("name") or "")))
    items = [{"name": p.get("name"), "grade": p.get("grade"), "city": p.get("city"),
              "province": p.get("province"), "total": p.get("total"),
              "poi": p.get("poi"), "rating": p.get("rating"),
              "food": p.get("food"), "leisure": p.get("leisure"),
              "kids": p.get("kids"), "hotel": p.get("hotel"),
              "page": p.get("city_page")} for p in rows[:n]]
    return {"kind": kind, "raw_total": len(raw), "cleaned_total": len(rows),
            "returned": len(items), "items": items,
            "note": "全国 S/A 商圈榜，按四维总分降序；total 为数据方评分"}


ROUTE_MOTO = ("骑", "骑行", "骑车", "跑山", "压弯", "摩旅", "摩友", "路线", "线路",
              "这条线", "环线", "轨迹", "赛道", "跑一趟")
ROUTE_FUN = ("吃", "美食", "住", "住宿", "酒店", "逛", "商圈", "玩", "夜生活", "亲子", "特产")
ROUTE_STATS = ("数据规模", "有哪些数据", "多少条", "覆盖多少", "多少城", "多少路线",
               "数据源", "数据日期")
ROUTE_CITY_ONLY = ("城市档案", "fun 城市", "fun城市", "城市生活数据")
ROUTE_RANK = ("全国美食榜", "美食榜", "美食排行", "商圈榜", "商圈排行",
              "商圈排名", "全国榜", "排行榜", "S级商圈", "S/A商圈")

# v0.2.1：自行车词 vs 摩托强词，用于排除「骑自行车」被误判成摩旅
BIKE_ONLY = ("自行车", "单车", "公路车", "山地车", "骑行", "骑车")
MOTO_STRONG = ("摩托", "机车", "摩旅", "摩友", "压弯", "禁摩", "限摩",
               "踏板", "挡车", "上高速", "adv")
# 「环 X 湖/线/山/岛/江/河/城」是环线口语说法；不写裸「环」以免「环境不错」误命中
LOOP_RE = re.compile(r"环[\u4e00-\u9fa5]{2,6}(?:湖|线|山|岛|江|河|城)")


def _extract_places(text: str, data_dir, offline, refresh=False) -> list:
    """--fill 专用：从 fun 城市档案抽原话中出现的地名（含去后缀基名），最长优先。

    数据不可用时返回空列表并降级为占位符，不报错、不编造地名。
    """
    try:
        fun = load_fun(data_dir, offline, refresh)
    except DataError:
        return []
    vocab = set()
    for c in fun.get("cities", []):
        n = c.get("city")
        if not isinstance(n, str) or not n:
            continue
        vocab.add(n)
        base = normalize_city(n)
        if len(base) >= 2:
            vocab.add(base)
    hits = [n for n in vocab if len(n) >= 2 and n in text]
    return sorted(hits, key=lambda s: (-len(s), s))[:5]


def cmd_route(text, data_dir=None, offline=False, fill=False, refresh=False) -> dict:
    """意图路由：把用户原话映射为应执行的动作链（确定性规则，不调模型）。

    v0.1.1：补齐 stats / 城市档案意图，环线口语识别，以及可选 --fill 地名填充。
    fill=False（默认）时输出与 v0.1.0 逐字段一致，保证零回归。
    """
    t = _text(text or "")
    if not t:
        raise DataError("E_INPUT", "用户原话不能为空")
    has_moto = any(k in t for k in ROUTE_MOTO) or bool(LOOP_RE.search(t))
    # v0.2.1 修：ROUTE_MOTO 含裸「骑」，会把「我骑自行车去重庆」也认成摩旅。
    # 出现自行车词且没有任何摩托强词时，不算摩旅诉求。
    if has_moto and any(k in t for k in BIKE_ONLY) \
            and not any(k in t for k in MOTO_STRONG):
        has_moto = False
    has_fun = any(k in t for k in ROUTE_FUN)
    has_stats = any(k in t for k in ROUTE_STATS)
    has_city_only = any(k in t for k in ROUTE_CITY_ONLY)
    has_rank = any(k in t for k in ROUTE_RANK)
    # 「全国美食榜」「商圈排行」同时含 fun 关键词，故 rank 优先于 has_fun 判定
    if has_rank and not has_moto:
        intent, cmds = "rank", ["rank --kind <food|districts> --n 10", "city --name <城市>"]
    elif has_stats and not (has_moto or has_fun):
        intent, cmds = "stats", ["stats"]
    elif has_city_only and not has_moto:
        intent, cmds = "city", ["city --name <城市>"]
    elif has_moto and has_fun:
        intent, cmds = "cascade", ["cascade --keyword <关键词>", "city --name <城市>"]
    elif has_fun:
        intent, cmds = "city", ["city --name <城市>", "top-cities"]
    elif has_moto:
        intent, cmds = "routes", ["routes --province <省拼音> --type <类型> --max 10",
                                  "cascade --keyword <关键词>"]
    else:
        # v0.2.1 修：旧实现这里直接兜底成 routes，导致「你好」「帮我写一份周报」
        # 「明天股票会涨吗」全部返回摩旅路线命令——假阳性比漏判更危险，
        # 会把完全无关的诉求拖进摩旅数据链。未命中一律 none，交回总路由判定。
        intent, cmds = "none", []
    out = {"intent": intent, "commands": list(cmds),
           "note": "请从原话中抽取地名填入 <...> 占位符；地名有歧义时先列候选让用户选定"}
    if intent == "none":
        out["note"] = ("未识别到摩旅/城市生活诉求，本模块不适用；"
                       "请交回 scripts/route.py 做总路由判定，不要强行套用摩旅数据。")
    if fill:
        places = _extract_places(t, data_dir, offline, refresh)
        out["places"] = places
        if places:
            out["commands"] = [c.replace("<城市>", places[0]) for c in cmds]
        out["note"] += ("；--fill 已从原话识别地名 " + "、".join(places)
                        if places else "；--fill 未识别到地名（数据不可用或原话无城市名），保留占位符")
    return out


CMDS = {"stats": cmd_stats, "routes": cmd_routes, "city": cmd_city,
        "cascade": cmd_cascade, "top-cities": cmd_top_cities,
        "rank": cmd_rank, "route": cmd_route}


def build_parser():
    p = argparse.ArgumentParser(prog="motofun.py", description="摩托路线 x 城市生活数据联动查询")
    p.add_argument("cmd", choices=sorted(CMDS), help="动作")
    p.add_argument("--province", "--code", dest="code", help="省份拼音代码，如 hunan")
    p.add_argument("--type", dest="route_type", help="路线类型，如 攻山压弯")
    p.add_argument("--max", dest="max_n", type=int, default=10)
    p.add_argument("--n", dest="n", type=int, default=15)
    p.add_argument("--name", "--city", dest="name", help="城市名")
    p.add_argument("--keyword", help="路线名称关键词")
    p.add_argument("--route-id", help="路线 ID")
    p.add_argument("--text", dest="text", help="route 命令的用户原话")
    p.add_argument("--data-dir", help="离线夹具目录（含 moto_index.json / moto_*.json / fun_data.json）")
    p.add_argument("--offline", action="store_true", help="禁止联网，仅用缓存")
    p.add_argument("--fill", action="store_true", help="route 命令：从原话抽地名填入动作链（默认关闭）")
    p.add_argument("--kind", choices=("food", "districts"), default="food",
                   help="rank 命令：全国美食榜 / S-A 商圈榜")
    p.add_argument("--rank-province", help="rank 命令：按省份中文名过滤，如 湖南省")
    p.add_argument("--dims", help="city/cascade：逗号分隔的额外维度，如 malls,leisure,xiaocan")
    p.add_argument("--top", dest="top", type=int, default=5,
                   help=f"city/cascade：每维度返回条数 1..{MAX_TOP}（默认 5）")
    p.add_argument("--detail", action="store_true", help="city/cascade：附行政区、商圈与可信度摘要")
    p.add_argument("--with-track", action="store_true",
                   help="routes/cascade：附 GCJ-02 轨迹坐标与途经点坐标（输出较大，默认关闭）")
    p.add_argument("--refresh", action="store_true",
                   help="跳过本地缓存强制回源；离线模式下仍只读缓存")
    p.add_argument("--json", action="store_true", help="输出 JSON（默认即为 JSON）")
    return p


def dispatch(cmd: str, args, data_dir, offline) -> dict:
    kw = {"data_dir": data_dir, "offline": offline,
          "refresh": getattr(args, "refresh", False)}
    if cmd == "stats":
        return {"cmd": cmd, "ok": True, "data": cmd_stats(**kw)}
    if cmd == "routes":
        if not args.code:
            raise DataError("E_INPUT", "routes 命令需要 --province")
        return {"cmd": cmd, "ok": True,
                "data": cmd_routes(args.code, args.route_type, args.max_n,
                                   with_track=getattr(args, "with_track", False), **kw)}
    if cmd == "city":
        if not args.name:
            raise DataError("E_INPUT", "city 命令需要 --name")
        return {"cmd": cmd, "ok": True,
                "data": cmd_city(args.name, dims=getattr(args, "dims", None),
                                 top=getattr(args, "top", 5),
                                 detail=getattr(args, "detail", False), **kw)}
    if cmd == "cascade":
        return {"cmd": cmd, "ok": True,
                "data": cmd_cascade(args.keyword, args.route_id, args.code,
                                    dims=getattr(args, "dims", None),
                                    top=getattr(args, "top", 5),
                                    detail=getattr(args, "detail", False),
                                    with_track=getattr(args, "with_track", False), **kw)}
    if cmd == "top-cities":
        return {"cmd": cmd, "ok": True, "data": cmd_top_cities(args.n, **kw)}
    if cmd == "rank":
        return {"cmd": cmd, "ok": True,
                "data": cmd_rank(getattr(args, "kind", "food"), args.n,
                                 getattr(args, "name", None),
                                 getattr(args, "rank_province", None), **kw)}
    if cmd == "route":
        if args.text is None:
            raise DataError("E_INPUT", "route 命令需要 --text")
        return {"cmd": cmd, "ok": True,
                "data": cmd_route(args.text, fill=getattr(args, "fill", False), **kw)}
    raise DataError("E_INPUT", f"未知命令：{cmd}")


def main(argv=None) -> int:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir).resolve() if args.data_dir else None
    if data_dir is not None and not data_dir.is_dir():
        print(json.dumps({"ok": False, "cmd": args.cmd,
                          "error": {"code": "E_INPUT", "msg": f"夹具目录不存在：{data_dir}"}},
                         ensure_ascii=False), file=sys.stdout)
        return EXIT_INPUT
    try:
        result = dispatch(args.cmd, args, data_dir, args.offline)
        print(json.dumps(result, ensure_ascii=False, sort_keys=False))
        return EXIT_OK
    except DataError as e:
        print(json.dumps({"ok": False, "cmd": args.cmd,
                          "error": {"code": e.code, "msg": e.msg}}, ensure_ascii=False))
        return e.exit_code
    except Exception as e:  # 兜底：绝不裸露 traceback
        print(json.dumps({"ok": False, "cmd": args.cmd,
                          "error": {"code": "E_INTERNAL", "msg": f"内部错误：{type(e).__name__}"}},
                         ensure_ascii=False))
        return EXIT_CORRUPT


if __name__ == "__main__":
    sys.exit(main())
