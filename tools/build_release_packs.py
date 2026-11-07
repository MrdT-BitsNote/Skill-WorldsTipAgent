# -*- coding: utf-8 -*-
"""build_release_packs.py — 三平台发布包（WorkBuddy / SkillHub / DuMate）。

复用 build_pack.collect() 的同一套文件清单（含新增的 ANTI_DISTILL.md），
按平台追加元数据：
  - WorkBuddy : 标准 SKILL.md 包（不加额外文件）
  - SkillHub  : 追加 _meta.json（slug/displayName/version/summary/license）
  - DuMate    : 追加 PLATFORM.md（百度 DuMate 平台导入说明）
固定时间戳 + 稳定排序 + 文本 LF 归一 + 字节可复核。
"""
from __future__ import print_function
import os, sys, zipfile, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_pack as BP  # 复用 collect() / pack_bytes()
import audit_upload_zip as AU  # noqa: E402  审核器视角硬闸门

ROOT = BP.ROOT
VER = BP.VER
STAMP = (2026, 11, 7, 0, 0, 0)

META_JSON = json.dumps({
    "slug": "worldstip-travel-planner",
    "displayName": "WorldsTip 旅行规划小册子",
    "version": "1.2.1",
    "summary": "输入目的地与天数，生成 A5 紧凑旅行小册子：怎么去、必吃必玩、逐日动线、安全提醒；基于真实 POI 与气候数据，绝不编造。",
    "license": "MIT",
    "internalVersion": VER,
}, ensure_ascii=False, indent=2).encode("utf-8")

PLATFORM_MD = (
    "# 百度 DuMate 平台导入说明\n\n"
    "本技能包与 SkillHub / WorkBuddy 同源，**直接读取根目录 `SKILL.md`**，无需改造。\n\n"
    "## 导入方式\n"
    "1. 解压本包，得到含 `SKILL.md` 的技能根目录。\n"
    "2. 在百度 DuMate 桌面 AI 智能体平台，选择「导入技能 / 本地技能」，指向该根目录。\n"
    "3. DuMate 会按 `SKILL.md` 的 frontmatter（name / description / allowed-tools / license）识别并加载。\n\n"
    "## 版本与授权\n"
    "- 内部开发版本：**%s**（全平台统一，杜绝版本错位）。\n"
    "- 许可：MIT，附加反蒸馏条款（见 `ANTI_DISTILL.md`）：禁止未授权搬运、二次分发、用于模型训练/蒸馏。\n"
    "- 归属：WorldsTip by MrdT。\n" % VER
).encode("utf-8")


def add_to_items(items, rel, data):
    items = [it for it in items if it[0] != rel]
    items.append((rel, data))
    return items


def build(out, extra_rel=None, extra_data=None, verify=True):
    items = BP.collect()
    if extra_rel:
        items = add_to_items(items, extra_rel, extra_data)
    items = sorted(items)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, p in items:
            if isinstance(p, bytes):
                data = p
            else:
                data = BP.pack_bytes(p)
            zi = zipfile.ZipInfo(rel, date_time=STAMP)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zi.create_system = 3
            z.writestr(zi, data)
    print("包路径 : %s" % out)
    print("文件数 : %d" % len(items))
    print("体积   : %s bytes (%.2f MB)" % (os.path.getsize(out), os.path.getsize(out) / 1048576.0))
    if verify:
        with zipfile.ZipFile(out) as z:
            bad = []
            for rel, p in items:
                exp = p if isinstance(p, bytes) else BP.pack_bytes(p)
                if z.read(rel) != exp:
                    bad.append(rel)
            print("字节一致校验: %s" % ("PASS" if not bad else "FAIL " + str(bad[:5])))
            return 1 if bad else 0
    return 0


def main():
    dist = os.path.join(os.path.dirname(ROOT), "dist")
    # WorkBuddy 有「解压 <= 3MB」+「SKILL.md 引用必须存在」双约束，
    # 必须走专用构建器（瘦身 + 引用改写），不能复用完整包清单。
    import build_workbuddy_pack as BWB
    wb_out, _ = BWB.build(os.path.join(
        dist, "worldstip-travel-planner-v%s-workbuddy.zip" % VER))
    wb = 0 if BWB.report(wb_out) else 1
    sh = build(os.path.join(dist, "worldstip-travel-planner-v%s-skillhub.zip" % VER),
               "_meta.json", META_JSON, verify=True)
    dm = build(os.path.join(dist, "worldstip-travel-planner-v%s-dumate.zip" % VER),
               "PLATFORM.md", PLATFORM_MD, verify=True)
    # 硬闸门补齐：WorkBuddy 已在专用构建器内拦过；完整包（SkillHub / DuMate）
    # 同样不能夹带会被审核器当成「必需资源」的中文名词或指向被裁文档的路径。
    sh_out = os.path.join(dist, "worldstip-travel-planner-v%s-skillhub.zip" % VER)
    dm_out = os.path.join(dist, "worldstip-travel-planner-v%s-dumate.zip" % VER)
    clean = True
    for p in (sh_out, dm_out):
        print("\n=== 审核器视角硬闸门: %s ===" % os.path.basename(p))
        try:
            AU.assert_clean(p)
        except RuntimeError as e:
            print("  %s" % e)
            clean = False
    print("\nWorkBuddy=%s  SkillHub=%s  DuMate=%s  硬闸门=%s"
          % (wb, sh, dm, "PASS" if clean else "FAIL"))
    return wb or sh or dm or (0 if clean else 1)


if __name__ == "__main__":
    sys.exit(main())
