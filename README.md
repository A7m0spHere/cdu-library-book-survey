# 成都大学图书馆荐书 Skill

> 一个可复用的 **AI Agent Skill / Skills 工作包**，用于成都大学图书馆馆藏调研、学习路线规划和书籍推荐。

`cdu-library-book-survey` 是一个 **Agent-neutral Skill**，面向成都大学学生的学习规划与馆藏调研。它不是一次性 Prompt，也不是单纯脚本，而是一套可被 Codex、Claude Code、Cursor、Gemini CLI、ChatGPT Skill 或其他 Agent 共同使用的 **Skill 规则、执行流程、脚本和报告模板**。

它的目标不是简单回答“图书馆有哪些书”，而是帮助学生判断：

- 哪些书真正值得借；
- 现在能不能借到；
- 去图书馆哪里找；
- 某个学习方向的馆藏是否足够；
- 是否需要校外购书、电子阅读或向图书馆荐购；
- 每本书对应哪些课程、能力和未来方向。

## 这是什么类型的 Skill

这是一个 **图书馆荐书与学习规划 Skill**。

它让 AI Agent 具备一套稳定的执行能力：

```text
学生需求
↓
学习路线判断
↓
关键词扩展
↓
成都大学 OPAC 馆藏调研
↓
详情页与馆藏位置核验
↓
馆藏书和校外书分离推荐
↓
行动清单
```

它可以作为：

- ChatGPT Skills 风格的 `SKILL.md`；
- Codex / Cursor / Gemini CLI 可读的 `AGENTS.md` 工作规范；
- Claude Code 可读的 `CLAUDE.md`；
- 任意 AI 可复制使用的 `prompt.md`；
- 可独立运行的 OPAC 采集脚本包。

## 适用场景

当用户有以下需求时使用本工作包：

- 查询成都大学图书馆馆藏；
- 按专业、课程、考研、科研、兴趣或职业目标推荐书；
- 比较馆藏书和市面上更优的校外书；
- 获取索书号、馆藏地、可借状态、条码号、图书定位；
- 生成“明天去图书馆该怎么借”的行动清单；
- 分析某个学习方向的馆藏覆盖情况和荐购缺口；
- 把书籍映射到课程、能力和未来职业方向。

## 目录结构

```text
cdu-library-book-survey/
├── README.md
├── AGENTS.md
├── SKILL.md
├── CLAUDE.md
├── prompt.md
├── scripts/
│   └── opac_survey.py
├── cache/
└── references/
    ├── workflow.md
    ├── ranking-rules.md
    ├── keyword-expansion.md
    ├── curriculum-mapping.md
    ├── confidence-rules.md
    ├── reading-cost-rules.md
    ├── gap-analysis.md
    ├── route-templates.md
    ├── capability-mapping.md
    ├── hallucination-prevention.md
    ├── recommendation-rules.md
    └── report-template.md
```

各文件作用：

| 文件 | 作用 |
|---|---|
| `README.md` | 通用说明，任何 Agent 或人类用户先读 |
| `AGENTS.md` | Codex、Cursor、Gemini CLI 等通用执行规范 |
| `SKILL.md` | ChatGPT Skills 风格入口 |
| `CLAUDE.md` | Claude Code 可选入口 |
| `prompt.md` | 纯提示词版本，适合复制到任意 AI |
| `scripts/opac_survey.py` | 独立 Python 采集脚本，输出 JSON/CSV/Markdown |
| `cache/` | 缓存 OPAC 检索结果、馆藏元数据、图书定位信息 |
| `references/` | 平台无关规则、模板、评分标准和路线映射 |

## 前置条件

成都大学 OPAC 可能需要以下网络环境之一：

1. 成都大学校园网；
2. 学校 VPN；
3. 用户手动打开 OPAC 后提供截图、复制文本或导出的结果。

OPAC 地址：

```text
http://libopac.cdu.edu.cn/opac/search_adv.php#/index
```

