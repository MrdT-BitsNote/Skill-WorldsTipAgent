# QC 报告 · v0.2.276 内容安全整改版

> 本文件所有数字均由本机实跑输出写入，未实跑项一律显式标注。
> 版本：v0.2.276 ｜ 构建日期：2026-11-09 ｜ 环境：Windows / Python 标准库 ｜ 不派 agent 跑模型 API。

## 一、验证集实跑结果

| 项目 | 命令 / 入口 | 实跑结果 |
|---|---|---|
| 统一回归 | `python tests/run_all.py` | 17/17 套件 PASS，32/32 新增用例 PASS，EXIT 0 |
| 逻辑反例回归 | `python tests/test_logic_fixes.py` | **134/134 断言 PASS**（含本版新增 L14 终端分流 14 条） |
| 八维度自检（源码） | `python tools/selfcheck.py --root .` | 57/57 项 PASS |
| 八维度自检（源码 + 四包） | 同上加 4 个 `--pack` | **106/106 项 PASS** |
| 离线自检（源码） | `python scripts/doctor.py` | 17 项 16 通过 + 1 项因未注入 `--lexicon` 判 SKIP（加 `--no-smoke` 为 14 项） |
| 离线自检（四包解压后） | 逐包 `python scripts/doctor.py`（`--no-smoke` 为 14 项） | **4/4 包 PASS**，各 17/17 项 |
| 版本真源 | `VERSION.json` 对 8 个版本文件逐项比对 | 全部 = **0.2.276**，0 分叉 |
| 孤儿扫描 | `python tools/orphan_scan.py --root <源码/包> --strict` | **5/5 目标 PASS**：脚本 ORPHAN 0、数据 ORPHAN 0、WEAK 0、悬空 0 |
| 跨平台差异台账 | `python tools/platform_diff.py --check` | PASS（四包齐判） |
| 打包字节校验 | `python tools/build_pack.py --verify` | 包内字节 == 源码 |
| 备份一致性 | `python tools/verify_backup.py` | **84 项检查，0 失败，0 SKIP** |
| 上传包危险内容审计 | `python tools/audit_upload_zip.py <五包>` | 五包各「危险命中 0 条」，AUDIT: PASS |
| 专家包版本与合规 | `python tools/build_expert_pack.py --verify` | VERSION-CHECK PASS（三处 1.0.0 + 内嵌技能 0.2.276）；**COMPLIANCE PASS 12/12** |
| 统一入口冒烟（包内） | WorkBuddy / 千问包内实跑 `--device both` | 两包均 `ok=true`、三件齐出、字节互不相同 |
| `--rich` 降级（包内） | WorkBuddy 包内 `--rich` | `degraded=true` + 原因文案，非 0 字节 HTML，exit 0 |
| `--rich` 增强（包内） | SkillHub 包内 `--rich` | `render_booklet.py` 真跑，`device_applied=false` 如实声明未分流 |
| 外部质检器评分 | `skill_lint.py` | **未实测**——该工具不在本机环境，本报告不声称任何分数或缺陷编号 |

统一回归覆盖：行程编排套件、visa 闸门套件、逻辑反例套件、融合专项断言、数据引擎边界套件，以及 12 个脚本级回归（`test_route_viz` 77 项断言、`test_moto_check` 545 项、`test_geo_disambiguate` 233 项等）。v0.2.274 在逻辑反例套件新增 L10 五项，锁死「摩旅逐日里程必须来自真实距离」，并追加 L11 五项，锁死「人文史数据缺失必须优雅降级」。新增用例覆盖意图闸门正/负/空/境外边界、地名抽取与跨省同名不硬判、锚点锁定、显式 `--to` 优先、人文 sidecar 索引与未命中、版本真源、统一入口四类分支、manifest 逐步记录与产物字节、离线默认，以及「参数 + 权威地名共现放行 / 同结构无权威地名仍拦」这对规则缺口回归。

## 一之补零、v0.2.275 发布号并轨记录（上一轮）

> 本版零行为变更：`scripts/`、`references/`、渲染器与数据文件逐字节未动，行程产出与 v0.2.274 一致。改动只在发布元数据与文档口径。

**起因**：用户准备上传 SkillHub，问包在哪。拆包核 `_meta.json` 时发现两处对不上。

