# DoD 清单 · v0.2.276 内容安全整改版

> 每条判据都对应本机实跑入口；逐项结论见 `QC_REPORT.md` 第五节。

| # | 判据（可执行断言） | 验证方式 |
|---|---|---|
| D1 | 两个源技能的触发词在合并版 `description` 中保留，且明确写出「不触发」边界 | 融合专项断言 F3 + frontmatter 检查 |
| D2 | 跨省同名地名先列候选、不静默硬判；含县镇锚点时锁定 | 地名抽取专项用例 |
| D3 | 默认紧凑卡册与 `--rich` 九风格增强册都能出真实成品 | 3 份成品案例 + 统一入口用例 |
| D4 | 非出行请求明确拒答；「参数 + 权威地名」的省略句式放行 | 意图闸门正/负向夹具 + 换问法压测 |
| D5 | 离线样例数据可复现，未覆盖数据如实 `found=false`，不编造 | 数据引擎边界套件 |
| D6 | 包内目录层级 ≤ 2，`SKILL.md` 在根，无缓存 / 临时产物夹带 | `python scripts/doctor.py --json` + 外部上传闸门 |
| D7 | frontmatter 必填齐、description 单行 ≤ 200 字、8 个版本文件一致 | doctor 自检 + `VERSION.json` 真源比对 |
| D8 | 统一回归一键入口 EXIT 0，全部套件 PASS | 源码仓库内的一键回归入口 |
| D9 | zip 与源码字节一致、固定时间戳、根含 `SKILL.md` | `python tools/build_pack.py --verify` |
| D10 | 外部上传闸门 0 缺陷（目录与 zip 双形态） | 外部质检器的上传档检查 |
| D11 | 报告中的分数 / 编号 / 退出码全部来自实跑，未实测项显式标注 | `QC_REPORT.md` 第六节 |
| D12 | 默认紧凑册含真实内嵌视觉元素（`<svg>` ≥ 1），且无 `<img>` 占位 / 外部资源 | `QC_REPORT.md` 视觉资产验收节 + 成品计数 |
| D13 | 包内每个脚本都有调用方或可执行文档指令；每份数据都有读取方；文档不点名包内不存在的文件 | `python tools/orphan_scan.py --root <源码/包>` 判 PASS，`tools/selfcheck.py` [E] 维度复算 |
| D14 | 四平台包的差异有台账、且台账与实测包一致；被裁能力有可检测的降级信号 | `python tools/platform_diff.py --check` PASS；缺增强渲染器的包跑 `--rich` 必须 ok=true + `degraded=true` + 非 0 字节 HTML |
| D15 | 默认一次出三件终端成品（PC 网页 / A5 分页小册子 / 手机 HTML5），三件各含独有排版标记且互不串味、字节两两不同 | `tests/test_logic_fixes.py` L14 14 条断言；`--device pc\\|a5\\|mobile` 单选严格只产一件 |
| D16 | 不可信输入（坏路径 / 坏 JSON / 空壳 plan）一律收敛为一行中文诊断 + exit 2，不裸露 traceback、不谎报成功 | `tests/test_logic_fixes.py` L15 16 条；含「合法 plan 仍 exit 0」反向对照与 `AITRIP_DEBUG=1` 调试开关 |
| D17 | 平台简介只讲功能与用户价值：`description_zh`/`description_en`/`summary` 不含脚本文件名、CLI 开关、内部迭代代号；合规检查器本身有反向自证 | `python tools/selfcheck.py` [B] 三项判据；`tests/test_logic_fixes.py` L16 7 条用违规样本证明判据会报错 |

## 与旧版 DoD 的差异

- 旧 D2 的 visa 灰灯契约、旧 D3 的「双路由入口并存」属于 v0.2.x 出境档判据；本版按 `qianwen-first` 档收窄为单包国内档，改由统一入口 `scripts/worldstip.py` 单点编排，故替换为 D2 / D4 的消歧与意图判据。
- 旧 D8 指向的旧打包器、旧 D9 指向的旧 lint 器均不在 v0.2.22 交付包内，已改为实际存在的 `tools/build_pack.py` 与外部上传闸门，避免文档指向幽灵文件。
