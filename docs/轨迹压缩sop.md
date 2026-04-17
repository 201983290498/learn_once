# 轨迹压缩 SOP

核心思路：**SOP 不应该是对轨迹的线性"总结"，而是对轨迹的结构化解剖 + 选择性压缩**。因为对于 RAG 复用而言，最有价值的不是"做完了什么"，而是"怎么从走偏走到正确轨道的"。

## 第一步：轨迹结构解析（Structure Parse）

从简化后的 jsonl 中提取出 **有结构的步骤序列**，而非原文阅读。

```
输入：locate_session.py 输出的 simplified jsonl
输出：List[TrajectoryStep]
```

每个 `TrajectoryStep` 需要分类标注：

| 字段             | 说明                                       |
| -------------- | ---------------------------------------- |
| `step_index`   | 步骤序号                                     |
| `turn_type`    | 见下方 5 类                                  |
| `user_intent`  | 用户这一轮在干什么（一句话）                           |
| `agent_action` | agent 这一轮做了什么（调了什么 tool/skill）           |
| `outcome`      | success / failure / partial / correction |
| `key_artifact` | 这一轮产出的关键信息（如"发现了 X 文件不存在"）               |

`turn_type` 五类：

| 类型               | 含义                  | 复用价值           |
| ---------------- | ------------------- | -------------- |
| **progress**     | 正常推进，步骤有效           | 中（构成路径骨架）      |
| **correction**   | 用户纠偏 / agent 自纠     | **极高**（经验核心）   |
| **exploration**  | 探索性尝试（未知对错）         | 低-中（除非后来被证明错误） |
| **noise**        | 闲聊、重复调用、无信息量工具调用    | 无（应删除）         |
| **verification** | 确认某件事做对了（测试通过、命令成功） | 高（完成信号）        |

## 第二步：任务类型判定（Pattern Classify）

在分类完每个 step 之后，先判断这条轨迹属于哪种交互模式——因为不同模式的精炼策略完全不同：

```python
if correction_steps > 0 and correction_steps / total_steps > 0.15:
    pattern = "complex_correction"  # 复杂任务纠偏
else:
    pattern = "simple_progressive"  # 简单问题递进
```

这个判定的意义在于决定后续精炼的侧重：

- **纠偏模式** → 重点保留"为什么走错" + "怎么纠正"，成功路径可以压缩
- **递进模式** → 重点保留"任务如何逐步扩展"的完整链条，因为递进本身就是经验

## 第三步：精炼压缩（Refine & Compress）

这是 SOP 最核心的步骤。精炼不是"删短的留长的"，而是基于以下规则：

### 保留规则（KEEP）

1. 所有 `correction` 类型的 step（无论成功还是失败的纠偏）
2. 所有 `verification` 类型的 step（确认做对了的标志）
3. `progress` 类型中的 **关键路径节点**（即：换了 tool/skill、产生了新文件/命令、改变了策略）
4. 递进模式中，任务范围发生"质的扩展"的转折点（从"开 lint"到"改风格"的那个 jump）

### 压缩规则（COMPRESS）

1. 连续的同类型 `progress` step（比如连续 5 轮都在读文件找位置）→ 合并为 1 步："探索 X 模块，定位到 Y 文件"
2. `exploration` 中最终被证明无效且没有其他教学价值的 → 删除
3. agent 的 thinking block 中有大量反复试错推理的 → 只保留"判断依据"，不保留推理过程

### 删除规则（DROP）

1. 纯闲聊、工具调用返回空结果或相同结果
2. 重复调用同一个 tool 且参数没变化
3. 与 `confirmed_task_description` 明确无关的旁支话题

## 第四步：经验提取（Experience Extract）

精炼后的步骤序列还不是最终产物。需要从精炼轨迹中提取出 **可复用的经验结构**：

```yaml
# 对每个 correction 步骤，提取：
mistake_pattern:
  what_went_wrong: "选错了 skill，用了 X 而不是 Y"
  why_it_happened: "因为 X 和 Y 名字/功能描述相似"
  how_fixed: "用户指出应使用 Y，agent 切换"
  generalizable_rule: "当需要 Z 能力时，应优先选择 Y 而非 X，因为..."

# 对整条轨迹，提取：
decision_chain:
  - step_id: S3
    decision: "选择使用 locate_session.py 而非直接读取"
    rationale: "因为会话文件太大，需要先定位"

completion_signal:
  - type: "tool_result"
    indicator: "git status 显示变更符合预期"
```

## 第五步：输出轨迹文件（Format Output）

### 字段来源说明

在生成最终输出之前，逐一说明每个字段如何从精炼轨迹中推导出来。每个字段的定义必须与 `docs/trajectory-format-mvp.md` 保持一致。

