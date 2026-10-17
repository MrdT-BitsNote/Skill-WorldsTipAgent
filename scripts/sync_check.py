#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据同步校验：把 live 站点 worldstip.com 的目的地清单与本技能 references/destinations.json
按 slug 联表，自动报出「冲突 / 显示名漂移 / 站点独有 / 技能独有」，防止 muli 类静默错误。

设计纪律（与技能一致）：
- 零第三方依赖，仅用标准库；联网走 urllib，失败自动降级到 --site-file 本地快照。
- 纯比较逻辑 compare() 与 I/O 分离，便于离线回归测试（见 test_sync_check.py）。
- 已知且经人工确认的差异登记进 KNOWN，报为「已知」而非「错误」，不制造噪音。

用法:
  python sync_check.py --live                 # 联网拉取站点清单后比对
  python sync_check.py --site-file snap.html  # 用本地保存的站点 HTML 比对（离线）
  python sync_check.py --live --strict        # 有未登记问题则退出码 1
  python sync_check.py --live --json          # 机器可读输出
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / "references"
DEST = REF / "destinations.json"
SITE_URL = "https://worldstip.com/worldstip-sitemap.html"

# 已人工确认、无需报警的差异（slug -> 原因）
KNOWN = {
    "site_only": {
        "europe": "出境自驾专题页，domestic 目的地表按设计不含出境",
        "georgia": "出境（格鲁吉亚）专题页，domestic 表不含；出境走 visa_rules 等专表",
    },
    "skill_only": {
        "shishou": "石首为湖北短途自驾出发地，无独立 map 页，属正常",
        "mulihong": "安徽木梨硔已入技能库（slug=mulihong）；站点暂用 muli 承载该页，"
                    "尚无独立 mulihong 页，待站方补页后自动消解",
    },
    "divergence": {
        "muli": "站点 /map/muli/ 当前指向安徽木梨硔，技能 muli 为四川木里；"
                "安徽木梨硔已另立 slug=mulihong，站点 slug 归属待站方修正",
    },
}


def parse_site_html(html: str) -> list[dict]:
    """从站点整页 HTML 中抽出内嵌 `const DATA = {...}` 并解析为 [{slug,name}]。"""
    m = re.search(r"const DATA = (\{.*?\});\s*const META", html, re.S)
    if not m:
        m = re.search(r"const DATA = (\{.*?\});", html, re.S)
    if not m:
        raise ValueError("未在站点 HTML 中找到 const DATA 块")
    data = json.loads(m.group(1))
    out = []
    for region, items in data.items():
        for it in items:
            u = it.get("u", "")
            sm = re.search(r"/map/([^/]+)/", u)
            slug = sm.group(1) if sm else ""
            out.append({"slug": slug, "name": (it.get("n") or "").strip(), "region": region})
    return out


def load_skill(path: Path = DEST) -> list[dict]:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return [{"slug": x.get("slug", ""), "name": (x.get("name") or "").strip(),
             "aliases": x.get("aliases") or [], "region": x.get("region", "")}
            for x in d["destinations"]]


def compare(site: list[dict], skill: list[dict], known: dict = KNOWN) -> dict:
    """纯函数：按 slug 联表，返回结构化报告。不触网、不读盘，可单测。"""
    site_by = {s["slug"]: s for s in site if s["slug"]}
    skill_by = {s["slug"]: s for s in skill if s["slug"]}
    ks, kk = set(site_by), set(skill_by)

    collisions, drift, reconciled = [], [], []
    for slug in sorted(ks & kk):
        sn, kn = site_by[slug]["name"], skill_by[slug]["name"]
        if sn == kn:
            continue
        aliases = skill_by[slug].get("aliases") or []
        if sn in aliases:
            reconciled.append({"slug": slug, "site": sn, "skill": kn})
        else:
            item = {"slug": slug, "site": sn, "skill": kn}
            if slug in known.get("divergence", {}):
                item["known"] = known["divergence"][slug]
                collisions.append(item)
            else:
                drift.append(item)

    site_only = [{"slug": s, "name": site_by[s]["name"],
                  **({"known": known["site_only"][s]} if s in known.get("site_only", {}) else {})}
                 for s in sorted(ks - kk)]
    skill_only = [{"slug": s, "name": skill_by[s]["name"],
                   **({"known": known["skill_only"][s]} if s in known.get("skill_only", {}) else {})}
                  for s in sorted(kk - ks)]

    unresolved = ([c for c in collisions if "known" not in c]
                  + drift
                  + [x for x in site_only if "known" not in x]
                  + [x for x in skill_only if "known" not in x])
    return {
        "site_count": len(ks), "skill_count": len(kk),
        "collisions": collisions, "drift": drift, "reconciled": reconciled,
        "site_only": site_only, "skill_only": skill_only,
        "unresolved_count": len(unresolved), "ok": len(unresolved) == 0,
    }


def fetch_site(url: str = SITE_URL, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (sync_check)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _print_report(rep: dict) -> None:
    print(f"站点 {rep['site_count']} 个 slug ｜ 技能 {rep['skill_count']} 个 slug")
    print(f"显示名已由 alias 消解: {len(rep['reconciled'])}")
    if rep["collisions"]:
        print(f"\n[冲突/已知分歧] {len(rep['collisions'])}")
        for c in rep["collisions"]:
            tag = "已知" if "known" in c else "需处理"
            print(f"  ({tag}) {c['slug']}: 站点「{c['site']}」 vs 技能「{c['skill']}」"
                  + (f" — {c['known']}" if "known" in c else ""))
    if rep["drift"]:
        print(f"\n[显示名漂移·未消解] {len(rep['drift'])}")
        for c in rep["drift"]:
            print(f"  {c['slug']}: 站点「{c['site']}」 vs 技能「{c['skill']}」")
    so = [x for x in rep["site_only"] if "known" not in x]
    sko = [x for x in rep["skill_only"] if "known" not in x]
    if so:
        print(f"\n[站点独有·未登记] {len(so)}")
        for x in so:
            print(f"  + {x['slug']} {x['name']}")
    if sko:
        print(f"\n[技能独有·未登记] {len(sko)}")
        for x in sko:
            print(f"  - {x['slug']} {x['name']}")
    print(f"\n结论：未登记问题 {rep['unresolved_count']} 项 → "
          + ("全部干净/已知 ✓" if rep["ok"] else "需处理 ✗"))


def main() -> int:
    ap = argparse.ArgumentParser(description="worldstip.com ↔ destinations.json 数据同步校验")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--live", action="store_true", help="联网拉取站点清单")
    src.add_argument("--site-file", help="用本地保存的站点 HTML 比对（离线）")
    ap.add_argument("--strict", action="store_true", help="有未登记问题则退出码 1")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    a = ap.parse_args()

    try:
        html = fetch_site() if a.live else Path(a.site_file).read_text(encoding="utf-8")
    except Exception as e:
        print(f"获取站点数据失败：{e}", file=sys.stderr)
        return 2
    try:
        site = parse_site_html(html)
        skill = load_skill()
    except Exception as e:
        print(f"解析失败：{e}", file=sys.stderr)
        return 2

    rep = compare(site, skill)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        _print_report(rep)
    if a.strict and not rep["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
