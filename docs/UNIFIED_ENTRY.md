# 统一入口与 v0.2.22 新增机制

## v0.2.22 合并版：一条命令出成品（先读这里）

本版由 A（发布版 v0.2.1）、B（本地版 v0.1.49）、S（v0.2.2 融合源仓库）三方合并而来，
以 S 的规范骨架为基线，接回 B 的九风格渲染与人文史资产，并新增以下机制。
**下文所有旧章节继续有效；本节是入口与优先级说明，冲突时以本节为准。**

### ① 统一入口 `scripts/worldstip.py`（最高优先级）

用户给出一句出行需求时，**先跑统一入口**，不要手工串 4~5 条命令：

```bash
python scripts/worldstip.py "从岳阳出发，周末去张家界爬山看日出，2天1晚，一个人，预算1500" --json
python scripts/worldstip.py "<原话>" --rich --rich-style apple --json   # 九风格增强渲染
python scripts/worldstip.py "<原话>" --feasibility strict --json        # 可执行性体检档
python scripts/worldstip.py "<原话>" --with-weather --json              # 显式开启联网天气
```

一次进程内完成：意图闸门 → 地名抽取/消歧 → `build_itinerary.py` → `plan_transit.py`
→ 〔可选天气〕→ 渲染。产物目录含 `plan.json` / `transit.json` / `小册子.html`
/ `manifest.json`；manifest 逐步记录退出码、耗时、产物字节，**不做静默降级**。

退出码：`0` 成功 / `2` 参数不足 / `3` 非出行请求被拦或跨省地名待选 / `4` 链路失败。

### ② 负向意图闸门 `scripts/intent_guard.py`

旧版把「帮我写一份本周工作总结」误判成 domestic 并生成废册子。本版在路由前
确定性拦截非出行任务与泛化措辞，输出 `verdict=reject` 与去向提示，不生成任何行程。

### ③ 地名抽取与「先查后问」 `scripts/geo_extract.py`

旧版 `route.detect_to()` 只认境外提示词，国内地名一律返回空，必须人工补 `--to`。
本版从 `destinations.json` / `geo_admin.json` / `moto_places.json` 惰性建索引，
区分出发地与目的地。命中 `geo_ambiguous.json` 的跨省同名地名（幕阜山 / 五指山 /
天柱山）时，**列出全部候选与差异维度请用户选定，绝不静默挑一个**；用户给出
县名/镇名锚点时直接锁定。

### ④ 人文史 sidecar 按需加载 `scripts/history_query.py`

`references/places_history.json`（1743 条）单独存放，主数据保持精简。只有明确查
人文时才读取，不进默认上下文。查不到如实 `found=false`。

### ⑤ 版本真源与离线自检 `VERSION.json` / `scripts/doctor.py`

版本号以 `VERSION.json` 为唯一真源，`doctor.py` 逐文件核对，杜绝版本分叉。
交付前跑：`python scripts/doctor.py --json`（任一失败即 EXIT 1）。

### ⑥ 双渲染引擎

默认 `render_compact.py`（紧凑卡册，快且小）；`--rich` 切 `render_booklet.py`
（9 风格 / full-light / md / 离线地图 / 体检档）。两者都支持 `--feasibility`。

### ⑦ 不触发边界

文档写作、周报月报、代码重构、报表、翻译润色、简历、合同、菜谱、诊疗、
泛化的「帮我安排一下」——一律由负向闸门拦下，交回通用能力处理。


---

详细命令与参数见 `scripts/worldstip.py --help`。