#### 2.1 Frontmatter 字段（元数据层）

**`trajectory_id`**

- **MVP 定义**：轨迹唯一 ID，稳定，不随文件名变更。
- **来源**：精炼后的 `task` 字段 + 首次出现该任务的日期。
- **生成方式**：将 `task`（或 `confirmed_task_description`）中的核心名词提取出来，转为小写下划线格式，加上 `v1` 后缀。例如 `"把本地 docx/pptx 上传到飞书，并在知识库里创建归档文档记录链接"` → `feishu_wiki_upload_archive_v1`。如果同一任务后续有新版本，递增版本号（`v2`, `v3`）。**不要使用 session\_id**，因为 session\_id 每次运行都不同，无法保证稳定性。

**`task`**

- **MVP 定义**：用户要解决的问题（一句话）。
- **来源**：优先使用用户传入的 `confirmed_task_description`；如未提供，则取原始轨迹中第一条用户消息的意图摘要。
- **生成方式**：直接使用 `confirmed_task_description`，不做改写或压缩。如果从原始轨迹推导，需要整合前三轮对话中用户表达的核心需求，用一句话概括"用户想要完成什么"。保持原意完整，不要为了简洁而丢失关键信息（如"在知识库里创建归档文档"这种具体操作不能省略）。

**`when_to_use`**

- **MVP 定义**：列表，描述"哪些问题适用此轨迹"。会并入 `index_text` 用于检索，也可额外生成聚合场景向量。
- **来源**：精炼轨迹中的 turn\_type 分布 + correction step 的场景上下文 + 文件变更涉及的系统/模块。
- **生成方式**：
  1. **纠偏模式**：遍历所有 `correction` 类型的 step，提取每个纠偏事件中"用户在解决什么具体问题"。例如用户在纠偏"用错 skill 上传 pptx"，则提取"需要区分 docx(import) 与 pptx(upload) 的正确上传方式"。将同类纠偏场景合并为一条。
  2. **递进模式**：识别任务范围发生质变的关键转折点，每个转折点生成一条适用场景。例如从"查询单个文档"扩展到"批量导出所有文档并生成索引"，则生成两条：一条对应单文档场景，一条对应批量场景。
  3. 每条用完整句子描述，而非短语。句式参考 MVP 示例："需要把本地文件归档到飞书知识库，并产出可访问链接清单"。
  4. 至少生成 1 条，最多 5 条。超过 5 条时合并语义相近的条目。

**`tags`**

- **MVP 定义**：列表，领域/系统/工具大类标签，用于过滤。
- **来源**：精炼轨迹中调用的 skill/tool 名 + 涉及的文件类型 + 涉及的系统模块。
- **生成方式**：
  1. 从精炼后的步骤序列中提取所有 `agent_action` 里调用的 skill 名称（如 `lark-wiki`, `lark-drive`, `lark-doc`），去重后加入 tags。
  2. 从文件变更中提取涉及的文件类型后缀（如 `.docx`, `.pptx`, `.pdf`），加入 tags。
  3. 从用户提问和 `confirmed_task_description` 中提取涉及的系统模块名（如 `feishu`, `wiki`, `drive`），加入 tags。
  4. 所有 tags 去重、排序，确保不重复。参考 MVP 示例：`["feishu", "wiki", "drive", "docx", "pptx"]`。
  5. tags 用于 embedding 检索时的向量过滤，因此要保持语义粒度一致——优先用系统/工具/领域名，不用动作描述（如用 `"wiki"` 而非 `"列出知识库"`）。

**`trigger_keywords`**

- **MVP 定义**：列表，关键词兜底检索，用于 grep/FTS（全文搜索）。
- **来源**：用户原始提问中的关键短语 + 轨迹中用户反复强调/纠正的概念。
- **生成方式**：
  1. 从用户第一条消息和 `confirmed_task_description` 中提取具体的操作短语和实体名。例如"上传docx"、"上传pptx"、"飞书知识库"、"创建归档文档"。
  2. 从 `correction` 类型的 step 中提取用户指出"应该用 X 而不是 Y"时涉及的关键概念。例如用户说"pptx 不支持 import"，则提取"pptx import"或"pptx 上传"。
  3. 提取结果应该是用户实际会输入的搜索词/命令关键词，而非内部实现细节。避免提取 agent 内部调用的 tool 名（如 `Write`, `Read`），这些对用户搜索没有意义。
  4. 与 `tags` 的区别：`tags` 是系统/工具/领域分类（用于过滤），`trigger_keywords` 是用户视角的搜索词（用于兜底匹配）。同一个概念如果既出现在 `tags` 又可能出现在 `trigger_keywords`，优先放在 `trigger_keywords` 中当它是用户常用表达时。参考 MVP 示例：`["飞书知识库", "上传docx", "上传pptx"]`。

