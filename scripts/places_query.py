# -*- coding: utf-8 -*-
"""
places_query.py —— 摩旅地点层检索（景点级候选）

设计契约（SKILL.md 硬性纪律）：
  1. 数据不进上下文，只进结果。moto_places.json 原始 1.4MB（约 40 万 token），
     **禁止全文读入**；本脚本按条件过滤后最多回 --limit 条（默认 8），hi 默认截断 120 字。
  2. 默认排除质量问题条目（fl 非空 / st=suspect），需 --include-suspect 显式放行。
     数据质量见 moto_places.json 的 _meta.quality_rule。
  3. 退出码契约（上层据此降级）：
       0 = 有结果
       1 = 已安装但无匹配
       2 = 扩展数据未安装（references/moto_places.json 不存在）→ 上层退回城市级建议并挂灰灯

用法（必须先 cd 到技能根目录，脚本用相对路径取数）：
    python scripts/places_query.py --province 浙江 --type 山 --limit 8 --json
    python scripts/places_query.py --kw 古镇 --limit 5
    python scripts/places_query.py --list-provinces
    python scripts/places_query.py --list-types
    python scripts/places_query.py --admin 湖南 --kw 山 --include-suspect
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_REL = os.path.join("references", "moto_places.json")
DATA = os.path.join(ROOT, DATA_REL)

EXIT_OK = 0
EXIT_NO_MATCH = 1
EXIT_NOT_INSTALLED = 2

HI_TRUNC = 120


def load():
    """返回 (places, meta)。文件不存在返回 (None, None)。"""
    if not os.path.exists(DATA):
        return None, None
    with open(DATA, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("places", []), d.get("_meta", {})


def norm(s):
    return (s or "").strip()


def match(p, province, admin, ptype, kw):
    if province:
        if not p.get("admin", "").startswith(norm(province)):
            return False
    if admin:
        if norm(admin) not in p.get("admin", ""):
            return False
    if ptype:
        if norm(ptype) != p.get("t", ""):
            return False
    if kw:
        k = norm(kw)
        hay = "%s %s %s %s" % (p.get("n", ""), p.get("admin", ""),
                               p.get("hi", ""), p.get("his", ""))
        if k not in hay:
            return False
    return True


def trim(p, full_hi, with_his):
    hi = p.get("hi", "") or ""
    if not full_hi and len(hi) > HI_TRUNC:
        hi = hi[:HI_TRUNC] + "…"
    out = {
        "n": p.get("n"),
        "admin": p.get("admin"),
        "t": p.get("t"),
        "lat": p.get("lat"),
        "lng": p.get("lng"),
        "hi": hi,
        "src": p.get("src"),
    }
    if with_his:
        out["his"] = p.get("his", "")
    if p.get("fl"):
        out["fl"] = p["fl"]
        out["st"] = p.get("st", "suspect")
    return out


def main():
    ap = argparse.ArgumentParser(
        description="摩旅地点层检索（景点级候选）；退出码 0=有结果 1=无匹配 2=扩展数据未安装")
    ap.add_argument("--province", help="省级前缀匹配，如 浙江 / 湖南省 / 内蒙古")
    ap.add_argument("--admin", help="行政区包含匹配，如 湖南 / 张家界")
    ap.add_argument("--type", dest="ptype", help="类型精确匹配，如 山 / 公园 / 古镇 / 寺院")
    ap.add_argument("--kw", help="关键词，匹配名称/行政区/介绍全文")
    ap.add_argument("--limit", type=int, default=8, help="返回条数上限（默认 8）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（默认人类可读）")
    ap.add_argument("--include-suspect", action="store_true",
                    help="包含质量问题条目（默认排除）")
    ap.add_argument("--full-hi", action="store_true", help="不截断 hi（默认截断 120 字）")
    ap.add_argument("--with-his", action="store_true", help="附带 his 历史背景")
    ap.add_argument("--list-provinces", action="store_true", help="列出省份及条目数")
    ap.add_argument("--list-types", action="store_true", help="列出类型及条目数")
    args = ap.parse_args()

    places, meta = load()
    if places is None:
        msg = ("[EXT-MISSING] 扩展数据未安装：%s 不存在。\n"
               "降级：退回 destinations.json 城市级建议，并在输出挂灰灯"
               "「景点级候选需安装扩展数据包 moto-places，当前为城市级建议」。\n"
               "安装：下载 worldstip-travel-planner-ext-motoplaces-*.zip，解压覆盖到技能根目录。"
               % DATA_REL)
        print(msg, file=sys.stderr)
        if args.json:
            print(json.dumps({"error": "ext_not_installed",
                              "missing": DATA_REL,
                              "fallback": "destinations.json.city_level"},
                             ensure_ascii=False))
        sys.exit(EXIT_NOT_INSTALLED)

    if args.list_provinces:
        from collections import Counter
        c = Counter(p["admin"].split("·")[0] for p in places if p.get("admin"))
        if args.json:
            print(json.dumps(dict(c.most_common()), ensure_ascii=False))
        else:
            for k, v in c.most_common():
                print("%-16s %d" % (k, v))
        sys.exit(EXIT_OK)

    if args.list_types:
        from collections import Counter
        c = Counter(p.get("t", "") for p in places)
        if args.json:
            print(json.dumps(dict(c.most_common()), ensure_ascii=False))
        else:
            for k, v in c.most_common():
                print("%-12s %d" % (k, v))
        sys.exit(EXIT_OK)

    if not (args.province or args.admin or args.ptype or args.kw):
        print("[USAGE] 至少提供 --province / --admin / --type / --kw 之一；"
              "或用 --list-provinces / --list-types 查看可选项。", file=sys.stderr)
        sys.exit(EXIT_NO_MATCH)

    res = []
    for p in places:
        if not args.include_suspect and (p.get("fl") or p.get("st") == "suspect"):
            continue
        if match(p, args.province, args.admin, args.ptype, args.kw):
            res.append(p)
        if len(res) >= args.limit:
            break

    if not res:
        print("[NO-MATCH] 无匹配条目。可放宽条件或加 --include-suspect。", file=sys.stderr)
        if args.json:
            print(json.dumps({"results": [], "count": 0}, ensure_ascii=False))
        sys.exit(EXIT_NO_MATCH)

    out = [trim(p, args.full_hi, args.with_his) for p in res]
    if args.json:
        print(json.dumps({"results": out, "count": len(out)}, ensure_ascii=False))
    else:
        for i, x in enumerate(out, 1):
            print("%d. %s（%s · %s）" % (i, x["n"], x["admin"], x["t"]))
            print("   坐标 %s, %s" % (x["lat"], x["lng"]))
            print("   %s" % x["hi"])
            if x.get("fl"):
                print("   [质量问题] %s" % ",".join(x["fl"]))
        print("\n共 %d 条（数据版本 %s）" % (len(out), meta.get("cleaned_at") or meta.get("built_at")))
    sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
