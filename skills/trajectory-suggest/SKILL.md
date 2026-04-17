---
name: trajectory-suggest
description: 召回相似历史轨迹，生成面向当前任务的推荐规划
level: 2
---

# Trajectory Suggest

## 我是什么

这是一个轨迹经验推荐 skill。它接收当前任务描述，从历史轨迹库中召回相似经验，生成面向当前任务的策略型推荐规划。

它可以被手动触发（`/trajectory-suggest`），也可以被 hook 自动触发（UserPromptSubmit 注入提示时）。

## 什么时候用我 / 什么时候别用我

**Use_When:**
- 用户输入 `/trajectory-suggest` 或 `/ts`
- hook 注入了 auto recall 提示，要求先评估再执行
- 用户遇到一个任务，想参考历史经验获得行动建议
- 用户说"轨迹推荐"或"有没有类似经验"

**Do_Not_Use_When:**
- 用户想沉淀当前对话经验（用 `/trajectory-capture`）
- 用户想查看已有轨迹统计（用 `/trajectory-status`）
- 用户的问题是简单的、不需要历史经验的

## 工作流

### Step 1: 读取上次规划状态

读取 `~/.claude/learn-once/state/active_suggestion.md`。

该文件包含上一次的推荐规划，包括 `coverage_in`（覆盖范围内的问题）和 `coverage_out`（越界/新需求）的定义。

### Step 2: 复用判断

判断用户当前 prompt 是否仍在上次规划的覆盖范围内：

- **覆盖范围内（Coverage In）**：用户只是在同一个任务下继续追问细节
  - 例如：追问某一步怎么执行、某个参数怎么填、某个文件放哪里
  - 回答：直接告诉主 agent 无更多参考经验，继续参考上次规划

- **越界/目标变化（Coverage Out）**：用户目标发生明显变化或提出新需求
  - 例如：从"完成某个改造任务"转到"新增另一条链路"
  - 关键约束发生变化导致原规划不再适用
  - 继续执行 Step 3

### Step 3: 轨迹召回

运行召回脚本：

```bash
python {plugin_root}/scripts/python/recall_trajectory.py "<当前具体任务描述>" --top-k 3
```

脚本输出格式：
```
Recall results for: '<当前具体任务描述>' (top_k=3)

1. <轨迹文件名>
   File: <轨迹文件完整路径>
   Score: <相似度得分>
```

### Step 4: 读取轨迹并生成推荐规划

逐一读取召回的轨迹文件。

加载 `{plugin_root}/docs/轨迹推荐sop.md`，严格按照 SOP 中的要求生成轨迹经验建议。

SOP 定义了输出格式为策略型经验建议，包含：
- 当前任务理解
- 历史经验对当前任务的意义
- 这类问题通常如何处理
- 针对当前任务的建议行动
- 执行中可能遇到的问题
- 当前经验的边界

### Step 5: 写入状态文件

将生成的推荐规划写入：
```
~/.claude/learn-once/state/active_suggestion.md
```

### Step 6: 返回给主 Agent

```markdown
## 推荐规划

<3-5 条关键建议的简要列表>

完整建议已写入 `~/.claude/learn-once/state/active_suggestion.md`，请参考执行。
```

## 停止条件

以下情况停止：
- 判断为 coverage_in，返回"无需重新建议"
- 召回结果为空（无相似轨迹），返回"暂无相似历史经验可参考"
- 用户取消了推荐请求

## 输出格式

### Coverage In 时

```
无需重新建议。当前问题仍在上次推荐规划的覆盖范围内。
原因：<简要说明>
```

### 无相似轨迹时

```
未找到相似的历史轨迹经验。
建议直接处理当前任务。
```

### 生成新规划时

```markdown
## 推荐规划

1. <关键建议 1>
2. <关键建议 2>
3. <关键建议 3>

完整建议已写入 `~/.claude/learn-once/state/active_suggestion.md`，请参考执行。
```

## 依赖脚本

- 召回脚本: `{plugin_root}/scripts/python/recall_trajectory.py`
- 推荐 SOP: `{plugin_root}/docs/轨迹推荐sop.md`
- 状态文件: `~/.claude/learn-once/state/active_suggestion.md`
