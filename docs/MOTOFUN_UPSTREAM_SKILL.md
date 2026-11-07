> **存档说明**：本文是上游组件 `worldstip-moto-fun`（v0.1.3）原始 SKILL.md 的全文存档，仅用于来源追溯与能力对照，**不是可安装技能**。本技能包的版本号见根目录 `SKILL.md` 的前置 `version` 字段；文中 `version: 0.1.3` 属上游组件自身版本线，与本包版本无关。

---
name: worldstip-moto-fun
version: 0.1.3
author: MrdT
agent_created: true
description: "摩托路线×城市消费查询：给定路线/城市，返回骑行详情、途经景点与沿途城市经清洗的高分餐饮、酒店、商圈评级（WorldsTip 两公开只读集）。触发词：摩旅路线吃什么、跑山附近美食、骑行途经城市、环青海湖住宿、骑完去哪逛、城市商圈美食路线、moto 路线、fun 城市档案。不触发：与骑游无关的问答、实时营业或导航。"
description_zh: "摩托路线 × 城市吃喝玩乐一站式查询：给定路线或城市，返回骑行线路详情、途经景点，以及沿途城市的高分美食、酒店与商圈评级，数据来自 WorldsTip 两个公开只读数据集。"
description_en: "Links motorcycle riding routes with city food, lodging and shopping-district data: given a route or city, returns ride details, waypoints, and verified top-rated restaurants, hotels and district grades from two public WorldsTip datasets."
display_name: "WorldsTip 骑游城市通"
display_name_en: "WorldsTip Ride & City Guide"
category: 旅行
allowed-tools: "Read, Bash"
user-invocable: true
disable-model-invocation: false
slug: worldstip-moto-fun
displayName: "WorldsTip 骑游城市通"
summary: "摩托路线×城市消费查询：给定路线/城市，返回骑行详情、途经景点与沿途城市经清洗的高分餐饮、酒店、商圈评级（WorldsTip 两公开只读集）。触发词：摩旅路线吃什么、跑山附近美食、骑行途经城市、环青海湖住宿、骑完去哪逛、城市商圈美食路线、m"
tags: ["旅行", "摩托车", "美食", "城市探索"]
license: MIT
homepage: https://worldstip.com
---

# WorldsTip 骑游城市通

**技能包名**：`worldstip-moto-fun`　|　**版本**：v0.1.3　|　**数据日期**：以数据集自身 `generated` 字段为准（`stats` 命令读取），不在文档里写死

> **一句话定位**：moto 回答「这条路怎么骑」，fun 回答「骑到这座城吃什么、住哪、逛哪」。本技能把两者接成一条链路，并按数据质量口径如实标注哪些能查到、哪些查不到。

## 触发条件

- **触发（用户说这些时调用）**：摩旅路线吃什么、跑山附近美食、骑行途经城市、环青海湖住宿、骑完去哪逛、城市商圈美食路线、moto 路线、fun 城市档案、某城有哪些骑行路线和夜生活。
- **不触发**：与摩托骑行 / 城市吃喝玩乐无关的通用问答；实时营业状态、排队、票价等需现查的信息；导航绘制与路线规划之外的出行安排。

## 工作流

1. **路由**：`python scripts/route.py "用户原话" --json` 判定意图（city / routes / cascade / rank / stats）。
2. **查询**：按意图调 `scripts/motofun.py` 对应动作，全部输出 JSON，退出码即判定。
3. **清洗**：餐饮 / 酒店按 `type` 首段过滤，小吃「仅登记不推荐」剔除，维度双形态统一走 `dim_pois()`。
4. **降级**：城市名归一化 + 分级降级，任何降级在 `match_level` / `note` 显式标注，不静默当精确匹配。
5. **输出**：路线怎么走 + 沿途景点 + 该城吃住逛，紧凑有序，缺失写「未覆盖」不编造。

## 降级设计

