# -*- coding: utf-8 -*-
"""build_moto_traces.py — 把线上摩旅地图库的真实 GPS 轨迹抽稀后写进技能数据层。

为什么需要
----------
技能 moto_routes.json 只有线路的里程/难度/补给等规划层字段，没有几何。
报告里想说清「这条线在地上怎么绕」，靠文字是说不清的。

moto.worldstip.com/map-data/ 有 31 省 1658 条线路的真实 GPS 轨迹（已验证：
太浮山轨迹算得 54.6 km，库标 56 km，误差 2.5%，是真路网轨迹）。
本脚本在**构建期**联网取轨迹、Douglas-Peucker 抽稀、写成 references/moto_traces.json，
运行期技能仍然零联网。

匹配纪律（宁缺勿错）
--------------------
- 必须「核心地名命中」且「里程比在 0.65–1.5 之间」双条件同时成立才算匹配。
- 只接受里程比，不接受纯名字匹配：线上是县市点对点命名，纯名字会把
  「北京妙峰山 160km 往返」错接到「妙峰山—百里山水画廊 243km」。
- 匹配不上的线路不硬凑，写入 coverage.matched 供上层如实披露。

用法（构建期，需联网）：
    python tools/build_moto_traces.py --out references/moto_traces.json
    python tools/build_moto_traces.py --province hunan --out /tmp/t.json   # 单省试跑
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import re
import sys
import urllib.request

BASE = os.environ.get("MOTO_MAP_BASE", "https://moto.worldstip.com/map-data")
UA = "Mozilla/5.0 (compatible; worldstip-travel-planner/1.0)"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _get(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def simplify(pts, eps_km=0.1):
    """Douglas-Peucker 抽稀。eps 为垂距阈值（km），0.1 km 约等于 10 米精度。"""
    if len(pts) < 3:
        return pts
    lat0 = math.radians(sum(p[0] for p in pts) / len(pts))

    def xy(pt):
        return (pt[1] * 111.32 * math.cos(lat0), pt[0] * 110.57)

    P = [xy(p) for p in pts]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        ax, ay = P[i]
        bx, by = P[j]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1e-9
        best, bi = -1.0, -1
        for k in range(i + 1, j):
            px, py = P[k]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / L
            if d > best:
                best, bi = d, k
        if best > eps_km:
            keep[bi] = True
            stack.append((i, bi))
            stack.append((bi, j))
    return [p for p, k in zip(pts, keep) if k]


def tokens(name):
    """线路名 → 核心地名 token 列表（供匹配用）。"""
    s = re.sub(r"[（(].*?[)）]", "", name)
    for junk in ("跑山", "线", "环", "·", "＋"):
        s = s.replace(junk, "")
    s = re.sub(r"^(北京|浙江|广东|湖南|四川|新疆|云南|西藏|青海|甘肃|海南|安徽"
               r"|重庆|广西|湖北|陕西|江西|河南|山东|贵州|辽宁|江苏|河北"
               r"|黑龙江|山西|内蒙古|福建|吉林|宁夏|上海|天津)", "", s)
    return [t for t in re.findall(r"[\u4e00-\u9fa5]{2,5}", s) if len(t) >= 2]


def main(argv=None):
    ap = argparse.ArgumentParser(description="抽取并抽稀线上摩旅轨迹，写入技能数据层")
    ap.add_argument("--out", default=os.path.join(ROOT, "references", "moto_traces.json"))
    ap.add_argument("--routes", default=os.path.join(ROOT, "references", "moto_routes.json"))
    ap.add_argument("--province", default=None, help="只跑指定省的 code，如 hunan")
    ap.add_argument("--eps", type=float, default=0.1, help="抽稀阈值 km，默认 0.1")
    ap.add_argument("--ratio", type=float, nargs=2, default=(0.65, 1.5),
                    help="里程比接受区间，默认 0.65 1.5")
    args = ap.parse_args(argv)

    with open(args.routes, encoding="utf-8") as f:
        data = json.load(f)

    # 1) 取索引，定要下载哪些省
    idx = _get(BASE + "/index.json")
    provs = idx.get("provinces") or []
    need = set()
    for fam in ("near", "long", "loop"):
        for r in data.get(fam, {}).get("routes", []):
            for t in tokens(r.get("name", "")):
                need.add(t)  # 只用于日志，实际全量拉，省得漏
    targets = [p for p in provs if (not args.province or p.get("code") == args.province)]

    online = []
    for p in targets:
        code = p.get("code")
        url = "%s/provinces/%s.json" % (BASE, code)
        try:
            d = _get(url)
        except Exception as e:  # 单省失败不阻断整体
            sys.stderr.write("  跳过 %s：%s\n" % (code, e))
            continue
        n = 0
        for r in d.get("routes", []):
            if not r.get("p"):
                continue
            online.append(dict(prov=code, id=r.get("id"), n=r.get("n"),
                               d=r.get("d"), p=r["p"]))
            n += 1
        sys.stderr.write("  %-12s %4d 条带轨迹\n" % (code, n))

    sys.stderr.write("线上可用轨迹 %d 条\n" % len(online))

    # 2) 匹配技能线路（地名命中 + 里程比双条件）
    lo, hi = args.ratio
    traces, unmatched = {}, []
    for fam in ("near", "long", "loop"):
        for r in data.get(fam, {}).get("routes", []):
            name = r.get("name") or ""
            km = r.get("km")
            if not km:
                unmatched.append({"name": name, "why": "线路库无里程"})
                continue
            tk = tokens(name)
            best = None
            for o in online:
                if not any(t in (o["n"] or "") for t in tk):
                    continue
                if not o.get("d"):
                    continue
                ratio = float(o["d"]) / float(km)
                if not (lo <= ratio <= hi):
                    continue
                score = abs(1.0 - ratio)
                if best is None or score < best[0]:
                    best = (score, o, ratio)
            if best is None:
                unmatched.append({"name": name, "why": "无同名且里程相近的线上轨迹"})
                continue
            o = best[1]
            pts = simplify(o["p"], args.eps)
            traces[name] = {
                "src_id": o["id"], "src_prov": o["prov"], "src_name": o["n"],
                "km_src": o["d"], "km_local": km, "ratio": round(best[2], 3),
                "pts_n": len(pts),
                "pts": [[round(a, 4), round(b, 4)] for a, b in pts],
            }

    total_pts = sum(t["pts_n"] for t in traces.values())
    doc = {
        "_meta": {
            "name": "摩旅线路真实轨迹（抽稀）",
            "why": "给报告提供线路的真实形状；此前只有里程与难度，路线形态靠文字无法表达。",
            "source": "WorldsTip 摩旅地图库 moto.worldstip.com/map-data（站内数据接口）",
            "build": "tools/build_moto_traces.py，Douglas-Peucker eps=%.2f km，坐标保留 4 位小数" % args.eps,
            "match_rule": "核心地名命中 + 里程比 %s~%s，双条件同时成立；只接受里程比，不接受纯名字匹配" % (lo, hi),
            "coord_order": "[lat, lng]",
            "runtime_note": "本文件为构建期产物，运行时零联网读取。",
            "_updated": datetime.date.today().isoformat(),
            "coverage": {
                "total": sum(len(data.get(f, {}).get("routes", [])) for f in ("near", "long", "loop")),
                "matched": len(traces),
                "points": total_pts,
            },
        },
        "traces": traces,
        "unmatched": unmatched,
    }
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(args.out)
    sys.stderr.write("\n匹配 %d/%d，共 %d 点，写入 %s（%d 字节）\n"
                     % (len(traces), doc["_meta"]["coverage"]["total"], total_pts,
                        args.out, size))
    for k in traces:
        t = traces[k]
        sys.stderr.write("  %-26s %s %d点 %.1f→%s km\n"
                         % (k[:24], t["src_id"], t["pts_n"], t["km_src"], t["km_local"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
