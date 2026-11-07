# HANDOFF · WorldsTip 旅行规划技能接手手册

> **面向**：任何在任意机器接手本仓库继续修改的 agent 或开发者。
> **主线分支**：`v0.2.272`　|　**内部版本真源**：`VERSION.json` → `0.2.272`　|　**更新**：2026-11-07
> **一句话定位**：本仓库同时是「技能源码」「四个平台上传包」「WorkBuddy 专家包源码」「发布归档」的唯一真源，改任何东西都从这里出发，不要直接改 zip。

---

## 0. 三分钟起步（clone 后第一条命令）

```bash
# 目录名必须是 worldstip-travel-planner —— doctor.py 会校验 SKILL.md 的 name 与目录名一致，
# 用默认仓库名 Skill-WorldsTipAgent 会让自检误报 FAIL。
git clone -b v0.2.272 https://github.com/MrdT-BitsNote/Skill-WorldsTipAgent.git worldstip-travel-planner
cd worldstip-travel-planner

python scripts/doctor.py          # 离线自检 17 项，任一失败 EXIT 1
python tests/run_all.py           # 统一回归：16/16 套件 + 32/32 新增用例
python tools/verify_backup.py     # 备份完整性：源码 / 专家 / 四平台包 / 版本对齐
```

三条全绿才算「拿到的是完整可改的仓库」。环境只需 Python 3 标准库，**零联网、零外部依赖**。

---

## 1. 目录地图

| 路径 | 作用 | 改它之后要跑什么 |
| --- | --- | --- |
| `SKILL.md` | 技能正文，**硬约束恰好 500 行**、根级、纯 LF、frontmatter 含 `name/version/description/display_name` | `doctor.py` + `run_all.py` + 重建全部平台包 |
| `VERSION.json` | 版本真源，`version` 字段裁决 8 个文件的版本号 | `doctor.py`（逐文件比对） |
| `scripts/worldstip.py` | 统一入口：意图闸门 → 地名抽取/消歧 → 行程编排 → 交通比选 → 渲染 | `run_all.py` |
| `scripts/render_compact.py` | A5 紧凑册渲染；§6 为「本次行程出片清单」，按真实 POI 分题材 | `scripts/test_render_compact.py`（26 用例） |
| `scripts/doctor.py` | 离线自检（版本/结构/字段/语法/数据/引用/冒烟） | — |
| `references/*.json` | 静态数据层：POI、必吃、行政区划、车站码、气候、摩旅路线、人文史 sidecar | `doctor.py` + `run_all.py` |
| `references/data-quality.md` | 数据口径与三条红线、已知缺口 | 人工复核 |
| `docs/*.md` | 机制说明（22 篇）；**WorkBuddy 包只保留其中 9 篇** | 重建 WorkBuddy 包并跑引用核对 |
| `tools/build_pack.py` | 通用包构建器：`collect()` 文件清单、`pack_bytes()` LF 归一、`VER` 版本常量 | 重建全部包 |
| `tools/build_release_packs.py` | 一次产出 WorkBuddy / SkillHub / DuMate 三个包 | 见 §3 |
| `tools/build_workbuddy_pack.py` | WorkBuddy 专用：≤3 MiB 裁剪 + 引用改写 + `check_refs()` 核对 | 见 §3 |
| `tools/build_qianwen_pack.py` | 千问专用：安全绿网净化 + 自检 report | 见 §3 |
| `tools/build_expert_pack.py` | 从 `expert/` 源码重建专家 zip（外层目录、固定时间戳） | 见 §3 |
| `tools/verify_backup.py` | 备份完整性确定性自检 | 提交前跑 |
| `expert/worldstip-travel-expert/` | **专家包可编辑源码**（`plugin.json` + agent md + 头像 + 许可） | `build_expert_pack.py --verify` |
| `releases/` | 已交付/可上传的 zip 归档（被 `.gitignore` 忽略，用 `git add -f` 跟踪） | `verify_backup.py` |
| `HANDOFF.md` | 本文件，仅仓库维护用 | — |
| `fixtures/`、`tests/`、`test/`、`assets/` | 离线夹具、验证集、图标 | `run_all.py` |

