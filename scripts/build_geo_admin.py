#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
geo_admin.json 构建器 —— worldstip-travel-planner

解决什么问题
------------
v0.2.0 的国内/出境判定靠 scripts/outbound_constraints.py 里手写的
_CN_PROVINCES / _CN_CITIES 短名单（不到200 项）。但中国有 34 个省级、
342 个地级、2978 个县级行政区。名单外的真实地名（如"芒市""霍尔果斯"
"阿尔山""婺源"）一律判成出境 → 国内用户凭空看到签证门禁卡。
这是【名单不全】型缺陷，不是【逻辑错误】，所以只能靠补全数据解决。

数据来源（权威、可溯源）
------------------------
民政部《中华人民共和国县以上行政区划代码》公开整理版：
  modood/Administrative-divisions-of-China（GitHub，多镜像）
  - provinces.json  31 条  省级
  - cities.json     342 条 地级
  - areas.json      2978 条 县级
香港/澳门/台湾属中国境内，官方源不含港澳台县级，单独并入。

为什么不做"排除法"（不在出境名单里就算国内）
-------------------------------------------
排除法会把任何拼错/生僻的境外地名判成国内 → 出境用户漏掉签证与保险门禁，
这是硬安全风险，比多弹一个待查灯严重得多。保持白名单 + 保守取向。

用法
----
  python build_geo_admin.py --src <下载目录> --dest ../references/geo_admin.json
  python build_geo_admin.py --dest ../references/geo_admin.json --fetch   # 直接下载
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(os.path.dirname(HERE), "references")

SOURCE_URLS = [
    "https://cdn.jsdelivr.net/gh/modood/Administrative-divisions-of-China@master/dist/{f}.json",
    "https://fastly.jsdelivr.net/gh/modood/Administrative-divisions-of-China@master/dist/{f}.json",
    "https://raw.githubusercontent.com/modood/Administrative-divisions-of-China/master/dist/{f}.json",
]
SOURCE_NAME = "民政部《中华人民共和国县以上行政区划代码》公开整理版 modood/Administrative-divisions-of-China"

# 港澳台属中国境内；官方大陆源不含，单独并入（一律用「中国××」规范表述）
HK_MO_TW_PROVINCES = [
    {"code": "810000", "name": "中国香港", "abbr": "香港"},
    {"code": "820000", "name": "中国澳门", "abbr": "澳门"},
    {"code": "710000", "name": "中国台湾", "abbr": "台湾"},
]
HK_MO_TW_AREAS = {
    # ⚠️ 每条清单必须只含【本地区自己的】下辖名。
    # 曾经把"中国澳门""中国台湾""澳门半岛"误放进 810000（香港）的清单，
    # 导致生成出 {"name":"中国台湾","province":"中国香港"} 这种记录——
    # 台湾被归到香港名下，是必须修掉的表述错误，不是数据瑕疵。
    # 教训：跨区域的下辖名要按归属分区写，不能图省事堆在一起。
    "810000": ["中国香港", "香港岛", "九龙", "新界"],
    "820000": ["中国澳门", "澳门半岛", "氹仔", "路环", "路氹城"],
    "710000": ["中国台湾", "台北", "高雄", "台中", "台南", "新北", "桃园",
               "花莲", "台东", "宜兰", "嘉义", "彰化", "南投", "屏东"],
}

# ── 名称归一：把「行政区全称」压成「用户实际会输入的短名」 ────────────────
# 剥离后缀时要留 2 字以上，否则「黄山」被砍成「黄」会造成跨省误判。
ADMIN_SUFFIXES = [
    "维吾尔自治区", "特别行政区", "壮族自治区", "回族自治区", "自治区",
    "土家族苗族自治州", "藏族自治州", "蒙古族藏族自治州", "苗族侗族自治州",
    "自治州", "自治县", "联合旗", "自治旗", "地区", "盟", "旗",
    "林区", "矿区", "市辖区",
    "新区", "省", "市", "县", "区",
]
# 剥完这些之后还要再剥的通名（"XX县XX镇" → "XX县"），避免过度剥离
TRAILING_NOISE = ["风景区", "景区", "旅游区", "保护区", "风景名胜区", "古城", "老街", "古镇", "公园", "景区"]


