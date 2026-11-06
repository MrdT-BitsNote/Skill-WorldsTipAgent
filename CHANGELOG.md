# 打包与平台合规 · 版本变更日志

## v0.2.1（2026-11-05）· 逻辑缺陷修正

**性质**：patch 版本（不改能力边界，只修判定错误）。起因是逐入口实跑自检，
静态检查 A/100 全绿但判定逻辑有 9 处错判——这类错只有跑真实输入才暴露。

> 说明：正文里的 `M3` 是内部里程碑标签，与本版本号 `0.2.1` 无关，勿混读。

- **日期被误读成天数**（`route.py·detect_days`）：旧实现 `(\d+)\s*(?:天|日)` 全串匹配，
  「10月3日出发」→ 3 天、「帮我订10月3日的房」→ 3 天。改为「先剥日期 → 抽显式天数 →
  算日期区间跨度 → 中文数字」，单日期不推断天数。`10月3日-10月6日` 现正确得 4 天。
- **人员构成硬编码**（`route.py·build`）：旧版 `composition` 写死「独自一人」，
  与 `--people 2` 互相打脸；未说人数时还默认 1 人。改为按原话特征推断，
  抽不到则按人数给中性描述，并把估算写进 `assumptions` 字段要求用户确认。
- **摩旅路由兜底假阳性**（`motofun.py·cmd_route`）：旧 `else` 分支把任意未命中输入
  兜底成 `routes`，「你好」「帮我写一份周报」全返回摩旅路线命令。改为 `intent=none`
  并提示交回总路由。
- **拉丁短词子串误命中**（`route.py·_kw_hit`）：`adv` 裸子串会命中 advice/advance，
  导致「any advice for Tokyo trip」判成摩旅。改为短 ASCII 词加双侧词边界。
- **自行车被判摩旅**（`route.py·classify` / `motofun.py`）：「环青海湖骑行」因 moto 关键词
  优先级更高被判摩旅；「我骑自行车去重庆」因裸「骑」命中被认成摩旅。改为出现自行车词
  且无摩托强词时让位给 cycling。
- **附加意图反客为主**（`route.py·pick_style`）：主意图带强画像时（moto/rv/roadbook），
  附加意图不得覆盖，「骑摩托车环湖」旧版给出 `--style cycling`，摩旅门禁画像全失效。
- **末班船断言拿错时间**（`feasibility.py·_time_near`）：旧版只找「末班」，
  「末班车 18:00 … 末班船 17:30」会把车的时间当船的时间，报出假 P0 冲突。
  改为只认「末班船/渡轮/轮渡/游船」类词。
- **时刻解析越界**（`feasibility.py·_slot_hour`）：`time="2100"` 会被拼成 2100，
  输出「末段约 2100:00」这种不存在的时刻。改为只认 0–23 的 `HH:MM / HH点` 写法。
- **高反判据是死代码**（`feasibility.py` / `build_itinerary.py`）：旧版读
  `plan["high_altitude"]`，但全仓库从未设置该字段，`altitude_min_days` 永远不触发；
  本地无权威海拔库，改为显式契约：`--altitude <米>`（≥3000 触发）或
  `--high-altitude` 才体检，未传不判，**绝不按地名猜海拔**。

**回归**：27/27 + 204/204 + 38/38 全通过，`run_all_fused` SUITES 5/5；39 个 `.py` 零语法错；
新增 44 条反例断言覆盖上述错判（`tests/test_logic_fixes.py`），每条先写下当年判错的原话。

## v0.2.0（2026-11-05）· 融合版

**性质**：minor 版本（新能力）。把 `worldstip-travel-planner v0.1.49` 与
`worldstip-moto-fun v0.1.3` 合成单一技能包，保留 travel 全部触发词与门禁口径。

- **新增数据层**：`scripts/motofun.py`、`scripts/motofun_route.py`、`fixtures/` 5 个离线夹具、
  `references/api-spec.md` / `data-quality.md` / `insights.md`；摩旅路线与沿途城市餐饮/酒店/商圈查询。
- **冲突消解**：moto 的 `scripts/route.py` 改名 `motofun_route.py`，travel 总路由原名不动；
  moto 的 SKILL/CHANGELOG/QC 全文卸载归档到 `docs/MOTOFUN_*.md`，正文只留索引。
- **版本线清理**：正文 7 处历史 `v0.2.0` 里程碑标签改 `M2`、`v0.2.1` 改 `M3`，
  消除「里程碑编号冒充版本号」的错位；版本线段重写为唯一权威 0.2.0。