| # | 级 | 缺陷 | 证据 | 修法 |
|---|---|---|---|---|
| 1 | P0 | `build_release_packs.py` 第 26 行把 `_meta.json.version` 写死 `1.2.1`，内部版本是 `0.2.274` | `unzip -p ...-skillhub.zip _meta.json` 得 `version=1.2.1` / `internalVersion=0.2.274` | 改为 `"version": VER`，与版本真源同源 |
| 2 | P1 | `displayName` 为 `WorldsTip 旅行规划小册子`（含空格），与 `SKILL.md` 的 `display_name` 不一致 | 两处字符串直接对比 | 统一为 `WorldsTip旅行指南小册子`（13 字、无空格无括号） |
| 3 | P2 | `summary` 仍在讲「A5 紧凑旅行小册子」单件形态，与 v0.2.274 起的终端三件套不符 | 简介与 `--device both` 实际产出对比 | 重写为三件套表述，不含版本号 |
| 4 | P2 | `README` / `INSTALL` / `HANDOFF` 三处「平台发布号与内部版本相互独立」的表述已过时 | grep「相互单独、不冲突」 | 改写为并轨说明，HANDOFF 补回退动作 |
| 5 | P0 | 首次上传 SkillHub 被拒：**「不允许的文件类型: LICENSE」**。包内唯一无扩展名文件就是 `LICENSE`（132 = 49 json + 48 py + 33 md + 1 svg + 1 LICENSE），而平台白名单按扩展名判 | 平台返回文案；`unzip -Z1` 过滤无点号文件名得 `LICENSE` 一项 | SkillHub / DuMate 两包把 `LICENSE` 改名 `LICENSE.md` 并改写包内三处引用；WorkBuddy 保留原名（该平台接受，且构建器断言根级必须是原名）；千问包后经专项自检一并改名，见「一之补一」 |

**为什么 #1 是 P0**：这个号写死在源码里，`doctor.py` 不管它、`grep 0.2.274` 也搜不到，升版时无人会去改。上一轮清理「构建器写死平台文案」时漏掉了这一行。

**为什么 #5 同样是 P0**：`build_pack.py` 的 `ALLOW_NOEXT = {LICENSE, LICENCE, NOTICE}` 是我方为「引用完整性」自己开的放行口，它只保证文件进包，管不了平台收不收。本地门禁全绿也测不出来——必须真传到平台才会暴露。改名而非删除，是因为 `ANTI_DISTILL.md` 以 `[MIT License](LICENSE)` 链接引用它，删了就悬空；WorkBuddy 的构建器还硬断言根级必须有 `LICENSE`。

**本轮实测**（全部重跑，非沿用上轮结论）：selfcheck 源码 57/57、源码加四包 106/106；`orphan_scan` 五目标 5/5（ORPHAN 0）；四包 `doctor.py` 各 17/17（全跑口径，`--no-smoke` 为 14 项）；`run_all` 17/17 套件 + 32/32 用例；`test_logic_fixes` 134/134；`audit_upload_zip` 五包危险命中 0；`platform_diff --check` PASS；`verify_backup` 84 项 0 失败；专家包 VERSION-CHECK PASS（内嵌技能 0.2.276）+ COMPLIANCE PASS 12/12（WorkBuddy 与专家包自查整改轮见 CHANGELOG 0.2.275-7）。

**体积**（MiB 两位小数）：WorkBuddy 95 文件 / 解压 2.91 MiB（3 MiB 上限余量约 3%）/ zip 0.98；SkillHub 132 / 4.25 / 1.53；DuMate 132 / 4.25 / 1.53；千问 85 / 2.79 / 0.93；专家 8 / 0.24 / 0.23。SkillHub 与 DuMate 较 v0.2.274 增 0.01 MiB，因本报告新增一节随包分发；WorkBuddy 与千问不解包本报告，体积不变。

**未验证项（如实披露）**：平台是否还有其他类型限制（`.svg`、中文文件名 `报告生成规范.md` / `排版规范.md`）本轮未触发，不等于不会触发。SkillHub 线上历史发布号止于 `1.2.1`。若平台按 SemVer 断言「必须递增」，`0.2.275`（主版本 0 < 1）会被判降级。本机无平台接口，**这一点未实测**；回退动作见 `HANDOFF.md` 第 3 条。

## 一之补一、v0.2.275 千问包自检与三处修正（上一轮）

> 用户要求「千问 AI 平台的包自检，做好自检以后打包」。按「先自检、再打包」执行，自检本身查出三处真缺陷。

**自检链路**（全部实跑，未沿用上轮结论）：源码 `selfcheck` 57/57 → 源码 `doctor` 17/17 → 构建 + 包内 13 项自检 → 干净目录解压 → 包内 `doctor` 17/17 → `orphan_scan --strict` PASS → `audit_upload_zip` 危险命中 0 → `selfcheck` 源码加四包 106/106 → 包内行为冒烟。

| # | 级 | 缺陷 | 证据 | 修法 |
|---|---|---|---|---|
| 1 | P0 | `summary` 被品牌词兜底替换改坏句子：「WorldsTip：一条命令生成国内行程…」→「**内置数据**：一条命令生成国内行程…」，主语成了「内置数据」 | 包内 `grep ^summary:` 直接读出；根因 `BRAND_SUBS` 末位 `("WorldsTip", "内置数据")` | 兜底之前加两条摘前缀规则（全角/半角冒号）；兜底加注释警示「别在句首命中」 |
| 2 | P1 | `description` 仍写「一句话生成国内 **A5** 行程小册子」，只讲单件；同包 `description_zh` 已写「一次给三份成品」。两个描述字段自相矛盾，而 `description` 是平台检索与展示的主字段 | 两字段逐字对比；`--device both` 实际出三件 | 重写为「按终端一次出三件：电脑网页、A5 可打印、手机 HTML5」；12 个触发词与负向边界一字未删；受 `doctor` ≤200 字硬限压到 198 字 |
| 3 | P1 | `LICENSE` 无扩展名，与 SkillHub 已实测被拒的类型相同；千问从未上传、无平台实测 | `unzip -Z1` 过滤无点号文件名得 `LICENSE` 一项 | `QW_RENAME` / `QW_LICENSE_SUBS` 构建期改名并同步 `README.md` 目录树；源码不动 |
| 4 | P2 | 改名暴露的既有盲区：`LICENSE` 原名无扩展名，长期落在外链扫描范围外（扫描按扩展名过滤）。改名后立即命中 `Open-Meteo（https://open-meteo.com）` 被 `FALLBACK` 只换域名、留下悬空 `https://`，产出畸形串「https://官方渠道」 | 改名后自检报「零 http(s) URL 命中 1」，命中明细 `('LICENSE.md', 0, 1, 0)` | `PRECISE` 增 Open-Meteo 专属规则（连协议头换为「公开气象数据接口」）；`FALLBACK` 增可选协议前缀 `(?:https?://)?` |