def strip_admin_suffix(name: str) -> list[str]:
    """返回该行政区名在匹配时的候选键，长名在前、短名在后。

    "湘西土家族苗族自治州" → ["湘西土家族苗族自治州", "湘西"]
    "大理白族自治州"      → ["大理白族自治州", "大理"]
    "岳阳市"             → ["岳阳市", "岳阳"]
    """
    cands = [name]
    cur = name
    # 反复剥后缀，每次剥完都记录一个候选（自治州这类长后缀要先剥）
    for _ in range(3):
        changed = False
        for suf in ADMIN_SUFFIXES:
            if cur.endswith(suf) and len(cur) - len(suf) >= 2:
                cur = cur[: -len(suf)]
                cands.append(cur)
                changed = True
                break
        if not changed:
            break
    # 顺序保证长的在前（长名先匹配，避免"南岳"抢占"南岳衡山"这类歧义）
    out, seen = [], set()
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def fetch_json(fname: str, src_dir: str | None) -> list[dict]:
    """优先用本地已下载文件，其次从镜像依次下载。"""
    if src_dir:
        p = os.path.join(src_dir, fname)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    last = None
    for tpl in SOURCE_URLS:
        url = tpl.format(f=fname.replace(".json", ""))
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=40) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list) and data:
                    return data
            except Exception as e:  # 限流/重置/404 一律换源
                last = e
                time.sleep(1.5)
    raise SystemExit(f"❌ 无法获取 {fname}：{last}\n   请手动下载 provinces/cities/areas.json 后用 --src 指定目录。")