如果 Agent 无法访问 OPAC，应进入“手动辅助模式”，并在最终报告中标注：

```text
[未实时核验]
```

如果使用缓存结果，应标注：

```text
[缓存数据]
```

## 快速开始

### 方式一：让 Agent 使用

把整个 `cdu-library-book-survey/` 目录提供给 Agent，然后这样提问：

```text
请使用 cdu-library-book-survey 工作包，帮我调研成都大学图书馆馆藏。

我是成都大学药学大二学生，已学普通化学、有机化学、结构化学，
正在学习 Python、RDKit 和化学信息学。
目标方向是 AI 制药、药物设计、QSAR、虚拟筛选和分子对接。

请输出 normal 深度报告：
- 馆藏推荐 Top10
- 学习价值 Top10
- 学习路线映射
- 能力映射
- 馆藏缺口分析
- 校外更优补充推荐
- 明天去图书馆该怎么借
```

Agent 应先读：

1. `README.md`
2. `AGENTS.md`
3. `SKILL.md`
4. `references/workflow.md`
5. 任务相关的其他 `references/*.md`

### 方式二：复制纯提示词

打开 `prompt.md`，把模板复制给任意 AI，并补全专业、年级、目标方向、用途和网络状态。

### 方式三：直接运行 OPAC 采集脚本

创建请求文件 `request.json`：

```json
{
  "profile": {
    "school": "成都大学",
    "major": "药学",
    "stage": "大二",
    "goal": "AI制药",
    "purpose": "课程学习+科研入门",
    "network": "校园网或VPN",
    "output_depth": "normal"
  },
  "keywords": [
    "药物化学",
    "药理学",
    "药物设计学",
    "计算机辅助药物设计",
    "化学信息学",
    "生物信息学",
    "QSAR",
    "人工智能药物研发"
  ],
  "max_results_per_keyword": 50,
  "include_shelf_locations": true,
  "use_cache": true
}
```

运行：

```bash
python3 scripts/opac_survey.py --input request.json --output survey.json --format json
```

也可以输出 CSV 或 Markdown：

```bash
python3 scripts/opac_survey.py --input request.json --output survey.csv --format csv
python3 scripts/opac_survey.py --input request.json --output survey.md --format md
```

脚本负责采集数据；推荐排序、学习路线、能力映射、校外书核验和最终报告，应由 Agent 按 `references/` 中的规则完成。

## 标准工作流

1. **输入完整性检查**  
   判断用户是否提供专业、年级、目标方向、用途、网络状态。信息严重不足时最多问 3 个问题。

2. **网络前置检查**  
   优先校园网；校外可尝试学校 VPN，但不默认 VPN 一定可用。

3. **缓存检查**  
   先查缓存；过期或关键字段缺失时再实时检索。

4. **学习路线建模**  
   从 `references/route-templates.md` 选择或生成路线，如药学本科路线、AI 制药路线、计算机路线、考研路线。

5. **关键词扩展**  
   根据 `references/keyword-expansion.md` 扩展中文、英文、同义词、课程名和技术名。

6. **OPAC 检索与详情核验**  
   按出版日期降序检索，进入详情页核验主题词、摘要、出版信息和馆藏状态。

7. **位置解析**  
   优先输出图书定位页的楼层、区、排、面、列、层；无精确架位时输出馆藏地和索书号。

8. **版本合并与筛选**  
   同一教材多版本只保留最合适正式教材；习题集、实验指导、考试辅导和低相关书不进主推荐。

9. **双 Top10 输出**  
   分离“馆藏推荐 Top10”和“学习价值 Top10”，避免把“馆里有”误当成“最值得学”。

10. **能力映射与缺口分析**  
    把推荐书映射到课程、能力、未来方向，并分析馆藏已覆盖、部分覆盖和明显不足的模块。

11. **质量检查**  
    输出前确认没有把校外书写入馆藏 Top10，没有编造索书号、馆藏地、条码号或可借状态。

12. **行动清单**  
    最后必须告诉用户“明天去图书馆该怎么借”。

