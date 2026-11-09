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
import sys
from datetime import datetime

FIELDS = ["accuracy", "safety", "budget", "comfort", "content"]
_WRITE_FAIL = ("❌ 复盘写入失败（%s）\n"
               "   目标路径: %s\n"
               "   本次复盘**没有保存**，不要向用户声称已记录。\n"
               "   处置：把 AITRIP_HOME 指向可写目录后重试，例如 "
               "`AITRIP_HOME=/tmp/aitrip python reflect.py --trip ...`\n")


def feedback_path() -> str:
    """复盘路径：AITRIP_HOME 优先，否则 ~/.aitrip。

    v0.2.274：托管沙箱里 $HOME 可能不可写，原先直接 open(...,"w") 抛原始
    PermissionError traceback。改为原子写 + 明确诊断（同 profile.py）。
    """
    base = os.environ.get("AITRIP_HOME") or os.path.join(os.path.expanduser("~"), ".aitrip")
    return os.path.join(base, "feedback.json")


def _save(data: list) -> tuple[bool, str]:
    path = feedback_path()
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True, path
    except OSError as e:
        return False, "%s: %s" % (type(e).__name__, e)


def _load() -> list:
    try:
        with open(feedback_path(), encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, list) else []
    except Exception:
        return []


def add(entry: dict) -> list:
    data = _load()
    data.append(entry)
    ok, info = _save(data)
    if not ok:
        raise OSError(info)
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
    try:
        add(entry)
    except OSError as e:
        sys.stderr.write(_WRITE_FAIL % (e, feedback_path()))
        return 2
    print(f"✅ 已记录复盘：{entry['trip']} / {entry['field']} {entry['score']}★")
    return 0


if __name__ == "__main__":
    sys.exit(main())
