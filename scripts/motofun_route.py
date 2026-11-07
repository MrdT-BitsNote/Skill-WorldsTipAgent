# -*- coding: utf-8 -*-
"""执行入口：把用户原话路由成该跑的动作链 / 该读的文档 / 该加载的数据。

用法：
  python scripts/motofun_route.py "骑太浮山，中午在常德吃点好的" --json
  python scripts/motofun_route.py "岳阳市有什么好吃的" --data-dir fixtures
  python scripts/motofun_route.py "全国美食榜" --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import motofun  # noqa: E402

DOCS = {
    "cascade": ["references/api-spec.md", "references/data-quality.md"],
    "city": ["references/api-spec.md", "references/data-quality.md"],
    "routes": ["references/api-spec.md"],
    "stats": ["references/api-spec.md"],
    "rank": ["references/api-spec.md", "references/data-quality.md"],
}

DATA = {
    "cascade": ["moto_index.json", "moto_{province}.json（按省懒加载）", "fun_data.json"],
    "city": ["fun_data.json"],
    "routes": ["moto_index.json", "moto_{province}.json（按省懒加载）"],
    "stats": ["moto_index.json", "fun_data.json"],
    "rank": ["fun_data.json（food_top / districts_top）"],
}


def main(argv=None) -> int:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(prog="motofun_route.py", description="意图路由入口")
    p.add_argument("text", nargs="?", default="", help="用户原话")
    p.add_argument("--json", action="store_true")
    p.add_argument("--data-dir", help="离线样例数据目录")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--fill", action="store_true", help="从原话抽地名填入动作链（默认关闭）")
    p.add_argument("--refresh", action="store_true", help="跳过本地缓存强制回源")
    args = p.parse_args(argv)

    data_dir = Path(args.data_dir).resolve() if args.data_dir else None
    try:
        r = motofun.cmd_route(args.text, data_dir=data_dir, offline=args.offline,
                              fill=args.fill, refresh=args.refresh)
        intent = r["intent"]
        # cascade 路由时指向 cascade，其余同 intent
        out = {"ok": True, "intent": intent, "commands": r["commands"],
               "docs": DOCS.get(intent, []), "data": DATA.get(intent, []),
               "note": r["note"],
               "discipline": [
                   "餐饮 POI 必须经 is_food() 清洗，禁止直接取 food[0]",
                   "酒店 POI 必须经 is_hotel() 清洗，实测 2.2% 混入餐饮/住宅",
                   "xiaocan 里标『仅登记不推荐』的条目不得作为推荐输出",
                   "长途环线 citySlug=loops 不做单城联动，不得称实测",
                   "城市降级必须显式标注 match_level，歧义先列候选让用户选定",
                   "查不到写未覆盖，绝不编造 POI / 评分 / 地址",
               ]}
        if args.fill:
            out["places"] = r.get("places", [])
        print(json.dumps(out, ensure_ascii=False))
        return motofun.EXIT_OK
    except motofun.DataError as e:
        print(json.dumps({"ok": False, "error": {"code": e.code, "msg": e.msg}},
                         ensure_ascii=False))
        return e.exit_code
    except Exception as e:
        print(json.dumps({"ok": False,
                          "error": {"code": "E_INTERNAL", "msg": f"内部错误：{type(e).__name__}"}},
                         ensure_ascii=False))
        return motofun.EXIT_CORRUPT


if __name__ == "__main__":
    sys.exit(main())
