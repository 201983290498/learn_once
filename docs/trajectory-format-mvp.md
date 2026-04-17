# 轨迹经验文件格式（MVP 定稿）

本文件记录我们已确认的“轨迹（trajectory）经验”**最小可行格式**（MVP），用于：

- 解决 Claude Code 在复杂任务中**选错 skill / 用错工具 / 提问不当**导致执行失败的问题
- 将用户多轮纠偏后形成的“正确路径”沉淀为**可检索、可复用的说明书式骨架**
- 在新任务到来时，通过 RAG（Embedding + 关键词）召回相似轨迹，交给子 agent 产出计划，再由用户确认执行（X 模式）

> 核心原则：**P 模式（说明书）**。轨迹强调“应该用什么 skill + 怎么用（方法模板）”，而非记录每次任务的完整执行流水。

***

## 1. 文件载体与存放建议

- **载体**：Markdown（人类可读）+ 内嵌 YAML（机器可解析）
- **建议位置（MVP，全局）**：`~/.claude/learn-once/trajectories/*.md`
- **检索索引**：只对 metadata 生成索引文本与 embedding；轨迹正文不进入 embedding（避免过长与污染）。当前实现以 `index_text = task + when_to_use + tags + trigger_keywords` 为主检索文本，并可选补充 `task` / 聚合后的 `when_to_use` 向量。

***

## 2. 顶层 metadata（YAML frontmatter）

> 用于检索与过滤（embedding / 关键词 / tag 过滤），并为子 agent 生成计划提供上下文。

最小字段（MVP）：

- `trajectory_id`：轨迹唯一 ID（稳定，不随文件名变更）
- `task`：用户要解决的问题（一句话）
- `when_to_use`：列表，描述“哪些问题适用此轨迹”（会并入 `index_text`，也可额外生成聚合场景向量）
- `tags`：列表，领域/系统/工具大类标签（用于过滤）
- `trigger_keywords`：列表，关键词兜底检索（用于 grep/FTS）

***

## 3. 轨迹级经验区（Markdown 正文）

建议在正文中固定保留以下小节（内容可为空，但模板保留）：

- `核心纠偏点/注意事项`：本轨迹最重要的经验沉淀（全局层，不强制逐步写）
- `相似技能辨析（可选）`：列出容易混淆的 skills/tools，以及为什么不选它们

***

## 4. Steps（内嵌 YAML，计划级骨架）

> 每一步尽量“轻”。默认不写大量 why/mistakes；只有历史上确实容易错的步骤才写 `key_point`。

### 4.1 Step 字段（MVP）

- `id`：步骤 ID（短且稳定）
- `action`：该子步骤要做的操作/动作描述（计划级）
- `skill`：推荐命中的 skill（字符串或数组）
- `how`：方法模板（命令/调用模板列表，不含真实参数）
- `key_point`（可选）：必要要点（仅在易错/易混淆时写一句）

### 4.2 模板示例

````markdown
---
trajectory_id: feishu_wiki_upload_archive_v1
task: "把本地 docx/pptx 上传到飞书，并在知识库里创建归档文档记录链接"
when_to_use:
  - "需要把本地文件归档到飞书知识库，并产出可访问链接清单"
  - "需要区分 docx(import) 与 pptx(upload) 的正确上传方式"
tags: ["feishu", "wiki", "drive", "docx", "pptx"]
trigger_keywords: ["飞书知识库", "上传docx", "上传pptx"]
---

# 轨迹：飞书知识库文件上传归档

## 核心纠偏点/注意事项
- wiki 与 drive 是两套系统：drive 文件不能直接作为 wiki 子节点挂载；正确做法是创建归档 docx，写入链接。
- pptx/pdf 用 upload，docx 用 import（否则会失败或产物不对）。

## Steps
```yaml
steps:
  - id: list_structure
    action: "列出知识库结构，定位 parent_node_token"
    skill: "lark-wiki"
    how:
      - "lark-cli wiki spaces list"
      - "lark-cli wiki nodes list --space-id ${space_id}"
    key_point: "不要跳过定位步骤，避免 token 乱填导致全链路偏航"

  - id: upload_docx
    action: "导入 docx 为在线文档"
    skill: "lark-drive"
    how:
      - "lark-cli drive +import --file ${docx_path} --type docx --as user"

  - id: upload_pptx
    action: "上传 pptx/pdf 到云空间"
    skill: "lark-drive"
    how:
      - "lark-cli drive +upload --file ${pptx_path} --as user"
    key_point: "pptx 不支持 import，别用错"

  - id: write_archive_doc
    action: "在归档文档中写入文件链接清单（Markdown overwrite）"
    skill: "lark-doc"
    how:
      - "lark-cli docs +update --doc ${archive_doc_id} --mode overwrite --markdown ${archive_markdown_path}"
      - "lark-cli docs +fetch --doc ${archive_doc_id}"
````

```

---

## 5. 与索引库的对应关系（MVP 约定）

- 轨迹文件是权威源；派生出的 meta 与索引库仅保存：
  - `trajectory_id`
  - `file_path`（指向轨迹 Markdown 文件）
  - `index_text`（由 `task + when_to_use + tags + trigger_keywords` 组合生成的短文本）
  - `embedding`（向后兼容的主向量）
  - `embeddings.vectors.index_text / task / when_to_use`（可选多向量扩展）

> 实现约定（MVP）：`meta` 推荐维护为 **单个聚合 JSON 文件**（例如 `~/.claude/learn-once/meta/meta.json`），由 Python 从 `trajectories/*.md` 自动抽取生成；禁止手写维护以避免不同步。
```

