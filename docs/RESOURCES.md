# 资源清单（references/ 数据资产）

> 本文件由 `SKILL.md` 分层拆分而来（v0.1.35），原始内容未删减。

## 资源清单

**数据（references/）**
- `theme_playbooks.json` — **主题深度玩法路由库（v0.1.17）**：4 个主题（亲子研学 / 摄影旅拍 / 美食朝圣 / 温泉康养）各含 `trigger_words` / `spot_criteria` / `pacing` / `booking` / `gear_focus` / `pitfalls` / `reuses`（指向已有 photography_guide/food_guide/audience_profiles，去重不复制）+ 全局 `routing_rule`（命中即叠加、不改骨架、不改可信度内核）。命中主题触发词时在通用行程上覆盖选点/节奏偏好，多主题以首要意图为主。
- `party_playbooks.json` — **出行陪伴结构玩法库（v0.1.24）**：6 类 Party Type（solo/couple/friends-small/friends-large/family/group），各含 `detect`(关键词) / `room_default`(分房口径) / `budget_mode`(分摊口径) / `safety_focus` / `pacing_focus` / `pitfalls`，加 `resolution_rule`(优先级 group>family>couple>friends>solo) 与 `orthogonality`(与 audience/style/theme 正交)。`build_itinerary.resolve_party_type()` 据此判定、`party_block()` 组装，驱动 stay_plan 分房、预算整团/人均两档口径、安全节奏叠加；`--party` 可显式覆盖。术语与边界裁定见 `CONTEXT.md`。
- `CONTEXT.md` — **领域术语表（v0.1.24）**：四轴正交模型（Party Type/Audience/Style/Theme Playbook）+ 6 类陪伴结构的规范术语、边界判据与消歧裁定（纯词汇表，不含实现）。
- `destinations.json` — **393 个国内目的地**（v0.1.17 从 moto 摩旅线路库城市 center 回灌真实 GCJ-02 坐标，**300 个含经纬度坐标**，其余靠名称检索 + 天气地理编码兜底；覆盖 31 省级行政区与港澳台地区，回灌条目带 `coord_source=moto_route_center` 溯源，绝不编造坐标）。**v0.1.3 起每条可带 `aliases`**（登记 worldstip.com 站点的 SEO 显示名，如「北海 · 涠洲岛」→ 涠洲岛），`search_dest.py` 关键字与主题检索均命中 alias；安徽木梨硔以 `slug=mulihong` 独立入库，与四川木里（`slug=muli`）区分。
- `moto_places.json`（**可选扩展数据包 `moto-places`，主包不内置**）— **景点级地点库（v0.1.41：2514 条 / 32 省级单位 / 41 类）**。每条含 `n`(名称) `admin`(省·市·区县) `t`(类型) `lat/lng`(坐标，**100% 有坐标**) `hi`(亮点，均 79 字) `his`(历史，均 53 字) `src`(来源线路) `st`/`fl`(质量标签)。来源：moto-site-astro 31 省线路途经点归并 + 高德 POI/regeo 核验。与 `destinations.json`（393 城）交集仅 30 条，**独有 2296+ 个城市库没有的景点级地点**。**v0.1.41 修复湖南省 443 点全量丢失**（`is_primary` 陈旧计算，0 → 384 条）。
  - **使用纪律（硬）**：必须经 `scripts/places_query.py` 检索，**严禁全文读入上下文**（1.3MB ≈ 40 万 token）。默认排除 `fl` 非空条目（1996 clean / 518 suspect），需 `--include-suspect` 放行。
  - **降级契约**：文件不存在时脚本退出码 `2` → 退回 `destinations.json` 城市级建议 + 输出挂灰灯，不得静默降级。
  - **安装**：解压 `worldstip-travel-planner-ext-motoplaces-v*.zip` 覆盖到技能根目录（与 `SKILL.md` 同级）。