**隔离资产**（`HANDOFF.md`、`expert/`、`build_expert_pack.py`、`verify_backup.py`）已被三个构建器显式排除，**不会进入任何平台上传包**。原因见 §5 的 WorkBuddy 驳回记录：审核器会把文档里出现的文件名当作「必须存在的资源」逐个索要。

---

## 2. 版本线与分支（重要：远端 main 不是开发主线）

| 分支 | 远端提交 | 内容 |
| --- | --- | --- |
| `main` | `457eedf` | GitHub 建仓时的独立初始提交，**与本地开发历史不同源**（本地仓库里没有这个对象） |
| `v0.2.26` | `b134dc0` | §6 拍摄清单行程锚定 + `陵` 误判修复，SkillHub 包 |
| `v0.2.27` | `8148a4b` | WorkBuddy 补齐 `LICENSE` 与 11 个被引用的 docs，废弃「占位词」路线 |
| `v0.2.271` | `735f46c` | 千问二轮绿网整改：去出境数据 / 品牌导流 / 描述不符 |
| `v0.2.272` | 本分支 | 剔除文件对照型文档（`FUSION.md` / `UNIFIED_ENTRY.md`）；**技能 + 专家 + 文档完整备份** |

**不要 `git push origin main`**：远端 `main` 与本地 `main` 不同源，强推会覆盖建仓初始提交。所有迭代走非破坏性版本分支，本地 `main` 只作开发工作区。查当前分支提交用 `git rev-parse HEAD`。

**版本号规则**（平台会硬性校验）：
1. 内部版本统一由 `VERSION.json.version` 裁决，改版本必须同步 `SKILL.md`、`README.md`、`CHANGELOG.md`、`INSTALL.md`、`QC_REPORT.md`、`DoD.md`、`scripts/worldstip.py`、`tools/build_pack.py` 共 8 处，`doctor.py` 逐项比对。
2. WorkBuddy 要求包内 `version` **严格大于**平台当前最新版本；被驳回后重传必须递增（`0.2.26 → 0.2.27 → 0.2.271 → 0.2.272`）。
3. SkillHub 的 `_meta.json.version` 是**平台发布号**（`1.2.0`），与内部版本分离；用 `internalVersion` 字段对齐内部版本，两者不要混写。
4. 专家包 `plugin.json.version`（`1.0.0`）是**独立版本线**，只在专家包结构变化时递增；与技能版本通过 `expert/worldstip-travel-expert/README.md` 的对应表对齐。
5. `SKILL.md` 恰好 500 行：增删内容要原地合并 blockquote / 删空行，不能靠追加行。

---

## 3. 四个平台包：差异、约束与构建命令

| 平台 | 产物 | 硬约束 | 特殊处理 |
| --- | --- | --- | --- |
| **WorkBuddy** | `worldstip-travel-planner-v0.2.272-workbuddy.zip` | 解压后 ≤ **3 MiB**（3,145,728 B）；md 里点名的文件必须真实存在；`display_name` 在同类型资产中唯一；包内 `name` 必须与资产 name 一致；`version` 递增 | 裁掉 `fixtures/tools/tests/assets`、未被 `SKILL.md` 引用的 docs、`places_history.json`、`render_booklet.py` 等；`display_name` 改为「融合版」；`SKILL.md`/README 里的引用整句改写为自洽描述；`LICENSE` 真实入包 |
| **SkillHub** | `…-skillhub.zip` | 包根 `SKILL.md`；追加 `_meta.json` | 完整包（127 文件），平台发布号 `1.2.0`；上传地址 `https://skillhub.cn/skills/indiv-mrdt/worldstip` |
| **DuMate（百度）** | `…-dumate.zip` | 复用标准 `SKILL.md` 包 | 与 SkillHub 同源，仅追加 `PLATFORM.md` 导入说明 |
| **千问 AI** | `…-qianwen.zip` | ZIP ≤ **10 MiB**；根级 `SKILL.md`；frontmatter 必填 `name` + `description`；**安全绿网**内容扫描 | 在 WorkBuddy 裁剪集上再剔开发文档与出境数据文件、域名改机构名、去品牌词与限制性条款；约 75 文件 |
| **专家包** | `worldstip-travel-expert.zip` | zip 内保留外层目录 `worldstip-travel-expert/`（与技能包相反） | `.codebuddy-plugin/plugin.json` + `agents/*.md` + 512×512 PNG 头像 + 许可 |