- **七法则补齐**：新增「融合数据层」段（触发条件/工作流/输出契约/降级设计/自检五段 +
  信源层级 + 冲突三角显式格式 + 重试 2 次熔断），末尾补 5 条退出自检二元门禁。
- **回归合并**：`tests/run_all_fused.py` 一键跑 27 项行程回归 + 16 项签证专项 +
  202 项数据引擎断言（版本/权限断言按融合口径等价修正）+ 融合专项断言。
- **S7 合规**：剔除全部 `__pycache__`、`releases/`（26MB）、独立包专用 `pack.py`；
  新增固定时间戳打包器 `tools/build_fused_pack.py`。
- **未改**：travel 的四灯门禁、10 章输出契约、触发词与不触发边界、`scripts/route.py` 入口名。


> 本文件由 `SKILL.md` 分层拆分而来（v0.1.35），原始内容未删减。

**v0.1.49 变更（三方合并统一版 · 本地候选，未发布）**

本版把 GitHub `origin/main` v0.1.43 与本地 v0.1.47 两条分叉线合并，两边能力都不丢。

- **回灌上游 v0.1.42/43**：`--mode` 用户明确即遵从、飞机 800km 阈值与配置化消费、民宿档、房车营地营位计费、预算双档、`site_query.py` + `worldstip_sites.json` 自有站点接入、可执行性体检并入 `render_compact.py`、`plan_route.py` 同城阈值同源、11 套上游脚本测试。
- **保留本地 v0.1.47**：签证绿灯绑定 `visa_verified` / `visa_source`、0 距离 falsy 修复、单景点日程分配修复、27 项统一回归、分层 docs、平台包构建器、38 份 references `_meta` 溯源与 `fn/alt` 数据增强。
- **合并决策**：`SKILL.md` 取本地 479 行骨架 + 6 条上游能力索引（491 行，守住 ≤500 行硬约束），远端 967 行原文不随分发包附带（开发仓库保留）。
- **边界**：本地候选副本，未 push、未覆盖 `pkg-check` 与已安装技能；最终以上游仓库与平台审核为准。

**v0.1.47 变更（交通判定修复 + 签证绿灯绑定核验 + 回归套件 + 数据溯源补齐）**

本轮解决三个实质缺陷：① 同城出行的距离为 `0.0`（falsy），被 `if not dist` 误判成「坐标缺失」，
推荐「需确认交通方式」而非「市内交通」；② 签证免签绿灯可仅凭本地历史基线直出，存在误导风险；
③ 技能包无任何自动化回归测试，改动无法验证是否引入回归。

- **① 【交通同类判定修复】**：`scripts/plan_transit.py` 的 `if not dist:` 改为 `if dist is None:`，
  `distance_km` 输出同理改为 `round(dist) if dist is not None else None`。同城（距离 0）正确进入
  「市内交通」分支；坐标真正缺失（`None`）仍走「需确认交通方式」，两者不再混淆。
- **② 【签证绿灯硬门槛】**：`scripts/gate_card.py` 的 `_check_visa()` 要求调用方传入
  `visa_verified=True` 且 `visa_source`（官方页面链接）才允许绿灯；仅凭本地 `visa_rules.json`
  基线一律灰灯并给出「证件类型 × 常住地 × 旅行目的 × 目的地 × 停留期限 × 入境次数 × 入境口岸」
  逐项核对指引。需要签证但未核验时同样降为灰灯（原先直出黄灯）。
- **③ 【回归测试套件】**：新增 `tests/run_tests.py`，27 项断言，独立可跑不依赖 pytest。
  覆盖交通圈层分支、住宿晚数与按房间计价、签证门禁三态、地名消歧与错字召回、数据完整性、
  扩展包降级、端到端产物、打包规范（无绝对路径 / 版本一致 / 纯 LF 无 BOM / 行数上限）。
- **④ 【数据溯源补齐】**：38 个 `references/*.json` 全部带 `_meta._updated` 与 `_meta.source`；
  已有 `built_at` / `verified_at` / `updated_at` 的统一补 `_updated` 别名键。
- **⑤ 【正文精简】**：`SKILL.md` 547 → 499 行。第 1 步问卷表、第 5 步 10 维调研模板、
  `research.json` 的 `ugc` 字段契约上浮至 `docs/WORKFLOW_DETAIL.md`。
- **⑥ 【版本对齐】**：README 由 v0.1.32 同步至 v0.1.47（此前落后 15 版）。

---

---

更早版本（v0.1.45 及以下）的变更记录见开发仓库 Git 历史，分发包为控制解压体积不再附带。