- `seasons_climate.json` — **六气候区×四季方案**（气温/穿衣/当季看点/风险）— 小册子特色板块数据源
- `safety_playbook.json` — **全交通方式+全场景安全手册**+应急预案模板
- `extreme_sports.json` — **极限玩法库（8 类）+ 自然美景专线（3 族线路+补给应急）**
- `photography_guide.json` — **美景拍摄指南**（星空/日出日落/题材速查/装备）+ 周边美景必查规则
- `packing_checklist.json` — **行前装备清单**（通用/方式专项/季节加项/目的地类型）+ T-7 倒排时间线
- `transit_rules.json` — **交通估算系数**（高铁/普铁/客车/轮船/自驾/飞机 + 市内交通）+ 市内/近郊/跨城三级圈层判定
- `poi.json` — 景点级票务预约数据（条目带来源与核验日期，按需维护）
- `short_trips.json` — 短途灵感库 42 条（区域/季节/主题/天数）
- `restrictions.json` — 房车限高/车牌限行/禁摩经验规则（非实时）
- `moto_rules.json` — **摩旅政策与合规库（v0.1.1）**：31 省高速准入（13 允许 / 17 禁止 / 1 有条件）+ 45 城禁摩限摩（含范围/时段/排量门槛）+ 证件合规链（D/E/F 准驾、年检、异地通检、头盔依据、交强险）+ 续航模型（4 档排量 + 加油站实务）。每条带 `evidence`（statute/practice/third_party 证据等级）与 `stability` 三档，查不到的一律 `unknown`
- `moto_routes.json` — **摩旅线路库（v0.1.1 · v0.1.2 补绿荫维度 · v0.1.13 补里程纪律）**：25 条（近郊跑山 12 / 长途穿越 8 / 环线 5），每条带季节窗口、里程、补给密度、高速依赖度、难度 1-5、caution、**shade 绿荫等级 + shade_note + summer_window（v0.1.2，基于地形性质的定性判断）**、**distance_source（v0.1.13，`editorial_estimate`/`map_measured`）**。`_meta.distance_discipline` 定死里程纪律：**地图服务 direction/driving 实算优先**、估值渲染标「（估）」绝不伪称实算、单日>150km 评估拆2天（近郊往返例外）、路点必须地图服务 place/text 校验存在性否则丢弃（防虚构点/几何塌缩）。只写稳定事实，不写实时路况
- `rv_logistics.json` — **房车/自驾后勤库（v0.1.13）**：限高（净高标准+房车车高区间）、驾照牌照（蓝牌/黄牌/拖挂C6阈值）、补给半径（水85L/人·天、电基础2-3度/开空调8-15度、油耗、LPG）、黑水灰水（容量+排放规则+排污设施稀缺结论）、营地（四类型谱系+费用区间+国标+预约）、路线优化（营地为节点+日行200-350km+6条经典线caution+野营合法性）、应急（12122拖车+极寒防护）、四车型后勤速查（轿车/SUV/MPV/房车）。每块带 `evidence`（statute/practice/third_party）+ `stability`（stable/volatile/unknown），只写区间/节奏/规则，不写具体排污站/营地名称与坐标
- `vehicle_range.json` — **车辆续航与补给规划库（v0.1.16）**：7 类车型（燃油轿车/SUV/MPV、纯电、插混、摩托车、房车）的油箱/电池、油耗/电耗、实际续航、最低储备、补给时间。纯电标称×0.65、插混纯电段×0.70、燃油按油箱÷油耗估算。含高速/国道/山区/无人区加油站与充电桩最大间距、单日安全系数 0.7。与 `moto_rules.json`（摩托续航模型）和 `rv_logistics.json`（房车水/电/排污）互补
- `cold_knowledge.json` / `audience_profiles.json` — 冷知识彩蛋 / 受众画像（男性/女性/家庭/老人）
- `feasibility_check.json` — **可行性体检规则库**：`thresholds`（单日点位/在外时长/海拔适应/长线疲劳）+ `destinations`（已知目的地 P0/P1/P2 强制关卡：预约/末班船/通行证/营业时间/限行/停车/必购项，含三峡已验证事实与大理·洱海·杭州·昆明·丽江·拉萨）+ `gate_keywords` 覆盖检测关键词
- `station_codes.json` — 12306 车站电报码表
- `food_guide.json` — **城市必吃清单**（12 城 / 菜品+理由+参考价+适合时段），写「必吃美食」板块的优先数据源
- `food_book_links.json` — **「必吃美食」省份级延伸阅读外链（v0.1.34）**：`by_province`（省→精准省书，`province_book` 为 null 表示站点暂无该省专书）+ `fallback`（全国通用书，全覆盖兜底）+ `city_to_province`（12 城→省索引）。链接指向同品牌美食电子书站 food.worldstip.com，仅作「想在家复刻」的延伸阅读，不与 food_guide 做字段级融合
- `carbon_factors.json` — **碳足迹因子库**：高铁/飞机/自驾/大巴/普铁 的 gCO2/人·km 与参考人公里价，`_sec_carbon` 双轴对比用
- `weather_contingency.json` — **天气突变 Plan B 替代方向库**：降雨/高温/低温/大风/雾霾 下的室内与替代活动
- `altitude_playbook.json` — **高反应急手册**：分级处置 + 常备药 + 就近就医枢纽
- `lost_items_playbook.json` — **证件与财物遗失应急手册**：身份证/银行卡/手机/钱包护照 的国内挂失冻结补办流程 + 应急热线（v0.0.12）

