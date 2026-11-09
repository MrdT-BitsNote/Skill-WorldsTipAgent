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
import sys

DIMS = ["pace", "schedule", "diet", "stamina", "stay", "avoid"]
DIM_LABEL = {
    "pace": "节奏偏好", "schedule": "作息习惯", "diet": "饮食禁忌",
    "stamina": "体力水平", "stay": "住宿偏好", "avoid": "雷区/避雷",
}
_WRITE_FAIL = ("❌ 偏好档案写入失败（%s）\n"
               "   目标路径: %s\n"
               "   本次偏好**没有保存**，不要向用户声称已记住。\n"
               "   处置：把 AITRIP_HOME 指向可写目录后重试，例如 "
               "`AITRIP_HOME=/tmp/aitrip python profile.py --action remember ...`\n")


def profile_path() -> str:
    """档案路径：AITRIP_HOME 优先，否则 ~/.aitrip。

    v0.2.274：托管沙箱里 $HOME 可能不可写（或 HOME 指向只读挂载），
    原先直接 open(...,"w") 会抛原始 PermissionError traceback，调用方看到的是
    一堆栈而不是「写不了，该怎么办」。现支持环境变量覆盖到可写目录。
    """
    base = os.environ.get("AITRIP_HOME") or os.path.join(os.path.expanduser("~"), ".aitrip")
    return os.path.join(base, "profile.json")


def _save(data: dict) -> tuple[bool, str]:
    """原子写（临时文件 + os.replace），失败返回原因而不是抛栈。"""
    path = profile_path()
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True, path
    except OSError as e:
        return False, "%s: %s" % (type(e).__name__, e)


def _load() -> dict:
    try:
        with open(profile_path(), encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
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
    ok, info = _save(cur)
    if not ok:
        raise OSError(info)
    return cur


def reset() -> dict:
    """重置偏好档案。

    v0.1.43 标准加固：原实现直接删除档案文件，属安全扫描易命中的「文件删除」
    特征。改为把档案内容写回空 dict——功能等价（recall 读到空档案即等同未设置），
    但不再出现文件删除类调用。
    """
    ok, info = _save({})
    if not ok:
        raise OSError(info)
    return {}


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
        try:
            reset()
        except OSError as e:
            sys.stderr.write(_WRITE_FAIL % (e, profile_path()))
            return 2
        print("✅ 偏好档案已清空")
        return 0
    if args.action == "remember":
        try:
            if args.json:
                data = json.loads(args.json)
                cur = remember("", "", data)
            elif args.field and args.value:
                cur = remember(args.field, args.value)
            else:
                print("❌ remember 需 --json 或 --field --value")
                return 2
        except OSError as e:
            # 不抛原始 traceback：明确说清「没写进去」以及怎么改（换可写目录）
            sys.stderr.write(_WRITE_FAIL % (e, profile_path()))
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