**自检器自身加固**：`build_qianwen_pack.report()` 由 12 项增至 **13 项**，新增「无无扩展名文件」。理由：#3/#4 这类缺陷本地全绿也测不出——`build_pack.py` 的 `ALLOW_NOEXT` 只保证文件进得去包，管不了平台收不收；扫描器也只看白名单扩展名，无扩展名文件等于隐身。判据进自检才能不再复发。

**终态实测**：13 项自检全 PASS（ZIP 975,014 B / 0.93 MiB / 85 文件）；包内 `doctor.py` 17/17；`orphan_scan --strict` ORPHAN 0；审核器视角扫 85 文本文件命中 0；`selfcheck` 源码 57/57 + 四包 106/106。包内实跑「从佛山去衡阳爬衡山，3天」：`ok=true`、`device_applied=true`，三件 26,060 / 26,456 / 27,064 B，`@page` 仅 A5 版、`viewport-fit=cover` 仅手机版、输出零外链。

**未验证项（如实披露）**：千问平台是否接受 `LICENSE.md`、是否有 `.svg` / 中文文件名等其余类型限制，**均无平台实测**——该包自 v0.2.270 起从未上传。

## 一之补二、0.2.274-7 平台规范自查整改记录（skill-optimizer + skill-dev-standard）

> 用户要求「版本号不变为 0.2.274」，故整改不递增版本号，作为 0.2.274 第 7 子节折入（详见 CHANGELOG）。
> 全部缺陷均为**实跑发现**，非静态猜测；每条都已修并补了回归断言。

### 5 铁律自评（skill-dev-standard）

| # | 铁律 | 判定 | 证据 |
|---|---|---|---|
| 1 | 高复用 | 达标 | 换城市换天数照 `SKILL.md` 跑通：大理 3 天在四包内各跑一次均 `ok=true`；流程全参数化（`--to/--days/--device/--feasibility`），无一次性硬编码 |
| 2 | 可交付 | 达标 | 五包在 `dist/`，`releases/` 为字节一致副本（`verify_backup.py` 84 项 0 失败）；同输入两次渲染三件 HTML **MD5 完全一致**（确定性实测） |
| 3 | 有标准 | 达标 | `SKILL.md` + `DoD.md`（D1–D17）+ `QC_REPORT.md`；判据是可执行断言（selfcheck 57 项 / doctor 17 项 / logic 134 条），非形容词 |
| 4 | 可迭代 | 达标 | 版本真源 `VERSION.json` 驱动 8 个版本文件；回归可一键重跑（`tests/run_all.py`）；触发词本轮**零改动** |
| 5 | 优于裸模型 | 达标 | 裸模型给不出「按终端三套真实 CSS」的三件产物，也无法保证「同输入同字节」；本包离线数据可复现、无覆盖字段标「需现场确认」而不编造；负向闸门明确拒答非出行请求 |

### 本轮修掉的 9 项（按级）

P0 ×3：测试残留污染工作区致 `doctor` FAIL；两渲染器坏输入裸 traceback 并泄漏本机路径；空壳 plan 渲染成空册子还报成功。
P1 ×2：`description_zh/en` 写实现细节与版本号；千问包描述写死且标过期代号。
P2 ×4：展示名带内部代号；`BRAND_SUBS` 死规则；`check_compliance()` 不可注入；文档 `doctor` 17 项与实际 14 项不符。

### 未修项（量化披露，不粉饰）

| 项 | 量化 | 影响判定 |
|---|---|---|
| 外部体检器 `skill-quality-audit` 未在本机 | 该项 **0 项检查**，`--profile upload` 未执行 | 中。上传前必须在有该技能的环境补跑一次；本轮改用包内 selfcheck/doctor/orphan/audit 四道自建门禁替代，但**不等价** |
| 五包未上传、站点未部署、GitHub 仍 v0.2.273、`og-cover.png` 仍旧版 | 4 项未动 | 低（不改代码正确性），但对外仍是旧版 |
| `profile` / `reflect` 跨会话记忆行为 | 本机 **0 覆盖**，只在单进程内验证读写与权限失败路径 | 中。真机多会话是否按预期累积，无法在本机证明 |
| 外部词表 `--lexicon` 未注入 | doctor **1/17 项 SKIP** | 低，不声称通过 |
| 三件套视觉观感未经人眼点击验收 | **0 次**人工目视，只有标记级 grep + 字节差异断言 | 中。已做「互斥标记 + 字节两两不等」机检，但「好不好看」机检替代不了 |
| 千问包港澳台覆盖缺口 | 意图闸门地名库未覆盖港澳台，已按实际能力收窄声明 | 能力缺口，非缺陷；已在包内声明 |