**规范文档（根目录）**
- `报告生成规范.md` — **v0.1.14 定稿 · 权威报告生成纪律**：固定 10 章节结构（§01-§10）+ 13 项出册前验收清单 + 明确通行方式规则（§02）+ 行前清单卡片化（§08）+ TIP/WARN/NOTE 三色边线 + 零图纯文字 + A5 紧凑卡册版式。所有小册子输出必须严格遵循，与 `排版规范.md` 互为补充。
- `排版规范.md` — **版式标准**：CSS 变量、字号、配色、章节块样式。

**示例（examples/）** — 4 份由 `render_compact.py`（v0.1.14+ 默认渲染器）生成的紧凑卡册成品，外加 4 份 `-light` 精简版（同为 compact 输出，仅去掉交通比选；文件名用 ASCII 以避免跨平台 zip 编码乱码）；另有 1 份 **内容质量标杆** `example-yueyang-sunrise-reference.html`（**非本引擎产物**，外部「旅游攻略搭子」生成，仅用于校准输出标准，不参与渲染器回归）。**每次改动渲染器 `HTML_TPL` 后必须重建这 8 份引擎样例**，否则会出现「文档说新版、样例还是旧版」的错位：

| 文件 | 场景 | 看点 |
|---|---|---|
| `example-wuhan-citywalk-2d.html` | 闺蜜武汉 2 日 Citywalk | 过早最佳时段、省博预约规则、地铁沿线选住宿 |
| `example-changsha-hiking-weekend.html` | 长沙本地人周末早爬山 | 5 座山横向对比 + 两套可执行半日方案 |
| `example-harbin-sanya-5d.html` | 哈尔滨→三亚 5 天 4 晚 | 直飞/中转/铁路对比、最低 ¥2,450 拆解、4 条省钱杠杆 |
| `example-hangzhou-xinjiang-drive.html` | 杭州→新疆自驾（增程 1,200km） | 20 天 10,500km 分段、通行费与能源费、独库公路限时规则 |
| `example-yueyang-sunrise-reference.html` | **内容质量标杆（非引擎产物）** 岳阳楼区→金鹗山看日出 | 结论先行、4 山横向对比、**门禁时间 vs 日出时刻的矛盾判定**、逐条来源标注、"以景区当日公示为准" |

> **标杆的纪律价值**：上面 4 份引擎样例是「渲染器产物」，这份是「内容质量标尺」。生成同类近郊/日出/当天来回案例时，必须达到它的四条标准——① 开篇直接给结论与首选理由；② 同类候选做横向对比表（距离/海拔/开放时间/能否赶上）；③ 主动暴露门禁与时刻的冲突并给出两种处理，不静默跳过；④ 每条数据标来源与查询日期，价格与政策标注"以当日为准"。**（v0.1.29 逻辑修复）引擎此前会把「市内/近郊 1 天」误判为跨省长线并推荐高铁飞机，现已修复**：`plan_transit.py` 增加市内圈（≤30km，只推公交/地铁/出租/网约车）与近郊圈（30-150km，优先自驾/班车，高铁仅通高铁且≥50km才列）判定，坐标缺失不再默认高铁而是提示先确认「市内 or 跨城」；`render_compact.py` 同步去掉了「400-700km 跨省推荐高铁飞机」的硬编码。生成同类案例时无需再人工纠偏。

**脚本（scripts/）**

