**本包内容**：`SKILL.md`（技能定义）+ `references/`（30+ 份数据参考）+ `scripts/`（数十个纯标准库 Python 脚本）（分发包为控制体积不含 `examples/` 范本，需要时用 `render_compact.py` 现场生成）+ `agents/worldstip-travel-planner.md`（智能体提示词）。

**版本**：v0.1.46　**大小**：见下载卡　**许可**：MIT
## 通用 / 千问 安装方式（任选其一）

1. **千问技能市场（推荐）**：在技能市场搜索 slug `@user_gc9bq/worldstip-travel-planner` 点击「安装」即可，平台自动加载 SKILL.md 前置元数据。
2. **任意支持 SKILL.md 的平台**：解压本包，把整个文件夹放到平台的 `skills/` 目录（或导入 SKILL.md），平台会读取 `---` 包裹的 YAML 前置（name / version / description）。
3. **纯手动挂载**：把 `SKILL.md` 全文作为「系统提示词」，把 `references/` 作为「知识库」挂载，并开启联网用于易变信息核验。

> 千问对 SKILL.md 前置有硬要求：根目录必须有 `SKILL.md`；`name` 为小写连字符唯一标识；`description` 含「输入类型/支持操作/触发关键词/不适用场景」四要素。本包已满足。
