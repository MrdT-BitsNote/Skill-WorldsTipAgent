#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨会话出行偏好档案。

用法:
  # 召回偏好（编排前调用，把结果喂给 build_itinerary）
  python profile.py --action recall
  # 记住一条偏好
  python profile.py --action remember --field pace --value "不喜欢赶场，每天最多3个点"
  # 批量记住（JSON）
  python profile.py --action remember --json '{"diet":"不吃辣","avoid":"人多的网红打卡点"}'
  # 清空
  python profile.py --action reset
"""
import argparse
import json
import os

PROFILE = os.path.expanduser("~/.aitrip/profile.json")
DIMS = ["pace", "schedule", "diet", "stamina", "stay", "avoid"]
DIM_LABEL = {
    "pace": "节奏偏好", "schedule": "作息习惯", "diet": "饮食禁忌",
    "stamina": "体力水平", "stay": "住宿偏好", "avoid": "雷区/避雷",
}


def _load() -> dict:
    try:
        return json.load(open(PROFILE, encoding="utf-8"))
    except Exception:
        return {}


def recall() -> dict:
    return _load()


def remember(field: str, value, data: dict | None = None) -> dict:
    cur = _load()
    if data:
        cur.update(data)
    else:
        if field not in DIMS:
            raise ValueError(f"未知维度 {field}，可选: {', '.join(DIMS)}")
        cur[field] = value
    os.makedirs(os.path.dirname(PROFILE), exist_ok=True)
    json.dump(cur, open(PROFILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return cur


def reset() -> None:
    try:
        os.remove(PROFILE)
    except FileNotFoundError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="跨会话出行偏好档案")
    ap.add_argument("--action", required=True, choices=["recall", "remember", "reset"])
    ap.add_argument("--field", help="维度: " + "/".join(DIMS))
    ap.add_argument("--value", help="偏好内容（文本）")
    ap.add_argument("--json", help="批量 JSON 对象")
    args = ap.parse_args()

    if args.action == "recall":
        data = recall()
        if not data:
            print("（暂无偏好档案，可先用 remember 记录）")
            return 0
        print("📌 出行偏好档案:")
        for k in DIMS:
            if data.get(k):
                print(f"  · {DIM_LABEL.get(k, k)}: {data[k]}")
        return 0
    if args.action == "reset":
        reset()
        print("✅ 偏好档案已清空")
        return 0
    if args.action == "remember":
        if args.json:
            data = json.loads(args.json)
            cur = remember("", "", data)
        elif args.field and args.value:
            cur = remember(args.field, args.value)
        else:
            print("❌ remember 需 --json 或 --field --value")
            return 2
        print("✅ 已记住偏好:")
        for k in DIMS:
            if cur.get(k):
                print(f"  · {DIM_LABEL.get(k, k)}: {cur[k]}")
        return 0
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