## 输出深度

| 模式 | 适用场景 | 输出内容 |
|---|---|---|
| `brief` | 快速借书 | 馆藏 Top10、行动清单 |
| `normal` | 默认 | 馆藏 Top10、学习 Top10、缺口分析、行动清单 |
| `deep` | 完整调研 | 学习路线、课程映射、能力映射、馆藏分析、校外推荐、荐购建议、来源日志 |

## 推荐报告应包含

默认报告模板见 `references/report-template.md`，核心栏目包括：

- 用户需求摘要；
- 学习路线映射；
- 能力映射；
- 馆藏推荐 Top10；
- 学习价值 Top10；
- 最容易马上找到的书；
- 适合馆内查阅的书；
- 校外更优补充推荐；
- 馆藏缺口分析；
- 不推荐借阅；
- 如果只能借/买 5 本；
- 明天去图书馆该怎么借；
- 找书说明；
- Source Log。

## 证据、置信度与防幻觉规则

每本书必须区分：

```text
馆藏事实 ≠ 外部资料 ≠ 人工判断
```

禁止编造：

- 索书号；
- 馆藏地；
- 馆藏数量；
- 条码号；
- 可借状态；
- 图书定位信息；
- 出版社和年份；
- 外部书籍版本信息。

必要标记：

| 情况 | 标记 |
|---|---|
| OPAC 未核验 | `[未核验]` |
| 使用缓存 | `[缓存数据]` |
| 使用外部来源 | `[外部资料]` |
| 模型/人工判断 | `[人工判断]` |
| 无法确认实时状态 | `[未实时核验]` |

推荐置信度：

| 等级 | 含义 |
|---|---|
| A | OPAC 详情页、馆藏状态、位置均已核验 |
| B | OPAC 结果和详情页已核验，但具体架位缺失 |
| C | 外部资料辅助判断，馆藏或版本信息不完整 |
| D | 基于用户目标和概要的推测，必须明确标注 |

## 缓存策略

| 数据类型 | 有效期 |
|---|---:|
| 馆藏元数据 | 30 天 |
| 图书定位信息 | 30 天 |
| 关键词检索结果 | 30 天 |
| 馆藏状态/可借状态 | 3 天 |

优先流程：

```text
缓存
↓
有效期检查
↓
增量核验
↓
更新结果
```

如果无法联网，可以使用缓存结果，但必须明确标注 `[缓存数据]` 和 `[未实时核验]`。

## 手动辅助模式

如果 OPAC 无法自动访问，让用户提供以下任一材料：

- 搜索结果截图；
- 书籍详情页截图；
- 复制出的书目信息；
- 馆藏表文本；
- 图书定位页截图或条码号。

Agent 仍然可以按相同的筛选、排序、证据和报告规则分析，但必须标注未实时核验的部分。

## 校外书推荐规则

校外书不是购物清单。最多推荐 8 本，并且每本必须说明：

- 图书馆未检索到，还是馆藏有相近书但该书更优；
- 补足了馆藏哪一类短板；
- 适合购买、电子阅读，还是向图书馆荐购；
- 推荐依据来自外部出版信息还是人工判断。

即使成都大学图书馆已有相关馆藏，如果市面上有明显更优、更现代、更适合用户目标的书，也可以推荐，但必须说明理由。

## 安全边界

本工作包只处理公开馆藏信息，不处理个人账号数据。

不要：

- 登录用户个人图书馆账号；
- 查询用户借阅记录；
- 代替用户预约、续借、荐购，除非用户明确要求且系统支持；
- 高频访问 OPAC；
- 绕过登录、验证码或访问限制。

## GitHub 发布建议

如果要发布到 GitHub，建议仓库名：

```text
cdu-library-book-survey
```

推荐提交信息：

```text
Add agent-neutral CDU library book survey workflow
```

推荐仓库描述：

```text
Agent-neutral workflow for Chengdu University OPAC book recommendations, learning routes, holdings locations, and collection gap analysis.
```