| 脚本 | 用途 |
|---|---|
| `render_compact.py` | **小册子渲染器（v0.1.14 主输出 · A5 紧凑卡册）**：默认风格，零图、零大留白、字段密集；10 章节固定结构（§ 01-§ 10）；TIP/WARN/NOTE 三色边线小贴士；内置 `transit/budget/gear/safety/cold` 五大数据流适配；英文版同模板切换 |
| `render_booklet.py` | **小册子渲染器（v0.1.13 及之前 · Apple 风备选）**：保留作为旧版备选——支持 `--variant light` 紧凑版、`--format md` Markdown 导出、`--style` 9 套视觉风格、`--map` 路线地图层（none/offline，合规离线）、`--compute` 实算插件（map）、`--feasibility` 可行性体检门禁（none/advisory/strict）；内置 SVG 图标、预算环形图、体力曲线、动线图、弹性评分、可执行性体检（P0 关卡+末班船时间一致性断言）。**v0.1.14 起不再为默认**，仅当用户明确要 Apple 风大留白版时调用 |
| `build_itinerary.py` | 行程编排引擎（21 式节奏+住宿+预算+装备+限行/房车补给）；**v0.1.1 起 moto 画像自动附加摩旅五项门禁与线路候选** |
| `moto_check.py` | **摩旅五项门禁校验（v0.1.1 · v0.1.2 扩充）**：准驾车型 / 头盔 / 逐省高速准入 / 逐城禁摩 / 续航加油半径；含线路推荐 `suggest_routes()`（支持 `shade_min`/`shade_first` 绿荫优先）与门禁卡渲染 `moto_html()`；`check_range()` 输出加油决策点动作序列（v0.1.2） |
| `moto_enrich.py` | **摩旅数据增强通道（v0.1.2）**：`build_checklist()` 按行程生成出行前待核实清单（政策/补给/路况/天气四类，按证据等级定必查或复核）+ `ingest_note()`/`validate_notes()` 规定检索笔记落地格式（四项必填、拒未来日期、超 30 天告警、evidence 恒 third_party）+ `enrichment_html()` 渲染。合规：只检索公开信息，不批量抓取 |
| `rv_check.py` | **房车/自驾后勤五项自检（v0.1.13）**：驾照牌照（唯一可判红灯：黄牌持C1/拖挂无C6=违法上路）/ 限高（可规避→黄灯，绝不红）/ 补给半径（水撑不过行程或开空调→黄灯，给补水充电节奏）/ 黑水灰水（房车默认黄灯提醒排污稀缺，已确认排污→绿灯，非房车→灰灯不适用）/ 营地过夜（未订→黄灯）。`rv_card()` 汇总 + `rv_html()` 渲染（含车型后勤速查+路线优化+经典线路+应急），与 gate_card/moto_card 同构同视觉。车型由用户 `--vehicle-type` 声明，**不做车型推荐** |
| `plan_transit.py` | **交通比选（市内/近郊/跨城三级分流）**：市内圈（≤30km，只推公交/地铁/出租/网约车）、近郊圈（30-150km，优先自驾/班车，高铁仅通高铁且≥50km才列）、跨城（六方式比选）；坐标缺失不默认高铁，提示先确认「市内 or 跨城」 |
| `check_weather.py` / `fetch_weather.py` | 户外天气预检（四档）/ 实时天气（fetch_weather 已接入 `live_api`，天气服务优先·Open-Meteo 兜底） |
| `live_api.py` | **真实 API 统一接入层（v0.1.0）**：地图服务(MAP_CFG) 距离/驾车路径、天气服务(WEATHER_CFG) 7天预报、Open-Meteo(免授权) 兜底；环境变量驱动、失败回落 None |
| `plan_context.py` | 季节感知+电车油车规划 |
| `search_dest.py` | 目的地关键字与主题检索（攻略与票务以宿主 WebSearch 公开检索为准，不抓取平台内容） |
| `guide_list.py` | **攻略检索清单校验器（v0.1.27）**：把宿主检索结果整理成 JSON 喂入，负责 URL 合法性校验（禁手拼/禁票务域名/禁交易路径——攻略模式唯一可点击外链的合规闸门）、按 URL 归一化去重、按 match→confidence→日期排序、>30/90 天时效告警、渲染 Markdown 清单；`--strict` 有拒绝即退出码 1 |
| `guide_digest.py` | **攻略研读沉淀校验器（v0.1.28）**：把攻略研读结论（fact/category/source/source_type/verified_on/confidence）校验合并为 `research.json` 的 `ugc` 条目——三元组缺一即拒（灰灯不进册）、fact>160 字拒（防照搬原文）、同事实多独立来源自动合并升级「多源印证」、日期拒未来、category→kind 映射兼容既有 ugc 结构；`--merge research.json` 去重合并写回、`--strict` 有拒绝退出码 1 |
| `suggest_trip.py` / `render_suggestion.py` | 短途灵感推荐+华丽 HTML（想不到去哪时） |
| `plan_route.py` | 距离方位顺序 / 多目的地排序（票价一律估算，见文字指引） |
| `transit_links.py` | **交通查询文字指引（v0.1.17 · 合规改判）**：用 station_codes.json(3404站) 解析城市→站名→电报码，输出「请到 12306 官方渠道 / 航司官方渠道查询」品牌中性文字提示。**不生成任何可点击外链、不做站外引流、不点名具体商业平台**（旧版曾生成第三方 OTA 深链，因平台合规已整体移除）。`--json`/`--html` 输出；`render_html()` 生成无超链接的查询指引卡片嵌入小册子 |
| `profile.py` | **跨会话偏好档案**（六维度 recall/remember/reset，落 `~/.aitrip/profile.json`） |
| `refloader.py` | **共享 reference 加载器（v0.1.3）**：统一 `references/` 目录解析与 JSON 读取语义（`load(name, default=)` / `path()` / `ref_dir()`），消除各脚本重复的 `json.load(open(...))`。**刻意不做跨调用缓存**——每次返回全新对象，避免调用方就地修改污染后续读取；缺文件/损坏按 `default` 兜底（默认 `{}`，传 `default=None` 则返回 `None`），绝不抛异常打断主流程。已被 geo_lookup / outbound_constraints / outbound_safety / moto_check / geo_disambiguate / build_itinerary / check_weather / plan_route / search_dest 复用 |
| `volatile_verify.py` | **易变数据自动核验（v0.1.17）**：扫描 references/*.json 中所有 `_stability:volatile`/`volatile:true`/`vol_note` 标记及 stability.json 定义的 volatile 字段名，检查 `_updated` 日期戳是否超过 30 天阈值。`--strict` 有过期退出码 1、`--json` 机器可读、`--file` 单文件、`--fix` 自动刷新日期戳。跳过 stability.json 字典本身 |
| `enrich_coords.py` / `verify_coords.py` | 坐标补全（并发≤4）/ 反查自检 |
| `reflect.py` | **复盘回写**（准确度/安全/预算/舒适/内容 1-5★，落 `~/.aitrip/feedback.json`） |
| `places_query.py` | **景点级地点检索（v0.1.41 · 配套可选扩展包 `moto-places`）**：按 `--province / --admin / --type / --kw` 过滤 `references/moto_places.json`，默认回 8 条、`hi` 截断 120 字——**数据不进上下文，只进结果**。默认排除质量问题条目（`fl` 非空），`--include-suspect` 放行；`--list-provinces` / `--list-types` / `--json` / `--full-hi` / `--with-his`。退出码契约：`0` 有结果 / `1` 无匹配 / **`2` 扩展数据未安装**（上层退回城市级建议并挂灰灯）。须先 `cd` 到技能根目录（相对路径取数） |
| `sync_check.py` | **数据同步校验（v0.1.3）**：把 live 站点 worldstip.com 的目的地清单与 `destinations.json` 按 **slug** 联表，报出「冲突 / 显示名漂移 / 站点独有 / 技能独有」，防止 muli 类静默错误。纯比较逻辑 `compare()` 与联网 I/O 分离；`--live` 联网拉取、`--site-file` 离线比对、`--strict` 有未登记问题退出码 1、`--json` 机器可读。已知且经确认的差异登记进 `KNOWN` 白名单（europe/georgia 出境页、shishou 出发地、muli 站点归属待修），报为「已知」而非「错误」 |


**质量标准**：成品应达到 `examples/` 中 4 份示例的密度——每个时间节点有具体地点名、每条美食有参考价、每行预算有两档、每条提示能直接执行。达不到就重做，不要交付「又多又空」的版本。