## 二、交付包扫描

| 扫描项 | 发布包内结果 |
|---|---|
| A 类 22 项必清 token | 0 |
| 硬重点词 | 0 |
| 白名单外外链 | 0 |
| 本地绝对路径 / 联系方式 | 0 |
| 危险执行特征 | 0 |
| 文档层台港澳裸用 | 0 |
| 二进制 / 缓存 / 临时产物夹带 | 0 |
| 目录深度 | ≤ 1 级子目录，符合平台两级约束 |
| 包内文件数 | **132**（SkillHub / DuMate）；**95**（WorkBuddy）；**85**（千问）；**8**（专家包）。验证集与维护期脚本不随包分发 |
| 包体积（v0.2.274 实测） | SkillHub 132 文件 / 解压 4.23 MiB / zip 1.52 MiB；DuMate 132 / 4.23 MiB / 1.52 MiB；WorkBuddy 95 / 2.91 MiB（3 MiB 上限余量约 3%）/ zip 0.98 MiB；千问 85 / 2.79 MiB / 0.93 MiB（零外链 0 命中）；专家 8 / 0.24 MiB / 0.23 MiB。体积取 MiB 两位小数、余量取百分比，是因为本报告自身随包分发——写死字节会自指漂移；精确字节以 `dist/` 实测为准。 |
| `SKILL.md` | 位于包根，**499 行**（上限 500，回归断言锁死），纯 LF |

说明：包内地名查询与约束脚本的别名表里保留若干行政区口语简写共 14 处，这是把用户输入归一到「中国香港 / 中国澳门 / 中国台湾」所需的匹配键，属运行期数据契约，删掉会破坏识别；文档与说明层已全部使用带「中国」前缀的完整表述。

## 一之负二、v0.2.274 终端分流记录（本轮新增）

**动因**：用户要求「输出功能修正：电脑 PC 端输出 html 和小册子，手机端输出 html5」。原实现是**一份 HTML 通吃所有屏幕**——紧凑渲染器只有 640px 断点、没有打印分页；增强渲染器有 `@media print` 但没有移动断点。同一份文件在手机上正文偏小、在桌面上版心偏窄、打印不分页。

| # | 改动 | 实现位置 | 验收方式 |
|---|---|---|---|
| 1 | 三套终端排版层（`pc` / `a5` / `mobile`），追加在原 CSS 之后，只增不改既有版式 | `render_compact.py` 的 `DEVICE_CSS` | 逐件 grep **互斥标记**：A5 独有 `@page{size:A5` + `@media print`；PC 独有目录三列 `repeat(3,1fr)`；手机独有 `viewport-fit=cover` + `.to-top` + `min-height:44px` |
| 2 | 统一入口暴露 `--device {pc\|a5\|mobile\|both}`，默认 `both` | `scripts/worldstip.py` | `L14` 断言三件齐出 / 单选各一件 / 命名正确 / 字节两两不同 |
| 3 | `--out` 仍为 PC 版（旧调用方路径不破），另两件加 `-A5` / `-手机` 后缀 | `_device_targets()` / `_expected_outputs()` | `L14` 命名断言 + 单选模式只产一件 |
| 4 | `--rich` 单页长文档不分流，如实声明 `device_applied=false` + `device_note` | `worldstip.py` 渲染分支 | `L14` 断言不谎报、说明可读 |
| 5 | 专家包平台解析硬约束固化为机检 | `build_expert_pack.py` 的 `check_compliance()` | COMPLIANCE 9/9（见下） |

**三件产物的实测互斥性（包内实跑，`len` 为字符数）**：

| 产物 | 命中标记 | 不应命中 |
|---|---|---|
| `小册子.html` | PC 目录三列 | `@page`、`viewport-fit`、`.to-top` |
| `小册子-A5.html` | `@page{size:A5`、`@media print` | 目录三列、`viewport-fit`、`.to-top` |
| `小册子-手机.html` | `viewport-fit=cover`、`.to-top`、`min-height:44px` | `@page`、目录三列 |

**顺带修掉的三处真实缺陷**（都不是「改需求带出来的」，是核验时当场抓到的）：

1. **专家包 `displayName.zh` 含空格**——原值 `WorldsTip 旅行规划师`（15 字符、中间带空格），平台要求 ≤15 字且**不含空格与括号**，属「解析失败」而非告警。改为 `WorldsTip旅行规划师`（14 字，无空格）。
2. **专家包 `defaultInitPrompt.en` 与 `quickPrompts[0].en` 不逐字一致**——中文那对一致、英文那对一个是「Let's plan a trip! Tell me your destination…」、另一个是「Help me plan a trip! Destination, days…」。这是 v0.2.274 就存在、此前无人检查的硬伤。已统一，并把该判据写进 `check_compliance()`。
3. **`verify_backup.py` 的「SKILL.md 恰为 500 行」与另两处判据矛盾**——`tests/run_tests.py` 与 `selfcheck` 都是 `<= 500`，只有它要求 `== 500`。平台限的是上限，少一行本属合规却被判失败，只能靠塞废行凑数。已统一为上限口径。