| 情况 | 处置 | 退到哪 |
|---|---|---|
| 无网 / 离线 | 加 `--offline` 仅用本地缓存；`--refresh` 与 `--offline` 同用仍只读缓存不联网 | 本地缓存快照 |
| 查无数据 | 返回 `E_DATA_UNAVAILABLE`（EXIT 3），写「fun 库未覆盖此城」 | 如实标注未覆盖 |
| 城市名不匹配 | 分级降级（province→exact→normalized→alias→municipality→同省兜底），`match_level`/`note` 显式标注精度损失 | 降级匹配或列候选 |
| 歧义地名 | 返回候选列表让用户选定，不擅自挑第一个 | 先查后问 |
| 脚本跑不起来 | 测试用 `--data-dir fixtures` 跑通；线上缺 `data-dir` 时提示配置，绝不编造 POI | 受控错误码 EXIT 1/2 |

## 自检

- 边界用例一键验证：`python test/run_all.py`（EXIT 0 = 全部通过）。
- 逐轮执行记录与踩坑见 `growth_log.md`；已沉淀规则见 `references/insights.md`，新会话开工前先读。
- 数据源口径 / 脏数据实测 / 已知缺口见 `references/data-quality.md`。

## ⚡ 执行入口

收到需求先跑路由，按返回的动作链执行：

```bash
python scripts/route.py "用户原话" --json
python scripts/route.py "骑太浮山，中午在常德吃点好的" --fill   # 从原话抽地名填入动作链
python scripts/route.py "全国美食榜" --json                    # rank 意图
```

`--fill` 默认关闭；开启后输出 `places` 并把 `<城市>` 替换成实际地名，其余行为不变。动作链里的 `<关键词>` / `<省拼音>` 仍需从原话抽取——路由只做意图判定，不猜路线名。

直接用查询引擎（7 个动作，全部输出 JSON，退出码即判定）：

```bash
python scripts/motofun.py stats                                   # 两库规模、7 维统计、缓存清单与数据日期
python scripts/motofun.py routes --province hunan --type 攻山压弯 --max 8
python scripts/motofun.py city --name 岳阳市                       # 城市档案（美食 + 酒店 TOP）
python scripts/motofun.py city --name 常德市 --dims malls,xiaocan,leisure,kids --top 3
python scripts/motofun.py city --name 常德市 --detail             # 行政区 / 可信度 / 商圈摘要
python scripts/motofun.py cascade --keyword 太浮山                 # 路线 → 城市档案联动
python scripts/motofun.py cascade --route-id taifushan --province hunan --with-track
python scripts/motofun.py top-cities --n 10                       # 商圈最多城市
python scripts/motofun.py rank --kind food --n 10                 # 全国美食榜（清洗后 785 条）
python scripts/motofun.py rank --kind districts --rank-province 湖南省  # S/A 商圈榜（703 条）
python scripts/motofun.py route --text "骑太浮山，中午在常德吃点好的" --fill
```

**按需开关（全部默认关闭）**：`--dims` 额外维度 / `--top 1..20` 每维条数 / `--detail` 城市摘要 / `--with-track` GCJ-02 轨迹与途经点坐标 / `--refresh` 强制回源 / `--fill` 地名填充。

**离线 / 无网**：加 `--offline` 仅用本地缓存；测试用 `--data-dir fixtures`（夹具为手写规范样本）。无数据时返回 `E_DATA_UNAVAILABLE`（EXIT 3），**禁止编造 POI 名称、评分或地址**。`--refresh` 与 `--offline` 同用时仍只读缓存，不偷偷联网。

## 数据纪律（不可让步）

