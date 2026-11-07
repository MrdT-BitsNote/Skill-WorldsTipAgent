#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_workbuddy_pack.py — WorkBuddy 平台发布包构建器（解压 <= 3MB 约束）。

与 build_pack.py 的差别（都是平台侧的硬约束，不是内容裁剪）：

1. **解压体积上限 3 MiB**（3145728 字节）。WorkBuddy 校验的是「解压后总大小」，
   而千问校验的是 zip 体积，所以两者不能共用一个包。
2. **SKILL.md 引用的文件必须真实存在**。平台会按 SKILL.md 里的路径逐条核对，
   引用了却不存在 → 判「内置文件缺失」。因此本脚本在裁掉大文件的同时，
   把 SKILL.md / README 里对它们的引用改写成不含路径的说明文字。

裁剪对象（均可再生 / 非运行期必需）：
  docs/            开发者文档（含专项说明）
  fixtures/        离线夹具
  tools/           构建脚本
  tests/test/      验证集
  assets/          图标（README 目录树引用）
  references/places_history.json   人文史 sidecar（含高敏词，且仅 history_query 按需用）
  references/worldstip_sites.json  自有站点外链清单
  references/api-spec.md           自有站点接口规格
  scripts/motofun.py / motofun_route.py / site_query.py   联网采集
  scripts/render_booklet.py        仅 --rich 九风格增强用

用法：
    python tools/build_workbuddy_pack.py [--out PATH]
