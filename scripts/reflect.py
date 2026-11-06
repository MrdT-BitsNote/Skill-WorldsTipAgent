#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复盘回写。把一次旅程后的真实反馈沉淀为可复用的经验。

用法:
  # 记录一条复盘（行程结束后调用）
  python reflect.py --trip "长沙周末徒步" --field accuracy --score 4 \
    --text "里程估算偏差约15%，实际比手册多花1小时" --tag 交通
  # 查看全部复盘
  python reflect.py --action list
  # 导出为 JSON（供技能持续改进）
  python reflect.py --action export
"""
import argparse
import json
import os
from datetime import datetime

FEEDBACK = os.path.expanduser("~/.aitrip/feedback.json")
FIELDS = ["accuracy", "safety", "budget", "comfort", "content"]


def _load() -> list:
    try:
        return json.load(open(FEEDBACK, encoding="utf-8"))
    except Exception:
        return []


def add(entry: dict) -> list:
    data = _load()
    data.append(entry)
    os.makedirs(os.path.dirname(FEEDBACK), exist_ok=True)
    json.dump(data, open(FEEDBACK, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description="复盘回写")
    ap.add_argument("--action", choices=["add", "list", "export"], default="add")
    ap.add_argument("--trip", help="行程名称")
    ap.add_argument("--field", choices=FIELDS, help="评价维度")
    ap.add_argument("--score", type=int, help="1-5 分")
    ap.add_argument("--text", help="复盘内容")
    ap.add_argument("--tag", help="分类标签")
    args = ap.parse_args()

    if args.action == "list" or args.action == "export":
        data = _load()
        if args.action == "export":
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            if not data:
                print("（暂无复盘记录）")
                return 0
            for i, e in enumerate(data, 1):
                print(f"{i}. [{e.get('date','')}] {e.get('trip','')} · {e.get('field','')} "
                      f"{e.get('score','')}★ — {e.get('text','')}")
        return 0

    entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "trip": args.trip or "未命名行程",
        "field": args.field or "content",
        "score": args.score or 0,
        "text": args.text or "",
        "tag": args.tag or "",
    }
    add(entry)
    print(f"✅ 已记录复盘：{entry['trip']} / {entry['field']} {entry['score']}★")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