def build(src_dir: str | None, dest: str) -> dict:
    prov_raw = fetch_json("provinces.json", src_dir)
    city_raw = fetch_json("cities.json", src_dir)
    area_raw = fetch_json("areas.json", src_dir)

    prov_by_code = {p["code"]: p["name"] for p in prov_raw}
    city_by_code = {c["code"]: c for c in city_raw}

    provinces = []
    for p in prov_raw:
        name = p["name"]
        provinces.append({
            "code": p["code"],
            "name": name,
            "keys": strip_admin_suffix(name),
        })
    for extra in HK_MO_TW_PROVINCES:
        provinces.append({"code": extra["code"], "name": extra["name"], "keys": [extra["name"], extra["abbr"]]})

    cities = []
    for c in city_raw:
        name = c["name"]
        # 「市辖区」是占位名（北京/天津/上海/重庆 下的），无地理意义，剔除
        if name == "市辖区":
            continue
        cities.append({
            "code": c["code"],
            "name": name,
            "province": prov_by_code.get(c["provinceCode"], ""),
            "keys": strip_admin_suffix(name),
        })
    for pc, names in HK_MO_TW_AREAS.items():
        pname = next(x["name"] for x in provinces if x["code"] == pc)
        for i, nm in enumerate(names):
            cities.append({"code": f"{pc[:2]}9{i:02d}", "name": nm, "province": pname, "keys": [nm]})

    counties = []
    for a in area_raw:
        name = a["name"]
        rec = {
            "code": a["code"],
            "name": name,
            "city": city_by_code.get(a["cityCode"], {}).get("name", ""),
            "province": prov_by_code.get(a["provinceCode"], ""),
            "keys": strip_admin_suffix(name),
        }
        # 自治州/盟下辖的县级若同名，也要能被短名命中
        counties.append(rec)
    for pc, names in HK_MO_TW_AREAS.items():
        pname = next(x["name"] for x in provinces if x["code"] == pc)
        for i, nm in enumerate(names):
            counties.append({"code": f"{pc[:2]}8{i:02d}", "name": nm, "city": nm, "province": pname, "keys": [nm]})

    # ── 自检：跨区域归属污染 ───────────────────────────────────
    # 港澳台必须各自归属自身，不能互串。这一条是【表述正确性】底线，
    # 不是风格问题——把中国台湾归到中国香港名下是错误的。
    _bad = []
    # 规则：用【名字 → 允许归属地区】的权威映射判断，不做字符串包含判断。
    # 「台北」的 province 写「中国台湾」是正确的，它当然不含「中国台湾」四字，
    # 所以 startswith 型判断必然把正确记录全判成异常。
    # 正确做法：先算出每个名字合法属于哪个地区，再核对生成结果是否越界。
    _owner: dict[str, str] = {}
    for _pc, _names in HK_MO_TW_AREAS.items():
        _own = next(x["name"] for x in provinces if x["code"] == _pc)
        for _nm in _names:
            _owner.setdefault(_nm, _own)
    # 源头检查：某个名字若被两个地区同时声明，说明清单本身已污染
    _dup = sorted({n for n, _o in _owner.items()
                   for _p, _ns in HK_MO_TW_AREAS.items() if n in _ns
                   and _o != next(x["name"] for x in provinces if x["code"] == _p)})
    if _dup:
        raise SystemExit(
            "[geo_admin] 港澳台区域清单互相污染，以下名字被多个地区同时声明：\n  "
            + "\n  ".join(_dup))

    for _lvl, _rows in (("city", cities), ("county", counties)):
        for _r in _rows:
            _nm = _r.get("name", "")
            if _nm not in _owner:
                continue  # 非港澳台条目，走省级正常逻辑
            _prov = _r.get("province", "")
            if _prov and _prov != _owner[_nm]:
                _bad.append(f"{_lvl}: {_nm} 的 province 为 {_prov}，"
                            f"但它属于 {_owner[_nm]}")
    if _bad:
        raise SystemExit("[geo_admin] 归属污染自检失败，拒绝写出：\n  " + "\n  ".join(sorted(set(_bad))))

    data = {
        "_meta": {
            "name": "中国境内行政区划地名索引（省/市/县三级）",
            "purpose": "供 is_domestic() 判定国内外，防止国内真实地名被误判为出境而误弹签证门禁卡。",
            "source": SOURCE_NAME,
            "source_note": "香港/澳门/台湾属中国境内，官方大陆行政区划源不含港澳台县级，已单独并入并使用「中国××」规范表述。",
            "built_at": time.strftime("%Y-%m-%d"),
            "counts": {"province": len(provinces), "city": len(cities), "county": len(counties)},
            "match_rules": [
                "三级键名匹配：先全称（岳阳市）后短名（岳阳）。",
                "额外剥离通名后缀：黄山风景区→黄山、西湖景区→西湖。",
                "仍不中→ 判为非境内，走 unknown 灰灯，不编造国别。",
            ],
        },
        "province": provinces,
        "city": cities,
        "county": counties,
    }
    # ── 短名歧义检测 ────────────────────────────────────────────────
    # 例："中山"同时是中山区(大连) 与 中山市(广东)；"朝阳"同时是朝阳区(北京) 与 朝阳县(辽宁)。
    # 对 is_domestic() 无影响（撞车项同属中国境内，判定结果一致），
    # 但景点归属到省市时会产生歧义，必须显式记录而不是静默取第一个。
    amb: dict[str, list[str]] = {}
    for level in ("province", "city", "county"):
        seen: dict[str, list[str]] = {}
        for r in data[level]:
            for k in r["keys"][1:]:
                seen.setdefault(k, [])
                if r["name"] not in seen[k]:
                    seen[k].append(r["name"])
        for k, v in seen.items():
            if len(v) > 1:
                amb[k] = sorted(v)

    data["_meta"]["ambiguous_short_names"] = {
        "count": len(amb),
        "note": "同一短名对应多个同级行政区（如 中山 → 中山市/中山区）。"
                "不影响境内判定；景点归属到省市时须按省份或全称消歧，不得静默取首个。",
        "map": dict(sorted(amb.items())),
    }

    data["_meta"]["counts"]["ambiguous_keys"] = len(amb)

    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="构建国内行政区划地名索引")
    ap.add_argument("--src", default=None, help="已下载的 provinces/cities/areas.json 所在目录")
    ap.add_argument("--dest", default=os.path.join(REF_DIR, "geo_admin.json"))
    ap.add_argument("--fetch", action="store_true", help="允许联网下载缺失文件")
    args = ap.parse_args()
    if not args.src and not args.fetch:
        print("需要 --src <目录> 或 --fetch")
        sys.exit(1)
    data = build(args.src, args.dest)
    c = data["_meta"]["counts"]
    size = os.path.getsize(args.dest) / 1024
    print(f"✅ 已生成 {args.dest}")
    print(f"   省 {c['province']} · 市 {c['city']} · 县 {c['county']} · {size:.0f} KB")
    print(f"   数据源：{SOURCE_NAME}")


if __name__ == "__main__":
    main()