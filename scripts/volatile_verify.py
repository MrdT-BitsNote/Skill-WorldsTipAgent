#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""易变数据自动核验脚本 —— 扫描 references/*.json 中所有 volatile 标记，
检查新鲜度（stale_after_days=30），产出核验清单。

设计纪律：
- 零第三方依赖，仅用标准库。
- 纯扫描逻辑与 I/O 分离，便于离线回归测试。
- 与 credibility.py 共享 stability.json 的 stale_after_days 阈值。

用法:
  python volatile_verify.py                  # 人类可读报告
  python volatile_verify.py --json           # 机器可读 JSON 输出
  python volatile_verify.py --strict         # 有 stale 条目则 exit 1
  python volatile_verify.py --file poi.json  # 只检查指定文件
  python volatile_verify.py --fix            # 自动刷新 updated 日期戳（危险操作，需确认）
"""
import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

REF_DIR = Path(__file__).resolve().parent.parent / "references"
STABILITY_FILE = REF_DIR / "stability.json"

STALE_DAYS_DEFAULT = 30

# stability.json 中 domains 下所有 volatile 字段名（用于匹配 JSON key）
_VOLATILE_FIELD_NAMES: set[str] | None = None


def _load_volatile_fields() -> set[str]:
    global _VOLATILE_FIELD_NAMES
    if _VOLATILE_FIELD_NAMES is None:
        with open(STABILITY_FILE, encoding="utf-8") as f:
            db = json.load(f)
        names = set()
        for dom in db.get("domains", {}).values():
            for fname, level in (dom.get("fields") or {}).items():
                if level == "volatile":
                    names.add(fname)
        _VOLATILE_FIELD_NAMES = names
    return _VOLATILE_FIELD_NAMES


def _stale_days() -> int:
    with open(STABILITY_FILE, encoding="utf-8") as f:
        db = json.load(f)
    return int(db.get("render", {}).get("stale_after_days", STALE_DAYS_DEFAULT))


def _parse_date(s: str) -> date | None:
    if not s or not isinstance(s, str):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s.strip()[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            pass
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _age_days(d: date, today: date | None = None) -> int:
    return ((today or date.today()) - d).days


# ── 扫描逻辑 ──────────────────────────────────────────────────────────────

class VolatileEntry:
    """一条 volatile 数据记录。"""
    __slots__ = ("file", "path", "kind", "field", "date", "age", "source_hint")

    def __init__(self, file: str, path: str, kind: str, field: str,
                 date_val: date | None, today: date | None = None,
                 source_hint: str = ""):
        self.file = file
        self.path = path
        self.kind = kind          # "stability_tag" | "update_stamp" | "volatile_field" | "vol_note"
        self.field = field
        self.date = date_val
        self.age = _age_days(date_val, today) if date_val else None
        self.source_hint = source_hint

    @property
    def is_stale(self) -> bool:
        if self.age is None:
            return True  # no date = untrusted
        return self.age > _stale_days()

    @property
    def status(self) -> str:
        if self.date is None:
            return "missing_date"
        if self.is_stale:
            return "stale"
        return "fresh"

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "path": self.path,
            "kind": self.kind,
            "field": self.field,
            "date": self.date.isoformat() if self.date else None,
            "age_days": self.age,
            "status": self.status,
            "source_hint": self.source_hint,
        }


def scan_file(filepath: Path, today: date | None = None) -> list[VolatileEntry]:
    """扫描单个 JSON 文件，返回所有 volatile 相关条目。"""
    entries: list[VolatileEntry] = []
    fname = filepath.name
    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return entries

    vol_fields = _load_volatile_fields()

    # extract file-level date as fallback for nested tags
    file_date: date | None = None
    for key in ("_updated", "updated", "built_at"):
        val = data.get(key)
        if isinstance(val, str):
            file_date = _parse_date(val)
            if file_date:
                break

    # 1. top-level update stamps
    for key in ("updated", "_updated", "built_at", "verified_note"):
        val = data.get(key)
        if isinstance(val, str):
            d = _parse_date(val)
            entries.append(VolatileEntry(
                fname, f".{key}", "update_stamp", key, d, today,
                source_hint="文件级时间戳"))

    # 2. recursive scan for _stability / volatile / vol_note / _stability_split
    def walk(obj, path: str):
        if isinstance(obj, dict):
            for k, v in obj.items():
                cp = f"{path}.{k}"
                # _stability tag
                if k == "_stability" and isinstance(v, str):
                    if v.lower() == "volatile":
                        sibling_date = None
                        for dk in ("_updated", "updated", "verified_on"):
                            dv = obj.get(dk)
                            if isinstance(dv, str):
                                sibling_date = _parse_date(dv)
                                break
                        if sibling_date is None:
                            sibling_date = file_date
                        entries.append(VolatileEntry(
                            fname, cp, "stability_tag", k, sibling_date, today,
                            source_hint=f"{fname} 内嵌 volatile 标记"))
                    elif v.lower() == "stable":
                        pass
                # volatile boolean
                elif k == "volatile" and v is True:
                    sibling_date = None
                    for dk in ("_updated", "updated", "verified_on"):
                        dv = obj.get(dk)
                        if isinstance(dv, str):
                            sibling_date = _parse_date(dv)
                            break
                    if sibling_date is None:
                        sibling_date = file_date
                    entries.append(VolatileEntry(
                        fname, cp, "stability_tag", k, sibling_date, today,
                        source_hint=f"{fname} 内嵌 volatile=true"))
                # vol_note — use file_date as reference
                elif k == "vol_note" and isinstance(v, str):
                    entries.append(VolatileEntry(
                        fname, cp, "vol_note", k, file_date, today,
                        source_hint=v[:60]))
                # _stability_split — use file_date as reference
                elif k == "_stability_split" and isinstance(v, str):
                    entries.append(VolatileEntry(
                        fname, cp, "stability_tag", k, file_date, today,
                        source_hint=v[:80]))
                # field names matching stability.json volatile domains
                elif k in vol_fields and isinstance(v, (str, int, float, list, dict)):
                    if isinstance(v, dict):
                        d = _parse_date(v.get("_updated", "")) or _parse_date(v.get("updated", ""))
                    else:
                        d = None
                    if d is None:
                        d = file_date
                    entries.append(VolatileEntry(
                        fname, cp, "volatile_field", k, d, today,
                        source_hint=f"匹配 stability.json volatile 字段: {k}"))
                walk(v, cp)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")

    walk(data, fname)
    return entries


SKIP_FILES = {"stability.json"}  # the dictionary itself, not data


def scan_all(today: date | None = None, only_file: str | None = None) -> list[VolatileEntry]:
    """扫描全部 references/*.json（跳过 stability.json 字典本身）。"""
    all_entries: list[VolatileEntry] = []
    for fp in sorted(REF_DIR.glob("*.json")):
        if fp.name in SKIP_FILES:
            continue
        if only_file and fp.name != only_file:
            continue
        all_entries.extend(scan_file(fp, today))
    return all_entries


# ── 报告 ──────────────────────────────────────────────────────────────────

def summarize(entries: list[VolatileEntry]) -> dict:
    by_status: dict[str, int] = {}
    by_file: dict[str, dict[str, int]] = {}
    by_kind: dict[str, int] = {}
    for e in entries:
        by_status[e.status] = by_status.get(e.status, 0) + 1
        by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
        if e.file not in by_file:
            by_file[e.file] = {"fresh": 0, "stale": 0, "missing_date": 0}
        by_file[e.file][e.status] += 1
    return {
        "total": len(entries),
        "by_status": by_status,
        "by_kind": by_kind,
        "by_file": by_file,
        "stale_after_days": _stale_days(),
    }


def render_report(entries: list[VolatileEntry], summary: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("  VOLATILE 数据自动核验报告")
    lines.append(f"  扫描时间: {date.today().isoformat()}  |  过期阈值: {summary['stale_after_days']} 天")
    lines.append("=" * 72)
    lines.append("")

    s = summary["by_status"]
    lines.append(f"  总计: {summary['total']} 条 volatile 数据")
    lines.append(f"  新鲜: {s.get('fresh', 0)}  |  过期: {s.get('stale', 0)}  |  缺日期: {s.get('missing_date', 0)}")
    lines.append("")

    # stale entries
    stale = [e for e in entries if e.status == "stale"]
    missing = [e for e in entries if e.status == "missing_date"]
    fresh = [e for e in entries if e.status == "fresh"]

    if stale:
        lines.append("-" * 72)
        lines.append(f"  ⚠ 过期条目 ({len(stale)} 条) — 需要重新核验")
        lines.append("-" * 72)
        for e in stale:
            lines.append(f"  [{e.file}] {e.path}")
            lines.append(f"    字段: {e.field}  |  日期: {e.date}  |  已过 {e.age} 天")
            if e.source_hint:
                lines.append(f"    提示: {e.source_hint}")
            lines.append("")

    if missing:
        lines.append("-" * 72)
        lines.append(f"  ✗ 缺少日期戳 ({len(missing)} 条) — 无法判断新鲜度")
        lines.append("-" * 72)
        for e in missing:
            lines.append(f"  [{e.file}] {e.path}")
            lines.append(f"    字段: {e.field}  |  类型: {e.kind}")
            if e.source_hint:
                lines.append(f"    提示: {e.source_hint}")
            lines.append("")

    if fresh:
        lines.append("-" * 72)
        lines.append(f"  ✓ 新鲜条目 ({len(fresh)} 条)")
        lines.append("-" * 72)
        for e in fresh:
            lines.append(f"  [{e.file}] {e.path}  日期: {e.date}  剩余 {summary['stale_after_days'] - e.age} 天")
        lines.append("")

    # per-file summary
    lines.append("-" * 72)
    lines.append("  按文件汇总")
    lines.append("-" * 72)
    lines.append(f"  {'文件':<35} {'新鲜':>6} {'过期':>6} {'缺日期':>6}")
    for fname, counts in sorted(summary["by_file"].items()):
        lines.append(f"  {fname:<35} {counts['fresh']:>6} {counts['stale']:>6} {counts['missing_date']:>6}")
    lines.append("")

    # verification checklist
    action_items = stale + missing
    if action_items:
        lines.append("-" * 72)
        lines.append(f"  核验清单 ({len(action_items)} 条待处理)")
        lines.append("-" * 72)
        for i, e in enumerate(action_items, 1):
            src = e.source_hint or "官方渠道"
            lines.append(f"  {i}. [{e.file}] {e.field}")
            lines.append(f"     → 核验来源: {src}")
            lines.append(f"     → 操作: 联网确认后更新 _updated / verified_note 日期戳")
        lines.append("")

    lines.append("=" * 72)
    if not action_items:
        lines.append("  ✓ 全部 volatile 数据在有效期内，无需核验。")
    else:
        lines.append(f"  ⚠ {len(action_items)} 条 volatile 数据需要核验。")
    lines.append("=" * 72)
    return "\n".join(lines)


# ── --fix: 自动刷新日期戳 ────────────────────────────────────────────────

def fix_dates(entries: list[VolatileEntry]) -> int:
    """将 stale/missing 条目的文件级 updated/_updated 刷新为今天。返回修复文件数。"""
    today_str = date.today().isoformat()
    files_to_fix: dict[str, str] = {}
    for e in entries:
        if e.status in ("stale", "missing_date"):
            files_to_fix[e.file] = today_str

    fixed = 0
    for fname, new_date in files_to_fix.items():
        fp = REF_DIR / fname
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, FileNotFoundError):
            continue
        changed = False
        for key in ("updated", "_updated"):
            if key in data:
                data[key] = new_date
                changed = True
        if not changed and "updated" not in data and "_updated" not in data:
            data["_updated"] = new_date
            changed = True
        if changed:
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            fixed += 1
    return fixed


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="易变数据自动核验")
    ap.add_argument("--json", action="store_true", help="输出 JSON 格式")
    ap.add_argument("--strict", action="store_true", help="有 stale 条目则 exit 1")
    ap.add_argument("--file", type=str, default=None, help="只检查指定文件")
    ap.add_argument("--fix", action="store_true", help="自动刷新 updated 日期戳")
    args = ap.parse_args()

    entries = scan_all(only_file=args.file)
    summary = summarize(entries)

    if args.fix:
        action = [e for e in entries if e.status in ("stale", "missing_date")]
        if not action:
            print("无需修复：所有 volatile 数据均在有效期内。")
            return
        fixed = fix_dates(action)
        print(f"已刷新 {fixed} 个文件的日期戳为 {date.today().isoformat()}。")
        print("注意：这只是日期戳刷新，数据内容本身仍需联网核验。")
        return

    if args.json:
        out = {
            "scanned_at": date.today().isoformat(),
            "summary": summary,
            "entries": [e.to_dict() for e in entries],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(render_report(entries, summary))

    if args.strict:
        stale_count = summary["by_status"].get("stale", 0) + summary["by_status"].get("missing_date", 0)
        if stale_count > 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
