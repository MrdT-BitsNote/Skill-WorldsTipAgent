**本包内容**：`SKILL.md`（技能定义）+ `references/`（40+ 份数据参考）+ `scripts/`（数十个纯标准库 Python 脚本，运行期依赖）+ `docs/`（架构 / 规范 / FAQ / 机制说明）+ `fixtures/`（离线自检夹具）+ `assets/`（logo）。分发包为控制体积，不含回归验证集与维护期构建脚本（仅源码仓库保留），也不含可选的 `moto-places` 扩展数据包（按需另装，见 `docs/RESOURCES.md`）。

**版本**：v0.2.27　**许可**：MIT
> **版本号说明**：本技能**内部开发版本 = 0.2.27**（全包文档统一以此为准）；SkillHub 平台侧 `_meta.json` 的 `version`（如 1.0.0）是平台发布流水号，与内部版本相互单独、不冲突。单一真源为根目录 `VERSION.json`，`scripts/doctor.py` 会逐项核验。

## 适用平台

本包按「首层 `SKILL.md` + 一级子目录」组织，适用于 SkillHub、WorkBuddy、千问 AI 技能 Hub 等读取 `SKILL.md` 的平台。**是否已在某个平台上线，以该平台页面为准**；本文件不代平台作上线状态声明。上传前建议先跑离线自检：

```bash
python scripts/doctor.py --json
```

## 安装方式（任选其一）

1. **平台导入**：解压本包，把整个文件夹放到平台的 `skills/` 目录（或直接导入 zip），平台会读取 `---` 包裹的 YAML 前置（name / version / description）。
2. **纯手动挂载**：把 `SKILL.md` 全文作为「系统提示词」，把 `references/` 作为「知识库」挂载；易变信息（营业时间、票价、天气）需另行核验，本包离线数据不冒充实时数据。
3. **命令行直接使用**：`python scripts/worldstip.py "从岳阳出发，周末去张家界爬山看日出"`，一条命令产出 `plan.json` / `transit.json` / `小册子.html` / `manifest.json`；加 `--rich` 切九风格增强渲染。完整参数见 `docs/UNIFIED_ENTRY.md`。
4. **CLI 发布到 SkillHub**：见根目录 `README.md` 的发布段落（`slug` / `displayName` / `version` / `summary` / `license` 五个前置字段已备齐）。

> `SKILL.md` 前置的通用要求：根目录必须有 `SKILL.md`；`name` 为小写连字符唯一标识且与包名一致；`description` 含「输入类型 / 支持操作 / 触发关键词 / 不适用场景」四要素。本包已满足。