```bash
# 从仓库根执行，产物写到同级 dist/
python tools/build_release_packs.py                 # WorkBuddy + SkillHub + DuMate（含字节一致校验 + WorkBuddy report）
python tools/build_qianwen_pack.py                  # 千问（含绿网自检 report）
python tools/build_expert_pack.py --verify          # 专家包

# 单包复核 / 指定输出
python tools/build_pack.py --out /tmp/full.zip --verify
python tools/build_workbuddy_pack.py --verify       # 若支持，见 --help
python tools/verify_backup.py --json                # 机器可读结论
```

所有构建器共用 `build_pack.collect()` 的同一份文件清单，固定时间戳 `(2026,11,7,0,0,0)`、稳定排序、文本统一 LF，**同输入产出字节可复现**；`--verify` 逐条目比对包内字节与源码。构建完把 `dist/` 的 zip 复制进 `releases/`（用 `git add -f`），`verify_backup.py` 会校验两处字节一致。

**当前实测基线**（v0.2.272）：WorkBuddy 92 文件 / 解压 2,968,514 B / zip 989,126 B，引用核对 166 条零缺失；千问 75 文件 / zip 910,340 B；SkillHub / DuMate 127 文件 / zip 约 1.51 MB。

---

## 4. 回归与自检命令（改完必跑）

```bash
python scripts/doctor.py --json                    # 17 项：版本真源 / 结构 / 字段 / .py 语法 / .json 可解析 / 文档引用 / 三分支冒烟
python tests/run_all.py                            # 16/16 套件 + 32/32 新增用例；任一失败 EXIT 1
python scripts/test_render_compact.py              # 26 用例：拍摄题材不误判（武陵源非建筑、东湖绿道、酒店商圈跳过）
python tools/verify_backup.py                      # 备份 + 包结构 + 版本对齐
```

`run_all.py` 覆盖：行程编排、灰灯专项、逻辑反例、融合专项、数据引擎边界、12 个脚本级回归、地名消歧、人文 sidecar、双渲染、manifest 字节可复核。**每个关键判据都配了「该失败」的负向夹具**，改判据时必须保留负向用例，否则会退化成假阳性绿灯。

**判据适用范围（改目录结构时必读）**：技能包的「两级目录」约束由三处独立实现——`scripts/doctor.py` 的 `SKIP_WALK`、`tests/test_fusion.py` 的 `_VCS`、`test/run_all.py` 的 `_VCS`。它们与 `tools/build_pack.SKIP_DIRS` 同步排除 `.git / releases / worldstip-out / 缓存 / expert`。`expert/` 是独立专家包源码，自带 `.codebuddy-plugin/` 与 `agents/` 子目录，不进技能交付包，因此不适用两级约束；它的结构完整性由 `tools/verify_backup.py` 单独校验（`plugin.json` 指向、6 文件齐备、头像 512×512、zip 外层目录）。**新增一个不进技能包的顶层目录时，四处排除集要一起改**，并重建四平台包。

---

## 5. 历史驳回 → 修法对照（别重复踩）