#### 2.2 轨迹级经验区字段

**`任务名称`（H1 标题）**

- **MVP 定义**：轨迹的人类可读标题，用于在正文开头标识这条轨迹的主题。
- **来源**：`task` 字段的精炼版本。
- **生成方式**：从 `task` 中提取核心动作和涉及的主要系统/对象，生成 10-20 字的短语。去掉修饰语和细节描述，保留"在哪个系统上做什么事"的主干。例如 `"把本地 docx/pptx 上传到飞书，并在知识库里创建归档文档记录链接"` → `飞书知识库文件上传归档`。标题应该让读者一眼看出这条轨迹的主题，不需要读完全文就能判断是否相关。

**`核心纠偏点/注意事项`**

- **MVP 定义**：本轨迹最重要的经验沉淀，全局层，不强制逐步写。
- **来源**：第四步经验提取中所有 `correction` step 的 `mistake_pattern` 聚合。
- **生成方式**：
  1. 遍历精炼轨迹中所有 `correction` 类型的 step，提取每个纠偏事件的 `generalizable_rule`（即"从这个错误中可以得出什么通用规则"）。
  2. 将语义相近的规则合并。例如多个 step 都指向"用错了 skill"，合并为一条关于 skill 选择的通用规则。
  3. 每条用完整句子描述，包含"错误做法 + 正确做法 + 原因"三要素。参考 MVP 示例：`"wiki 与 drive 是两套系统：drive 文件不能直接作为 wiki 子节点挂载；正确做法是创建归档 docx，写入链接。"`
  4. 保留 2-5 条最重要的纠偏点。超过 5 条时，只保留被多个 step 反复验证的规则和会导致全链路偏航的关键错误。
  5. 如果轨迹中没有任何 `correction` step（纯递进模式且一路顺利），此小节可以为空，但标题必须保留。

**`相似技能辨析`（可选）**

- **MVP 定义**：列出容易混淆的 skills/tools，以及为什么不选它们。
- **来源**：完整原始轨迹（非精炼版）中 agent 尝试过但最终被用户否决或后续被 correction 覆盖的 skill/tool。
- **生成方式**：
  1. 回顾完整原始轨迹，找到所有 agent 调用过但最终没有出现在精炼步骤中的 skill/tool。
  2. 对于每个被放弃的 skill/tool，分析它为什么不适合：是功能不匹配？是用户明确否决？还是在后续纠偏中被更好的方案替代？
  3. 每条格式：`<容易混淆的 skill/tool 名称>：<为什么不适用它的具体原因}`。参考 MVP 风格：明确指出"X 不能做 Y"或"X 适合 A 场景但不适合 B 场景"。
  4. 如果没有容易混淆的 skill/tool，可以省略此小节。
  5. 注意：只列出"用户可能也会想到但实际不该用"的 skill/tool，不要列出明显不相关的选项。

#### 2.3 Steps 字段（内嵌 YAML，计划级骨架）

**`steps[].id`**

- **MVP 定义**：步骤 ID，短且稳定。
- **来源**：精炼后的步骤序列。
- **生成方式**：用 2-4 个英文单词的蛇形命名（snake\_case）描述该步骤的核心动作，例如 `list_structure`, `upload_docx`, `write_archive_doc`, `analyze_skill_structure`。**不要用 S1, S2, S3 这种序号**，因为语义化 ID 在后续版本迭代中更稳定——即使步骤顺序变化，ID 仍然有意义。ID 应该是动作的动宾结构或名词短语，保持简短。

**`steps[].action`**

- **MVP 定义**：该子步骤要做的操作/动作描述（计划级）。
- **来源**：精炼后该 step 的 `user_intent` + `agent_action` 合并。
- **生成方式**：用"做什么"的祈使句式描述该步骤的目标。描述应该足够具体，让执行者知道这一步要达成什么，但不要包含具体实现细节。参考 MVP 示例：`"列出知识库结构，定位 parent_node_token"`, `"导入 docx 为在线文档"`, `"上传 pptx/pdf 到云空间"`。长度控制在 10-30 字。如果该步骤包含多个子动作，用逗号或"并"连接。

**`steps[].skill`**