1. **餐饮必须清洗**：fun 的 `food[]` 实测 31021 条里混入 777 条非餐饮（164 住宿 / 290 购物 / 157 休闲等）。一律经 `is_food()` 按 `type` 首段 == `餐饮服务` 过滤。**未经清洗直接取 `food[0]` 会把「瑞高酒店」当美食推荐**。
2. **酒店也必须清洗**：`hotels[]` 12097 条里 262 条（2.2%）首段是餐饮 / 商务住宅等，如「宏豪浦江一号(陆家嘴店)」是餐饮。必须经 `is_hotel()` 按首段 == `住宿服务` 过滤。
3. **小吃维度的数据自带否决标记**：`xiaocan[]` 的 `sub` 里有 2024 条「评分…超出苍蝇馆常见区间，**仅登记不推荐**」。数据方明确标注不推荐，一律剔除，不得当推荐输出；另有 9726 条「店名小店语义」是分类说明，可保留。
4. **维度有两种真实形态**：`food/xiaocan/malls/specialties/hotels` 是 list；`leisure/kids` 是 `{subcats:[...], list:[...]}` 的 dict。**只认 list 会把全库 33975 条 POI 谎报成 0**；取数统一走 `dim_pois()`，且 `subcats` 是分类统计不是 POI，必须跳过。
5. **POI 去重**：全库 431 条同城同维度同名（223/389 城），按 `(name, addr)` 去重；排序按评分降序、名称升序，保证同输入同输出。
6. **长途环线不冒充实测**：`citySlug=loops` 的跨市环线 `cs=computed`，是算法聚合条目，`city` 字段存的是**省名不是城市**。不得做单城联动，不得称「实测」；答复中须与市区周边短途分开口径。**环线判定只认 `citySlug` 派生的显式信号，不靠城市名与省名做前缀猜测**——真实数据里「北京 / 上海 / 天津 / 吉林」都作为非环线路线的城市名出现过。
7. **城市名归一化 + 分级降级**：moto 用「常德」，fun 用「常德市」。全量实测 386 个 moto 城市名，按真实 `cascade` 路径（391 个 `city × province × is_loop` 三元组）**零未匹配、零歧义**：330 归一 / 2 精确 / 4 别名 / 24 直辖市降级 / 31 省级汇总。`city` 路径（不带省份）336 匹配 / 1 显式歧义 / 49 未覆盖。降级链：`province`（仅 loops）→ `exact` → 基名等价 `normalized` → `alias` → `municipality` → 同省子串兜底 → 如实标注未覆盖。任何降级都要在输出 `match_level` / `note` 里显式说明，**不得静默当作精确匹配**。
8. **歧义先查后问**：出现多个候选城市时返回候选列表让用户选定，不擅自挑第一个。跨省简称（如「海南」可指青海省海南藏族自治州或海南省）不带省份时一律列候选，不静默选一个。
9. **坐标系**：moto 轨迹 `p` 与途经点 `w` 为 GCJ-02（地图服务体系）；配其他 WGS-84 底图需自行转系。`c` 是路线配色 HEX，不是坐标。
10. **数据快照口径**：评分 / 人均为采集时的快照，不是实时价格；答复中不要写成「当前价」。缓存命中即返回，线上数据更新后需显式 `--refresh` 回源。

## 输出契约

- 每个推荐 POI 带上 `name` / `rating` / `avg` / `addr`（另含 `type` / `sub`），按评分降序；能取到 `page` 时附站内链接。
- 路线信息带 `km` / `days` / `type` / `highlights` / `waypoints` / `url`；途景点附 `coord`。
- 数据缺失写「fun 库未覆盖此城」，**不补白、不用通用建议凑数**（不写「可以去当地菜市场」这类泛化模板）。
- 一次答复里同时呈现：路线怎么走 + 沿途景点 + 该城吃住逛，紧凑有序，不留大块空白。

## 子资源

- `@references/api-spec.md` —— 两个数据源的端点、字段、数据结构完整口径。
- `@references/data-quality.md` —— 脏数据实测统计、城市匹配率、降级规则、全维度体检结论与已知缺口。
- `@references/insights.md` —— 已沉淀的可复用规则（每轮自检后反写）。
- `growth_log.md` —— 逐轮执行记录与踩坑；新会话开工前先读它和 insights。
- `scripts/motofun.py` —— 查询引擎；`scripts/route.py` —— 意图路由入口；`scripts/pack.py` —— 可复现打包。
- `test/run_all.py` —— 边界用例一键验证；`离线样例目录/` —— 手写规范夹具（复刻真实双形态结构，非真实数据）。
- `QC_REPORT.md` —— 质检报告与 DoD 核对；`CHANGELOG.md` —— 版本变更。

## 已知限制

- fun 单城档案共 389 城，不覆盖县级市与乡镇；`city` 路径仍有 49 个 moto 城市名无单城档案（多为省名与重庆区县），`cascade` 路径通过省级 / 直辖市 / 别名降级覆盖，全部标注精度损失。
- 两个数据集为静态快照，不含实时营业状态、排队、票价；营业类信息需另行现查。
- 摩托路线轨迹为抽稀 polyline，仅作展示，不用于导航。
- `--fill` 只填 `<城市>`，`<关键词>` / `<省拼音>` 仍需调用方抽取。
- 上传前自检 `skill-quality-audit/audit.py` 本机缺失，D10 未执行；详见 `QC_REPORT.md`。