"""
import argparse
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_pack as BP  # noqa: E402  复用 collect() / pack_bytes() / VER

LIMIT = 3 * 1024 * 1024  # WorkBuddy 解压后上限 3145728 字节

EX_DIRS = {"docs", "fixtures", "tools", "test", "tests", "assets"}
EX_FILES = {
    "growth_log.md",
    "CONTEXT.md",
    "references/worldstip_sites.json",
    "references/api-spec.md",
    "references/places_history.json",
    "scripts/motofun.py",
    "scripts/motofun_route.py",
    "scripts/site_query.py",
    "scripts/render_booklet.py",
}

# 行级替换：把「引用已裁文件」的句子改写为自洽描述（不留路径，避免幽灵引用）
LINE_RULES = (
    ("自有站点按需采集",
     "- **地点层与采集**：`references/moto_places.json`（2514 条，带 `fn` 全称与 `alt` 别名，"
     "由 `places_query.py` 消费）；摩旅与城市游玩优先用本地离线数据，不联网、不拼接外部接口。"),
    ("**人文史 sidecar** `references/places_history.json`",
     "**人文史查询** `scripts/history_query.py`（人文史数据未随本包分发）；"),
)

SUB_RULES = (
    # 自有站点取数链路：整句去掉联网描述
    (r"再走 `scripts/motofun_route\.py`；取数统一 `scripts/motofun\.py --offline --data-dir "
     r"fixtures --json`，", "再由本技能的摩旅/美食门禁与本地数据支撑，"),
    (r"接口口径见 `references/api-spec\.md`，", ""),
    (r"①新增 `site_query\.py` \+ `worldstip_sites\.json`：按需读取 moto\.worldstip\.com 路线与 "
     r"fun\.worldstip\.com 商圈/美食等数据[^；]*；", "①新增本地离线数据支撑与降级口径；"),
)

# 文档引用：markdown 链接 → 反引号 → 裸路径，三态都清
DOC_PATTERNS = (
    (r"\[`docs/[^`]+?\.md`\]\(docs/[^)]+?\)", "专项文档"),
    (r"`docs/[^`]+?\.md`", "专项文档"),
    (r"docs/[A-Za-z0-9_]+\.md", "专项文档"),
)

DISPLAY_RULES = (
    ('display_name: "WorldsTip旅行指南小册子·合并版"',
     'display_name: "WorldsTip旅行指南小册子·融合版"'),
    ('displayName: "WorldsTip旅行指南小册子·合并版"',
     'displayName: "WorldsTip旅行指南小册子·融合版"'),
)

# README 目录树里指向已裁对象的整行
DROP_LINE_KEYS = ("worldstip_sites.json", "site_query.py", "test_site_query.py",
                  "assets/logo.svg")


def patch_skill(t, align_display=True):
    out = []
    for line in t.split("\n"):
        hit = next((rep for key, rep in LINE_RULES if key in line), None)
        out.append(hit if hit else line)
    t = "\n".join(out)
    for pat, rep in SUB_RULES + DOC_PATTERNS:
        t = re.sub(pat, rep, t)
    t = t.replace("`fixtures/`", "本地离线夹具").replace("fixtures/", "本地离线夹具")
    t = t.replace("Offline fixtures", "Offline bundled data")
    t = t.replace("`render_booklet.py`", "增强渲染器").replace("render_booklet.py", "增强渲染器")
    if align_display:
        for a, b in DISPLAY_RULES:
            t = t.replace(a, b)
    return t


def patch_readme(t):
    out = [line for line in t.split("\n")
           if not any(k in line for k in DROP_LINE_KEYS)]
    t = "\n".join(out)
    for pat, rep in SUB_RULES + DOC_PATTERNS:
        t = re.sub(pat, rep, t)
    t = t.replace("`fixtures/`", "本地离线夹具").replace("fixtures/", "本地离线夹具")
    t = t.replace("`render_booklet.py`", "增强渲染器").replace("render_booklet.py", "增强渲染器")
    return t


def build(out, align_display=True):
    selected = []
    for rel, p in BP.collect():
        top = rel.split("/")[0]
        if "/" in rel and top in EX_DIRS:
            continue
        if rel in EX_FILES:
            continue
        selected.append((rel, p))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, p in selected:
            data = BP.pack_bytes(p)
            if rel == "SKILL.md":
                data = patch_skill(data.decode("utf-8"), align_display).encode("utf-8")
            elif rel == "README.md":
                data = patch_readme(data.decode("utf-8")).encode("utf-8")
            zi = zipfile.ZipInfo(rel, date_time=(2026, 11, 7, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zi.create_system = 3
            z.writestr(zi, data)
    return out, selected


def report(out):
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        total = sum(i.file_size for i in z.infolist())
        skill = z.read("SKILL.md").decode("utf-8")
        readme = z.read("README.md").decode("utf-8")
    print("包路径 : %s" % out)
    print("文件数 : %d" % len(names))
    print("zip    : %d bytes (%.2f MB)" % (os.path.getsize(out), os.path.getsize(out) / 1048576.0))
    print("解压   : %d bytes (%.2f MB)  上限 %d  余量 %d  合规=%s"
          % (total, total / 1048576.0, LIMIT, LIMIT - total, total <= LIMIT))
    print("根级   : SKILL.md=%s  外层目录=%s"
          % ("SKILL.md" in names, any("/" in n for n in names) and "SKILL.md" not in names))
    print("最大深度: %d" % max(n.count("/") for n in names))
    bad = [n for n in names if n.startswith("_") or "__pycache__" in n
           or n.startswith(("tests/", "test/")) or n.endswith((".zip", ".bak"))]
    print("违规条目: %s" % (bad[:5] or "无"))
    for key in ("version:", "name:", "display_name:"):
        line = next((l for l in skill.split("\n") if l.startswith(key)), "(缺)")
        print("  %s" % line)
    ghosts = {tok: skill.count(tok) for tok in
              ("docs/", "fixtures", "render_booklet", "places_history",
               "worldstip_sites", "api-spec", "motofun", "site_query")}
    print("SKILL 残留: %s" % ghosts)
    print("README 残留: %s" % {tok: readme.count(tok) for tok in
                              ("docs/", "render_booklet", "places_history",
                               "worldstip_sites", "api-spec", "motofun", "site_query")})
    return total <= LIMIT and not bad


def main():
    ap = argparse.ArgumentParser(description="构建 WorkBuddy 发布包（解压 <= 3MB）")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = args.out or os.path.join(
        os.path.dirname(BP.ROOT), "dist",
        "worldstip-travel-planner-v%s-workbuddy.zip" % BP.VER)
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    out, _ = build(out)
    ok = report(out)
    print("RESULT: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