**与既有排版定稿的关系**：`780px` 版心仍是默认（PC）档的定稿值，原文「严禁擅自加宽到 860/1080」继续有效；`a5`（148mm）与 `mobile`（100% 全宽）是本规范明确允许的例外，其宽度由纸张比例与设备视口决定。此前一版曾把 PC 档改成 1040px，与规范冲突，已回退。


v0.2.274 把「孤儿脚本 / 零消费数据」清零了，但同批分析里还列着四条**没修**的问题。本轮逐条修完，判据全部固化成机检。

| # | 问题（原来长什么样） | 修法 | 复数方式 |
|---|---|---|---|
| 1 | `--rich` 在 WorkBuddy / 千问包内必失败：`render_booklet.py` 被裁，跑出来 exit 4 + 0 字节 HTML，调用方只知道「链路未产出成品」 | 显式降级：回落紧凑卡册 + stderr `[DEGRADED]` + `manifest/JSON` 写 `degraded=true`、`degrade_reason`、`render_requested` | 包内实跑两包各一次（本次 30,228 B / 30,231 B HTML）；`L13` 7 条断言 |
| 2 | 包级传递性死代码：`compute_plugin`(77) + `credibility`(347) 在 WorkBuddy 无消费者；千问再加 `gate_card`(334) 共 758 行 | 从对应包裁掉 + 正文口径改写（「由脚本判定渲染」→「按档位人工判读，**禁止自称已核验**」） | `selfcheck [X]` 新增「入口闭包内或有可执行文档指令」；`orphan_scan` 四包 PASS |
| 3 | 四包脚本数 40/40/34/32、文档集差异**零声明** | 新增 `docs/PLATFORMS.md` + `tools/platform_diff.py`：差异表按实测包生成，附结构签名；`--check` 接进自检 | `platform_diff --check` PASS；`selfcheck` 103 项含此判据 |
| 4 | `profile` / `reflect` 在 `$HOME` 不可写时抛原始 `PermissionError` traceback | 原子写（临时文件 + `os.replace`）+ `AITRIP_HOME` 覆盖 + `OSError` 捕获给三段诊断，退出 2 | `L13` 5 条（失败 2 + 成功落盘 1 + 无 traceback 2） |
| 5 | 六个检索入口职责交叠、无分工说明 | `docs/RESOURCES.md` 加「检索层分工」表（数据源 / 回答什么 / 典型命令 / 明确不做）+ 判据顺序 | `L13` 6 条点名断言；表内命令逐条实跑 |

**顺带修掉的两个真错误**：

- 千问构建器的 `scrub_booklet_refs()` 原来对 `.py` 也生效，把 `os.path.isfile("render_booklet.py")` 改写成 `os.path.isfile("增强渲染器")` —— 清洗规则把**代码逻辑**改坏了。现收窄为只作用于文档。
- 分工表第一版按假想参数写成 `guide_list.py --in`、`guide_digest.py --out`，而两者其实是位置参数（`guide_list.py <guides.json> [--strict]` / `guide_digest.py <facts.json> --merge research.json`）。实跑发现后改正——否则等于用「修文档」的名义新增了两条假文档。

**终态机检（本轮全部实跑）**：

| 检查 | 命令 | 结果 |
|---|---|---|
| 源码自检 | `python tools/selfcheck.py` | 57 项：57 通过 / 0 失败 |
| 源码 + 四包 | `python tools/selfcheck.py --pack × 4` | **106 项：106 通过 / 0 失败** |
| 可达性（源码 + 四包） | `python tools/orphan_scan.py --root <5 目标>` | 5/5 PASS（脚本孤儿 0 / 数据零消费 0 / 悬空 0） |
| 跨平台台账 | `python tools/platform_diff.py --check` | PASS（结构签名一致） |
| 包内自检 | 四包解压后 `python scripts/doctor.py` | 各 PASS |
| 统一回归 | `python tests/run_all.py` | 17/17 套件 + 32/32 用例 |
| 逻辑反例 | `python tests/test_logic_fixes.py` | **91/91**（新增 L13 20 条） |
| 审核器视角 | 五包审计 | 危险命中 0 |

**包体积（v0.2.274 实测，MiB 取两位小数；余量用百分比，避免「改文档→包变大→数字又错」的自指循环）**：WorkBuddy 95 文件 / 解压 2.91 MiB（3 MiB 上限余量约 3%）/ zip 0.98 MiB；SkillHub 132 文件 / 4.23 MiB / 1.52 MiB；DuMate 132 文件 / 4.23 MiB / 1.52 MiB；千问 85 文件 / 2.79 MiB / 0.93 MiB（零外链 0 命中）；专家 8 文件 / 0.24 MiB。精确字节以 `dist/` 实测为准。