| 平台报错 | 根因 | 已落地的修法 |
| --- | --- | --- |
| `display_name` 已被使用 | 同类型资产名重复 | 加唯一后缀（`·MrdT` / 「融合版」），在 `patch_skill()` 内统一改写 |
| 包内 `name` 与资产 name 不一致 | 传错包（把 `delivery-no-pseudoblock` 包传到了 `worldstip-travel-planner` 资产） | 上传前核对包根 `SKILL.md` 的 `name`；`verify_backup.py` 校验四包版本与真源一致 |
| 解压后超出 3 MiB（3,178,519 B） | 完整包夹带 fixtures / docs / 富渲染 | 专用 `build_workbuddy_pack.py` 裁剪，压到 2,968,514 B |
| 版本号必须大于当前最新 | 重传未递增 | 版本线递增到 `0.2.272`，8 处版本同步 |
| 缺少「LICENSE」 | `ANTI_DISTILL.md` 用 markdown 链接引用它，但 `ALLOW_NOEXT` 未放行无扩展名文件 | `build_pack.py` 增加 `ALLOW_NOEXT = {LICENSE, LICENCE, NOTICE}` |
| 缺少「专项文档」 | 曾用中文占位词替换 `docs/*.md` 路径，审核器把占位词本身当文件名继续索要 | **占位词路线已废弃**：改为补回真实 docs 文件 |
| 缺少「摩旅路由.py」「本地离线夹具」「联网采集模块」 | `docs/FUSION.md` / `UNIFIED_ENTRY.md` 是文件对照记录，整篇点名了包里没有的文件 | 从 WorkBuddy 包剔除这两篇；其余 docs 命中被裁文件关键词时整行删除；`check_refs()` 复核 166 条引用 |
| WorkBuddy 引用核对失败 | `SKILL.md` / README 里写了被裁掉的路径 | `SKILL_EXACT` / `LINE_RULES` / `SUB_RULES` 整句改写为自洽描述，不留悬空路径 |
| 千问安全绿网 | 外链、政府域名、`QC_REPORT.md` 敏感词清单、限制性条款、品牌词、出境数据、导流电子书、描述与包内容不符 | 见 §6 |
| 千问 `re.compile` 被改坏 | 域名替换兜底把 `compile` 里的字母误伤 | `scrub_origins()` 限制 fallback 仅作用于 `.md/.json`；`DAMAGE` 正则自检源码误伤 |
| `description_en` 混入中文 | 夹具的英文描述被中文题材词污染 | S6 BLOCKER 发现并修，`doctor.py` 校验字段 |

---

## 6. 千问安全绿网规则（`build_qianwen_pack.py` 内已实现）

| 层 | 动作 |
| --- | --- |
| A 文件剔除 | `EX_QW_DIRS = BWB.EX_DIRS ∪ {docs}`；剔除 `CHANGELOG / DoD / QC_REPORT / INSTALL / ANTI_DISTILL / 报告生成规范 / 排版规范` |
| B 出境能力剔除 | 剔除 `country_safety.json`、`visa_rules.json`、`currency_tz.json`、`outbound_safety.py`、`food_book_links.json`；**保留** `outbound_constraints.py`（否则「香港」会被误判境外）与 `stability.json` |
| C 品牌与范围 | `BRAND_SUBS` 把 `WorldsTip/MrdT` 归零；`FM_TEXT` 重写 `description / description_zh / description_en`；`SCOPE_SUBS` 去掉「含港澳台」表述；`SKILL_REGEX_SUBS` 清掉 `food_book_links` 幽灵引用 |
| D 数据来源 | `scrub_origins()` 把域名改成机构名（`cs.mfa.gov.cn → 中国领事服务网` 等），fallback 仅限 `.md/.json`，避免误伤源码 |
| E 许可末行 | 去掉单方限制性条款，只留署名 + MIT 许可 |
| F 自检 | `DAMAGE` 查源码误伤；report 校验「无开发文档夹带 / 无出境能力文件 / 零外链 / 零品牌词 / 零高敏词」 |

