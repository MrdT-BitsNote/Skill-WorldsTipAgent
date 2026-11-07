# WorldsTip 旅行规划师 · 专家包

由 **WorldsTip by MrdT** 出品的旅行规划专家。把「想去哪、玩几天」变成一本能直接照着走的 A5 紧凑旅行小册子，坚持用真实数据说话，绝不编造景点、票价或天气。

| 项 | 值 |
| --- | --- |
| 专家包版本 | `1.0.0`（`plugin.json` 内） |
| 对应技能版本 | `worldstip-travel-planner` **v0.2.273**（技能内部版本，见仓库根 `VERSION.json`） |
| 形态 | Agent 型（单个 AI 专家 + 内嵌技能），适配 WorkBuddy 专家目录 |
| 内嵌技能 | `skills/worldstip-travel-planner/`（入口型，用 `title/summary/read_when` 元数据，由 Agent 的 `skills` 字段绑定） |
| 源码位置 | 本仓库 `expert/worldstip-travel-expert/` |
| 可分发压缩包 | 仓库 `releases/worldstip-travel-expert.zip` |

> 专家包版本号与技能版本号是**两条独立版本线**：专家包只在自身结构/`plugin.json` 变化时递增，技能版本由 `VERSION.json` 统一裁决。两者通过上表建立对应关系，避免版本错位。

## 目录结构（对齐 WorkBuddy 官方专家包样板）

```text
worldstip-travel-expert/
├── .codebuddy-plugin/plugin.json            专家包清单（16 字段，含 author.email）
├── agents/worldstip-travel-expert.md       Agent 定义（frontmatter 含 tools / maxTurns / skills）
├── avatars/expert.png                      512×512 真实头像
├── skills/worldstip-travel-planner/        内嵌技能
│   ├── SKILL.md                            入口说明，frontmatter 为 title/summary/read_when
│   └── references/README.md                数据口径与索引说明
└── README.md / LICENSE / ANTI_DISTILL.md
```

**两套 frontmatter 不混用**：专家包内嵌技能用 `title / summary / read_when`；独立平台上传包的技能正文用 `name / version / description / display_name / allowed-tools`。内嵌技能只是**入口**，不复制 500 行技能正文，也不复制 POI / 价格 / 天气数据——版本真源、正文真源、数据真源都只有一份（详见独立技能包 `HANDOFF.md` §12）。

## 核心功能（对应技能 v0.2.273 的四大关切）

1. **怎么去**：城市级交通比选（高铁 / 飞机 / 自驾）+ 每个景点的到达方式（公交 / 打车 / 索道 / 码头），并把景点间路程算进动线，避免来回折返。
2. **必吃 · 必玩**：必吃只给品类 + 为什么值得 + 参考价，**绝不指定具体店**；必玩给出招牌景点与玩法；查不到的城市诚实标「未收录」。
3. **逐日动线**：按人本节奏排每天几点出门、去哪、怎么串，标注当日路程量化（车程 Nh / 跨区 N 次）与体力评级，跨天不重复排同一景点。
4. **季节与安全**：结论绑定出行日期；安全提醒按真实场景给（城市 walk 不列山区提醒），含应急预案，绝不写「注意安全」空话。

## 使用示例

- 「帮我规划长沙 + 岳麓山周末 2 天轻徒步，两人，下周末出发。」
- 「武汉 3 天 city walk，怎么去各个景点、必吃有什么、每天怎么排？」
- 「新疆独库公路 7 天自驾，沿途必玩、住宿节奏、安全预案怎么安排？」

## 头像

头像位于 `avatars/expert.png`（深墨绿 + 米白旅行小册子图标，512×512 PNG，228 KB）。如需替换，要求 PNG/JPG、512×512 px、单张不超过 500 KB。

## 安装

把本目录复制到目标机器的 WorkBuddy 专家市场插件目录，例如：

```text
<用户目录>/.workbuddy/plugins/marketplaces/my-experts/plugins/worldstip-travel-expert/
```

Windows 本机示例路径为 `C:\Users\<用户名>\.workbuddy\plugins\marketplaces\my-experts\plugins\worldstip-travel-expert\`。放入后按目标机器的专家注册流程使其可见；`plugin.json` 的 `agents` / `avatar` 均为包内相对路径，不需要额外改写。

## 版权与反蒸馏

本专家包基于 MIT 许可发布并附加反蒸馏条款，核心 POI 与气候数据受保护，详见包内 `ANTI_DISTILL.md` 与 `LICENSE`。署名须保留「WorldsTip by MrdT」。

## 打包与校验

从仓库根目录执行（固定时间戳、稳定排序，同输入产出字节一致的 zip）：

```bash
python tools/build_expert_pack.py --verify
python tools/verify_backup.py
```

接手说明见仓库根 `HANDOFF.md`（目录地图、四平台包差异、版本线、安全绿网规则、已知缺口）。