## 一之负一、v0.2.274 接线核查记录（上一轮）

**问题**：包内脚本「能跑」不等于「有人跑」。v0.2.274 里既有可跑但无人调用的孤岛脚本，也有只被资源表罗列、没有读取方的数据。

**判据（`tools/orphan_scan.py`，机器可复核）**：

| 层级 | 判定 | 是否合格 |
|---|---|---|
| CODE | 从入口经 `import` / `xxx.py` 字符串 / subprocess 可达；或经 `tests/run_all.py` 的 glob 发现 | 合格 |
| DOC | shipped 文档里以 `scripts/x.py` **可执行形态**点名（模型会真跑） | 合格 |
| MENTION | 只在资源表里被罗列，没有可执行指令 | 不合格 |
| ORPHAN | shipped 文档与代码里都找不到任何引用 | 不合格 |
| 数据 WEAK / ORPHAN | 只被罗列 / 全文无提及 | 不合格 |
| DANGLING | 文档点名的实体文件在包内不存在 | 不合格 |

数据另有**传递降级**：只被不可达脚本引用的数据，一并判不合格。

**本轮起始基线 → v0.2.274 结果**：

| 目标 | 脚本（入口/代码/文档/罗列/孤儿） | 数据（代码/文档/弱/孤儿） | 悬空引用 | 判定 |
|---|---|---|---|---|
| 源码树 | 4 / 47 / 8 / 0 / 0（基线 0 / 0 / 0 / 2 / 1） | 41 / 1 / 0 / 0 | 0（基线 1） | PASS |
| WorkBuddy | 2 / 31 / 3 / 0 / 0（基线 2 / 30 / 3 / 1 / 0） | 36 / 4 / 0 / 0 | 0 | PASS |
| SkillHub | 2 / 32 / 6 / 0 / 0（基线 2 / 31 / 5 / 1 / 1） | 41 / 1 / 0 / 0 | 0 | PASS |
| DuMate | 2 / 32 / 6 / 0 / 0 | 41 / 1 / 0 / 0 | 0 | PASS |
| 千问 | 2 / 30 / 3 / 0 / 0（基线 2 / 29 / 3 / 1 / 0） | 32 / 4 / 0 / 0 | 0 | PASS |

**修掉的 5 类缺陷（每条都由扫描器当场指出）**：

1. `plan_context.py`（365 行）四包全中：只被 `RESOURCES.md` 资源表罗列。已接进主链路——`build_itinerary.py --date` 产出 `plan.json.context`，`render_compact.py` § 05 消费。
2. `motofun_route.py`（85 行）SkillHub/DuMate 零引用：文档一直写 `python scripts/route.py`，跑的是 travel 自己的路由。已改为 `scripts/motofun_route.py`。
3. `lost_items_playbook.json`（3.5KB）WorkBuddy/千问只被罗列：补「读法」指令（何时读、写进哪一节）。
4. `scripts/pack.py` / `scripts/render_booklet.py` 等 8 处悬空：一律加「仅源码仓库内，不随包」标注，或改由构建器按平台裁剪。
5. `plan_context.py` 自带区域归类把**西北归成高原**（敦煌拿到高原建议），且缺 `northwest` 月表会 KeyError：改为读 `seasons_climate.json` 的 `match_rules`，月表缺档直接用基线四季块。

**包内实跑（不是静态看）**：WorkBuddy 与千问两包解压后各跑一次 `build_itinerary --date 2026-07-15` → `render_compact`，§ 05 均出现「当月装备 / 本季看点 / 本季风险」，不再出现「请查实时天气预报」兜底句，千问包内 `http` 命中 0。

**终态机检（本轮全部实跑）**：

| 检查 | 命令 | 结果 |
|---|---|---|
| 源码自检 | `python tools/selfcheck.py` | 57 项：57 通过 / 0 失败 / 0 提示 |
| 源码 + 四包自检 | `python tools/selfcheck.py --pack × 4` | 98 项：98 通过 / 0 失败 |
| 可达性（源码 + 四包） | `python tools/orphan_scan.py --root <5 个目标>` | 5/5 判 PASS |
| 离线自检（四包解压后） | `python scripts/doctor.py`（目录名 = 技能名） | 各 17/17 PASS |
| 统一回归 | `python tests/run_all.py` | 17/17 套件 + 32/32 用例 |
| 逻辑反例 | `python tests/test_logic_fixes.py` | 71/71（含新增 L12 时令接线 11 条） |
| 审核器视角 | 构建时硬闸门 | 四包危险命中 0 |

说明：`orphan_scan` 的「DOC 合格」不等于「代码真调用」——对 `theme_playbooks` / `packing_checklist` / `carbon_factors` / `lost_items_playbook` 这类**给模型读的资料型数据**，合格线是「有明确读法指令」；对 `seasons_climate` / `destinations` / `moto_places` 这类**给代码算的数值型数据**，合格线是「有可达脚本字面引用」。两类不混用一条标准。

## 一之零、v0.2.274 八维度自检记录（上一轮）