**刻意不改的内容**（改了会破坏事实准确性或功能）：脚本里「台湾 / 香港 / 澳门」是用户输入别名与坐标字典键，同时包含「中国台湾 / 中国香港 / 中国澳门」规范写法；「南海区 / 南海神庙 / 钓鱼岛（吉林景点）/ 川藏南线」是同名词；「全国最早」「客运班车最便宜」是客观事实与功能对比。

---

## 7. 数据红线与数据规模

**三条红线**（`references/data-quality.md` §8）：① 不编造景点 / 票价 / 天气 / 店名；② 必吃只到**品类 + 参考价**，绝不指定具体店；③ 缺数据显式标灰降级（「未收录」「需现场确认」），不用「逛逛菜市场 / 温泉」这类模板凑数。跨省同名地名（幕阜山、临湘等）**先列候选再让用户选定**，不默认推断。

| 数据文件 | 实测规模 |
| --- | --- |
| `destinations.json` | 393 城坐标与气候 |
| `poi.json` | 20 城 / **104 条 POI**，每条含 `play`（玩法）与 `arrival`（怎么去） |
| `food_guide.json` | 26 个城市/区域键（含 `guiyangyangshuo` 合并键），只给品类 + 参考价 |
| `geo_admin.json` | 34 省级（含中国香港 / 中国澳门 / 中国台湾）/ 361 市 / 3001 县 |
| `station_codes.json` | 3405 个车站代码 |
| `places_history.json` | 1743 条人文史（sidecar，按需加载；WorkBuddy / 千问包不随包分发） |

拍§6「本次行程出片清单」由 `scripts/render_compact.py` 的纯函数 `_poi_photo_theme()` 按 POI 的 `name/tag/desc` 判题材；已修的建筑关键词误判（`陵` 会命中「武陵源」→ 改为 `陵墓/皇陵/十三陵/中山陵/孝陵/王陵/陵园`，`城` 过宽 → 改具体词），酒店 / 商圈 / 城市绿道跳过。

---

## 8. 已知缺口（如实披露，不要假装已覆盖）

1. **平台裁剪差异**：WorkBuddy 与千问包不含 `places_history.json`（人文史 sidecar）、`render_booklet.py`（`--rich` 九风格增强渲染）、`fixtures/`（离线夹具）、`docs/FUSION.md` 与 `UNIFIED_ENTRY.md`。这两个包的能力是完整包的子集，写文案时不要声称它们含这些能力。
2. **千问国内版不含出境能力**：`visa_rules / country_safety / currency_tz / outbound_safety` 已被剔除，只能做国内行程。
3. **静态快照**：POI / 气候 / 消费索引均为静态数据，不含营业状态、排队、实时票价、天气；实时联网为可选增强，默认离线。
4. **城市覆盖有限**：`poi.json` 20 城、`food_guide.json` 26 键，未覆盖城市在渲染层诚实标「未收录」；`destinations.json` 的 393 城坐标气候覆盖面远大于 POI 层。
5. **港澳台**：行政区划层已收录规范名称，但 POI / 必吃层未收录港澳目的地明细。
6. **数据对齐口径**：`references/data-quality.md` §5 记录 moto / fun 两数据集无共同主键、仅靠城市中文名对齐，数据更新后需重跑匹配率扫描；县级市与乡镇无单城档案，降级到省级即精度损失。
7. **离线夹具不含实时天气**：`--profile upload` 类审核需人工在平台侧确认，本地无法代替。

---

## 9. 变更纪律（照此顺序改，避免版本错位）