- **MVP 定义**：推荐命中的 skill（字符串或数组）。
- **来源**：该 step 调用的主要 skill 名。
- **生成方式**：
  1. 从该 step 的 `agent_action` 中提取被调用的 skill 名称（通常是 slash command 对应的 skill，如 `lark-wiki`, `lark-drive`, `oh-my-claudecode:plan`）。
  2. 如果该步只调用了一个 skill，用字符串格式，如 `"lark-wiki"`。
  3. 如果该步调用了多个 skill 且都关键，用数组格式，如 `["lark-drive", "lark-doc"]`。
  4. 如果该步没有调用任何 skill（纯 Bash 命令或直接工具调用），填 `"none"`。
  5. 注意：这里填的是 skill 名而非 tool 名。`Write`, `Read`, `Bash`, `Agent` 是 tool 不是 skill，不应出现在此字段中。只有形如 `<skill-name>` 或 `oh-my-claudecode:<name>` 的才是 skill。

**`steps[].how[]`**

- **MVP 定义**：方法模板（命令/调用模板列表，不含真实参数）。
- **来源**：该 step 的关键 tool 调用参数或命令。
- **生成方式**：
  1. 从该 step 的 `agent_action` 中提取关键命令或调用模板。例如 `lark-cli wiki spaces list`, `lark-cli drive +import --file ${docx_path} --type docx --as user`。
  2. **不含真实参数**：所有具体值用变量占位符替换（如 `${docx_path}`, `${space_id}`, `${archive_doc_id}`）。不要写入实际的文件路径、token、ID 等。这是为了让模板可以被不同任务复用。
  3. 每个 step 的 `how` 列表长度为 1-3 条。超过 3 条时，合并语义相近的命令。
  4. 命令格式应该是用户可以直接复制执行的 shell 命令或 skill 调用方式。如果涉及 skill 调用，写出 skill 名和推荐参数（参考 skill 的 SKILL.md 中的 usage 部分）。
  5. 参考 MVP 示例的写法：`"lark-cli wiki spaces list"`, `"lark-cli docs +update --doc ${archive_doc_id} --mode overwrite --markdown ${archive_markdown_path}"`。

**`steps[].key_point`（可选）**

- **MVP 定义**：必要要点，仅在易错/易混淆时写一句。
- **来源**：该 step 对应的 `mistake_pattern`（如有）。
- **生成方式**：
  1. **只在发生过 correction 的 step 中写入**。如果该 step 在原始轨迹中一路顺利、没有发生纠偏，则不写 `key_point` 字段（直接省略，而非留空）。
  2. 格式为"注意 X，因为 Y"或"不要 X，否则 Y"的一句话。参考 MVP 示例：`"不要跳过定位步骤，避免 token 乱填导致全链路偏航"`, `"pptx 不支持 import，别用错"`。
  3. 内容应该直接指出最容易犯的错误和后果，不要写泛化的建议（如"注意检查参数"这种没有信息量的提示）。
  4. 长度控制在 15-40 字。如果一句话说不清楚，说明这个纠偏点应该提升到上层的"核心纠偏点/注意事项"中，而不是塞在 step 级别。

### 输出格式模板

````markdown
---
trajectory_id: <蛇形命名稳定 ID，如 skill_design_iteration_v1>
task: "<confirmed_task_description，直接使用不压缩>"
when_to_use:
  - "<完整句子描述适用场景 1>"
  - "<完整句子描述适用场景 2>"
tags: ["<系统/工具/领域标签 1>", "<标签 2>", "<标签 3>"]
trigger_keywords: ["<用户搜索词 1>", "<用户搜索词 2>", "<用户搜索词 3>"]
---

# 轨迹：<10-20 字的人类可读标题>

## 核心纠偏点/注意事项
- <完整句子：错误做法 + 正确做法 + 原因>
- <完整句子：最容易犯的错 + 正确做法>

## 相似技能辨析（可选）
- <容易混淆的 skill X>：为什么不用它，因为...

## 具体的解决流程Steps
```yaml
steps:
  - id: explore_skill_structure
    action: "探索目标 skill 目录结构，理解现有设计"
    skill: "oh-my-claudecode:explore"
    how:
      - "Agent(subagent_type='Explore', prompt='探索目录结构并返回所有文件和子目录')"
    key_point: "不要直接读取所有文件，先理解结构再决定读哪些"

  - id: compare_reference_template
    action: "对比参考 skill 的结构，提取可复用模式"
    skill: "none"
    how:
      - "Read <目标 skill>/SKILL.md"
      - "Read <参考 skill>/SKILL.md"
    key_point: "注意参考 skill 的辅助文件（data_contracts, templates, scripts），不要遗漏"

  - id: write_improvement_plan
    action: "基于对比结果，生成结构化改进计划"
    skill: "oh-my-claudecode:planner"
    how:
      - "Agent(subagent_type='planner', prompt='基于对比结果生成改进计划')"
```
````