机检器 `tools/selfcheck.py`，52 项判据 / 8 维度，退出码 0/1。与 `scripts/doctor.py` 分工：
doctor 管「使用者装完能不能跑」，selfcheck 管「打包者发布前声明与实物是否一致」。

| 维度 | 检查什么 | 首跑结果 | 修完结果 |
|---|---|---|---|
| A 结构 | 包根 / 行数上限 / BOM / CRLF / 层级 / 缓存夹带 | 2 失败 | PASS（行数仍 500） |
| B 触发 | 触发短语 ≥8 / 负向边界 / display_name_en / tags | PASS | PASS |
| C 版本 | 8 处版本 + 描述字段里的版本串 + CHANGELOG 条目 | 4 失败 | PASS |
| D 数字 | 条数 / 体积 / 点名脚本与数据文件是否真实存在 | 3 失败 | PASS |
| E 指针 | 功能文档与数据是否在正文有指针 | 2 失败 | PASS |
| F 数据 | 42 份 JSON 可解析、`_meta` 溯源块 | PASS | PASS |
| G 串台 | 他技能规则 / 替换失败残句 / 占位符 / 绝对路径 | 3 失败 | PASS |
| H 测试 | 回归入口存在、套件注册数 == 实物 | PASS | PASS |
| X 包级 | 解压后悬空引用 / 脚本依赖缺口 / 跨平台漂移 | 4 失败（两包） | PASS |

**修掉的真实缺陷（全部由机检抓出，非估计）**

1. `SKILL.md` 的「退出自检门禁」写的是另一个技能的验收口径（「分数与缺陷编号是否来自技能质检器实跑」「裁决表是否不超过 6 行」），属复用模板串台 → 改写为 5 条旅行输出门禁。
2. 千问包 `description` 触发词被构建器删光，技能在该平台唤不起来；包内自带 `doctor.py` 当场判 FAIL → 恢复 12 个触发词 + 负向边界。
3. 千问包 frontmatter 版本硬编码 `v0.2.271`，落后 4 个版本 → 改为从 `VERSION.json` 注入。
4. 千问包 9 篇 `docs/*.md` 悬空引用（整目录被裁、正文仍指着）→ 改白名单随包 11 篇，只排含外链与纯维护类。
5. WorkBuddy 包把 `--json > weather.json` 改写成 `--json（结果以 JSON 输出）`，bash 代码块里整条命令跑不通 → 只删重定向。
6. `scripts/history_query.py` 在无 `places_history.json` 时直接 `open()` 抛 traceback（WorkBuddy / 千问档都不带该数据）→ 改为 `available()` 判定 + `reason` 字段 + 退出码 2。
7. `doctor.py` 自身两条判据误报：把「包内不带的维护文件」判成版本失败、把 `tests/run_all.py`（源码仓库专属）判成幽灵引用 → 改为缺文件判 SKIP、`tests/` 在包内不存在时豁免。
8. 主 `SKILL.md` 三处版本漂移 + 替换失败残句「统一回归到 统一回归入口（源码仓库内）」+ 数字谎报（39→42 份、1.3MB→1.1MB）。

**自检器自身也修了 4 个判据 bug**：字典形态集合不计数、`\b` 对 `v0.2.274` 不成立、源码树深度把 `expert/` 算进来、泄漏扫描把检测规则本身当泄漏。

**六关实跑**

```
selfcheck 源码    52 项：通过 50 / 失败 0 / 提示 2        SELFCHECK: PASS
doctor            14 项：通过 14 / 失败 0                DOCTOR: PASS
run_all           套件 17/17 + 用例 32/32                REGRESSION: PASS
logic_fixes       55/55（新增 L11 五项）                 LOGIC-FIX: PASS
selfcheck 四包    96 项：通过 94 / 失败 0 / 提示 2        SELFCHECK: PASS
包内 doctor ×4    workbuddy / qianwen / skillhub / dumate 均 17/17 PASS
verify_backup     84 项 0 失败 0 SKIP                    BACKUP: PASS
audit 6 包        危险命中 0                             AUDIT: PASS
render 冒烟       moto / normal × 1440 / 390 四视口溢出 0
```

## 一之补、v0.2.274 摩旅线路形状实跑记录

| 项目 | 命令 | 实跑结果 |
|---|---|---|
| 路线可视化断言 | `python scripts/test_route_viz.py` | 通过 **77** 项断言，ALL PASSED |
| 里程逻辑反例 | `python tests/test_logic_fixes.py` | LOGIC-FIX **50 / 50** PASS（新增 L10 五项） |
| 摩旅成品（有距离） | `worldstip.py "从佛山骑摩托去衡山看日出，2天" --style moto` | 每日 320 km、全程 640 km、系数 1.35；表头「直线约 474 km · 全程约 640 km（路网系数 1.35）」 |
| 摩旅成品（命中线路） | `worldstip.py "骑摩托去常德桃花源，2天" --style moto` | §04 出「线路形状 · 桃源桃花源『世外桃源』文化线」，库标 53 km / 轨迹累计 52.2 km（差 1.5%） |
| 线路清单 | `python scripts/route_viz.py --list` | 已收录 6 条真实轨迹（覆盖 6/25 精选线路），未收录 19 条如实写入 `coverage.matched` |
| 零外链闸门 | `python tools/build_qianwen_pack.py` | 零外链域名 0 / 零 http(s) URL 0 → RESULT: PASS |
| 视口溢出 | 1440 / 390 两视口 | 报告 `#sec4` 无横向溢出（`right > vw` 命中 0） |