1. 改数据 → `doctor.py` + `run_all.py`；改渲染 → 加 `scripts/test_render_compact.py` 的负向用例。
2. 改 `SKILL.md` → 保持 500 行、纯 LF，同步 `VERSION.json` 与其余 7 个版本文件 → `doctor.py`。
3. 递增版本 → 重建**全部**四平台包 + 专家包 → `verify_backup.py` → `dist/` 旧包移入 `dist/_archive/`，新包进 `releases/`。
4. 改任一构建器的排除集 → 必须同步检查 `build_pack.SKIP_DIRS / SKIP_FILES`、`build_workbuddy_pack.EX_DIRS / EX_FILES`（千问继承 BWB 的排除集），并重建四包验证「接手资产未夹带」。
5. 提交到新的非破坏性版本分支（`git checkout -b v0.2.273`），`releases/*.zip` 用 `git add -f`；`git push -u origin <分支>` 后用 `git ls-remote --heads origin` 核验远端 SHA。
6. 上传平台前，用 `verify_backup.py` 确认包内 `name` / `version` / `display_name` 与目标资产匹配。

---

## 10. 接手检查清单

- [ ] clone 时目录名是 `worldstip-travel-planner`（否则 doctor 误报）
- [ ] `python scripts/doctor.py` 全绿
- [ ] `python tests/run_all.py` → `REGRESSION: PASS`
- [ ] `python tools/verify_backup.py` → `BACKUP: PASS`
- [ ] 四平台包 + 专家 zip 以 `releases/` 为权威副本；本地若有 `dist/`，`verify_backup.py` 会额外比对两处字节一致（无 `dist/` 时如实标 `SKIP`，不算失败）
- [ ] 新版本上传前确认 `version` 大于平台当前最新、`display_name` 唯一
- [ ] 未把 `HANDOFF.md` / `expert/` / 备份脚本打进任何上传包

---

## 11. 权属与许可

MIT 许可 + 权属水印，署名须保留「WorldsTip by MrdT」。反蒸馏条款见 `ANTI_DISTILL.md` 与 `LICENSE`（专家包内也各有一份）。`delivery-no-pseudoblock-v0.2.22-workbuddy.zip` 是配套的终检纪律辅助技能，独立版本线，仅作归档，不参与本技能构建。

---

## 12. WorkBuddy 官方专家包结构样板（2026-11-07 学习）

来源：`https://codebuddy-platform-1258344699.cos.ap-beijing.myqcloud.com/open/static/files/design-experts.zip`（官方示例专家包 `design-experts`，15,909 B）。解压后的有效文件只有 4 个，其余是 macOS 元数据（`.DS_Store`、`__MACOSX/`），不属于规范内容。

### 12.1 官方目录结构

```text
design-experts/
├── .codebuddy-plugin/plugin.json          专家包清单
├── agents/design-md-architect.md          Agent 定义（frontmatter + 正文）
├── avatars/expert.png                    头像（plugin.json 引用）
└── skills/
    └── design-reference/                 专家专属内嵌技能
        ├── SKILL.md
        └── references/README.md          按需读取的索引/数据
```

**要点**：专家包内可以内嵌技能，路径固定为 `skills/<技能名>/SKILL.md`；Agent 通过 frontmatter 的 `skills: [<技能名>]` 绑定。专家包允许多级嵌套目录，与技能上传包「目录深度 ≤ 1」是两套约束（见 §4 判据适用范围）。

### 12.2 三份文件的 frontmatter 是两套约定，不可混用

| 位置 | 官方字段 | 说明 |
| --- | --- | --- |
| `.codebuddy-plugin/plugin.json` | `name / version / description / author{name,email} / agents / expertType / agentName / displayName{en,zh} / profession{en,zh} / displayDescription{en,zh} / avatar / categoryId / defaultInitPrompt{zh,en} / plugin / tags[{en,zh}] / quickPrompts[{en,zh}]` | 共 16 个键，双语字段一律 `{en, zh}` |
| `agents/*.md` | `name / description / tools / maxTurns / skills` | `tools` 是数组；`skills` 绑定包内 `skills/` 下的技能名 |
| `skills/<name>/SKILL.md` | `title / summary / read_when` | **内嵌技能**用渐进披露式元数据（`read_when` 是触发条件列表），**不**写 `name/version/description` |

