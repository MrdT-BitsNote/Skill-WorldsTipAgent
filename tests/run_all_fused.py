#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""融合版一键回归总入口：行程 27 项 + 数据引擎 204 项 + 融合专项 + v0.2.1 逻辑反例。任一失败 EXIT 1。"""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUITES = [
    ("行程编排回归", ROOT / "tests/run_tests.py"),
    ("准入许可灰灯专项", ROOT / "tests/test_visa_gate_merged.py"),
    ("数据引擎回归", ROOT / "test/run_all.py"),
    ("融合专项", ROOT / "tests/test_fusion.py"),
    ("v0.2.1 逻辑反例", ROOT / "tests/test_logic_fixes.py"),
]

def main():
    bad = []
    for name, p in SUITES:
        print(f"\n========== {name} :: {p.relative_to(ROOT)} ==========")
        r = subprocess.run([sys.executable, "-B", str(p)], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=600)
        tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-6:])
        print(tail)
        print(f"  -> EXIT {r.returncode}")
        if r.returncode != 0: bad.append((name, r.returncode))
    print(f"\nSUITES: {len(SUITES) - len(bad)} / {len(SUITES)} PASS")
    for n, rc in bad: print(f"  FAILED {n} exit={rc}")
    return 1 if bad else 0

if __name__ == "__main__":
    raise SystemExit(main())