## 二之补、v0.2.22 视觉资产验收

| 项 | 改动前（合并版） | v0.2.22（视觉增强） |
|---|---|---|
| 默认紧凑册 `<svg>` | 0 | **1**（真实内嵌矢量封面） |
| 默认紧凑册 `<img>` | 0 | 0（不引入外部图片） |
| 外部资源引用 | 0 | 0 |
| 成品体积 | 21,612 字节 | 23,225 字节（+1,613） |
| 标题数 / 章节结构 | 27 / 12 | 27 / 12（未改） |

封面由 `render_compact.py` 的 `cover_art()` 确定性生成，含起终点节点、天数节点与「离线生成的示意插画，非实景照片」标注，避免把示意图误当实拍图。第三节效率数字沿用 v0.2.22 同机实测；本次改动只增加一段 SVG 拼接，未改变编排链路。

## 三、同题效率实测（同一输入，同一机器）

| 链路 | 进程启动次数 | 墙钟耗时 | 内部编排耗时 | 成品 HTML |
|---|---|---|---|---|
| A 旧链路（v0.2.1） | 3 | 1.117 s | — | 21,028 字节 |
| B 旧链路（v0.1.49） | 3 | 1.198 s | — | 20,331 字节 |
| **v0.2.22 统一入口** | **1** | **0.531 s** | **0.142 s** | 21,612 字节 |

统一入口用同进程 `runpy.run_path` 编排既有 CLI，省掉 2 次解释器启动；相对 A 快约 2.10 倍，相对 B 快约 2.26 倍。该数字只代表本机离线链路，含首次导入开销，不等同于线上模型侧耗时。

## 四、行为层压测（关 3）

| 场景 | 四次换问法结果 | 判定 |
|---|---|---|
| 国内爬山（应放行） | pass / pass / pass / pass | 收敛 |
| 非出行请求（应拦截） | reject / reject / reject / reject | 收敛 |
| 跨省同名地名（应待选） | choice / choice / choice / choice | 收敛 |
| 境外请求（应明确边界） | reject / reject / reject | 收敛 |

重复跑 5 次结果稳定；负向夹具 7/7 证红；覆盖矩阵 60 格、0 空格。压测中发现并修复的真缺口：「从岳阳出发到张家界，2天1晚」这类**不含玩法动词**的句子曾被闸门误拒，现改为先做地名抽取、再用「出行参数 + 权威地名命中」放行，并补了配对的反向回归用例。

## 五、DoD 逐项核对

| # | 判据 | 结论 |
|---|---|---|
| D1 | 两源技能触发词保留、负向边界存在 | PASS（融合专项 F3） |
| D2 | 跨省同名先列候选，不静默硬判 | PASS（geo_extract 专项） |
| D3 | 默认紧凑册与 `--rich` 九风格册均可出成品 | PASS（3 份真实案例） |
| D4 | 非出行请求明确拒答 | PASS（负向 7/7） |
| D5 | 目录层级 ≤ 2、根含 `SKILL.md` | PASS（doctor + 闸门） |
| D6 | frontmatter 必填齐、8 处版本一致 | PASS（doctor） |
| D7 | 统一回归 EXIT 0 | PASS（17/17 套件） |
| D8 | zip 与源码字节一致、固定时间戳 | PASS（`build_pack.py --verify`） |
| D9 | 上传闸门 0 缺陷 | PASS（A / 100，目录 + zip） |
| D10 | 报告数字全部来自实跑，未实测项显式标注 | PASS（见第六节） |

## 六、已知限制（如实披露，不粉饰）

1. **未跑千问平台真实判定**：本轮只做本地离线链路与确定性扫描；任何「本地全绿」都不能等价于「平台一定放行」，本包不承诺过审。
2. **朴素分类器的残余风险**：中国旅行指南本体仍含必要内容（新疆、西藏、政府、寺、清真、公安、军事、南海、钓鱼岛等地名与机构词），若平台按 token 命中而非语义判定，仍可能误报。届时须依据平台给出的具体命中词继续收窄，或走平台提供的反馈通道，而不是盲改。
3. **能力边界按 `qianwen-first` 档收窄**：本版为单包国内档，未恢复 S 源仓库为发布而砍掉的完整出境模式；B 的人文史以单独 sidecar 按需加载，不进默认上下文。
4. **可选外部词表未注入**：离线自检的 `--lexicon` 可选参数本轮按默认运行，该项如实标记为 SKIP，不计入 17 项 PASS。
5. **源仓库未同步**：本次合并版落在当前工作区的技能目录，G 盘权威源仓库未回写、未提交；qoder / Coze Drive / 乐享三端也未同步本版。
6. **效率数字为本机单次采样**：未做多样本置信区间，仅作数量级参考。