平台**独立上传包**的 `SKILL.md`（本仓库根目录那份）用另一套：`name / version / description / display_name / allowed-tools / ...`，且恰好 500 行。这两套格式服务对象不同，不要把内嵌技能的 `title/summary/read_when` 抄进独立包，也不要把独立包的 16 个字段抄进内嵌技能。

### 12.3 官方样板自身的两处缺陷（不照抄）

1. `displayName` 写成 `{"en": "琳达", "zh": "Diana"}` —— 中英文值对调了。我方 `plugin.json` 的 `en/zh` 是正确的。
2. `plugin.json` 引用 `avatars/expert.png`，但 zip 内**没有** `avatars/` 目录，头像文件缺失。我方专家包带真实 512×512 PNG，比样板完整。

### 12.4 我方专家包逐项对照（整改后）

| 项 | 官方样板 | 我方 v0.2.272（整改后） | 结论 |
| --- | --- | --- | --- |
| `plugin.json` 键集合 | 16 键 | 16 键，完全一致 | 一致 |
| `author` | `{name, email}` | `{name, email}` | 已补齐 |
| `agents/*.md` frontmatter | `name/description/tools/maxTurns/skills` | 同左 5 键 | 已对齐；删掉与 `plugin.json` 重复的 `displayName`/`profession` |
| `skills/` 内嵌技能 | 有 | `skills/worldstip-travel-planner/`（`SKILL.md` + `references/README.md`） | 已补齐 |
| 内嵌技能 frontmatter | `title/summary/read_when` | 同左 3 键 | 已对齐，未混入独立包字段 |
| `avatars/expert.png` | 引用但缺文件 | 真实存在 228,477 B | 我方更完整 |
| 独立技能包 `SKILL.md` | 不适用（样板只有内嵌技能） | 500 行 + 16 字段，四平台已过审 | **保持原样，未改动** |

### 12.5 已落地整改（2026-11-07）

采用「按样板补全结构，但保持单一真源」的方案：

1. `plugin.json` 补 `author.email`（取 Git 配置的公开 noreply 邮箱）。
2. Agent frontmatter 改为官方 5 键：`tools: [Read, Write, Edit, Glob, Grep, Bash]`（与技能 `allowed-tools` 一致）、`skills: [worldstip-travel-planner]`；删除与 `plugin.json` 重复的展示字段。
3. 新增内嵌技能 `skills/worldstip-travel-planner/SKILL.md`，frontmatter 为 `title/summary/read_when`，**入口型**：只写能力边界、数据口径、工作流程与输出契约，不复制 500 行正文、不复制任何 POI / 价格 / 天气数据，并显式声明版本真源、正文真源、数据真源只有一份。
4. 新增 `skills/worldstip-travel-planner/references/README.md`，说明数据来自完整技能包、本专家包无数据副本、三条红线与静态快照缺口。
5. 修正 Agent 正文一处事实错误：原文写「查本地库」并列出 5 个数据文件名，但专家包独立分发时**不含**这些文件；改为「调用内嵌技能确认口径，数据随完整技能包分发，不可用时降级」。
6. 专家包 README 增补目录结构与「两套 frontmatter 不混用」说明。

**验证**：`tools/verify_backup.py` 从 64 项扩到 **76 项**，新增 12 项专门检查内嵌技能 frontmatter、Agent 的 `tools/skills` 绑定、绑定目标真实存在、`plugin.json` 的 `author.email`、专家 zip 含内嵌技能文件等；全绿 76/76。`doctor.py` 17/17、`tests/run_all.py` 16/16 + 32/32 不受影响（`expert/` 已在三处判据中排除）。专家 zip 由 6 文件变 8 文件、240,764 B，`dist/` 与 `releases/` 字节一致；**四个平台上传包字节未变**（接手资产与专家源码均被构建器排除）。
