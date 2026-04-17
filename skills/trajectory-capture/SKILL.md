---
name: trajectory-capture
description: 手动触发轨迹沉淀，从当前会话中提炼可复用的经验轨迹
level: 3
---

# Trajectory Capture

## 我是什么

这是一个手动触发的轨迹沉淀 skill。当用户在多轮对话中觉得"这条路走通了，值得沉淀"时，通过 `/trajectory-capture`（或 `/tc`）触发。

它不是自动总结工具，而是一个"确认任务边界 → 定位日志 → 精炼经验 → 直接入库"的完整流程。

## 什么时候用我 / 什么时候别用我

**Use_When:**
- 用户完成了一个复杂任务，过程中经历了纠偏/试错/工具选择，最终找到了正确路径
- 用户明确想"把这次的经验保存下来，下次遇到类似问题可以直接参考"
- 用户手动输入 `/trajectory-capture` 或 `/tc`

**Do_Not_Use_When:**
- 用户只是问了一个简单问题，没有多轮交互过程
- 用户想自动捕获经验（当前不做自动 capture）
- 用户想查看已有轨迹（用 `/trajectory-status`）
- 用户想获取推荐规划（用 `/trajectory-suggest`）

## 工作流

### Phase 1: 轨迹范围确认

1. 从近到远回看最近若干轮对话（用户提问、agent 回答、关键工具调用、用户纠偏语句）
2. 将当前上下文概括为 2-4 个候选 task，每个候选包含：
   - `task_description`：一句话概括本次沉淀 task 对象 + 详细描述
   - `why_this_scope`：为什么判断这几轮属于同一个任务
   - `anchor_user_message`：最像"这个任务正式成立"的那条用户提问
   - `excluded_branches`：本次不纳入沉淀的旁支话题
3. 向用户展示候选，请用户选择 1 个，或直接修改
4. 用户确认后，生成 `confirmed_task_description` 和 `anchor_user_message`

展示格式：
```markdown
本次可以沉淀的候选 task 如下，请选择 1 个，或直接修改：

1. `<task_title_1>`
   - 为什么这样归类：`<why_this_scope_1>`
   - 任务起点候选：`<anchor_user_message_1>`
   - 不纳入本次沉淀的内容：`<excluded_branches_1>`

2. `<task_title_2>`
   - 为什么这样归类：`<why_this_scope_2>`
   - 任务起点候选：`<anchor_user_message_2>`
   - 不纳入本次沉淀的内容：`<excluded_branches_2>`
```

### Phase 2: 上下文定位（子 agent 自主定位）

用户确认后，创建 `trajectory-memory-constructor` 子 agent，发送以下指令：

```
请你根据下面的 session_locator 信息，先在 Claude Code 的上下文对话缓存文件中定位到 task 相关的轨迹的起点与终点。然后根据轨迹精炼 SOP 去沉淀轨迹经验，然后将轨迹保存。完成之后请以 JSON 格式返回轨迹的概要版本。
----
{
  "session_locator": {
    "task": "<confirmed_task_description>",
    "anchor_user_message": "<anchor_user_message>",
    "workspace_folder": "<当前工作目录路径>"
  }
}
---
返回给主 agent 的格式为：
{
  "task_description": "<task_description>",
  "trajectory_summary": "<trajectory_summary>",
  "trajectory_file": "<path to the saved .md file>"
}
```

子 agent 会自行调用 `locate_session.py` 定位日志、读取原始记录、按 SOP 精炼、写出轨迹草稿。

### Phase 3: 多轮对话轨迹总结与精炼

子 agent（trajectory-memory-constructor）负责：
1. 运行 `locate_session.py` 定位会话日志
2. 按 `轨迹压缩sop.md` 精炼多轮对话
3. 按 `trajectory-format-mvp.md` 格式写出轨迹 Markdown 文件
4. 返回 JSON：`{"task_description": "...", "trajectory_summary": "...", "trajectory_file": "..."}`

### Phase 4: 轨迹入库

子 agent 完成精炼后，自动执行入库：

1. 将轨迹 Markdown 文件写入 `~/.claude/learn-once/trajectories/`
2. 运行入库脚本：
   ```bash
   python {plugin_root}/scripts/python/ingest_trajectory.py <trajectory_md_path>
   ```
3. 报告入库结果：
   ```
   轨迹沉淀完成。
   - 文件: <trajectory_file>
   - ID: <trajectory_id>
   - 索引: meta.json + embeddings.pkl 已更新
   ```

## 停止条件

以下情况停止：
- 轨迹精炼完成并入库
- 用户表示"不需要沉淀" / "取消"
- 子 agent 无法定位到匹配的会话日志（返回错误信息给用户）

## 输出格式

### 向用户展示的内容

1. 候选 task 列表（Phase 1）
2. 入库完成报告（Phase 4）

### 最终报告

```markdown
轨迹沉淀完成。

- **任务**: <task>
- **轨迹 ID**: <trajectory_id>
- **文件**: <file_path>
- **适用场景**: <when_to_use 摘要>
- **关键纠偏点**: <核心纠偏点摘要>
```

## 子 Agent 指令

spawn 时使用：
- `subagent_type`: `trajectory-memory-constructor`
- `model`: `sonnet`
- `prompt`: 如上 Phase 2 中定义的指令（包含 session_locator JSON）

## 依赖脚本

- 定位脚本: `{plugin_root}/scripts/python/locate_session.py`
- 入库脚本: `{plugin_root}/scripts/python/ingest_trajectory.py`
- 精炼 SOP: `{plugin_root}/docs/轨迹压缩sop.md`
- 格式规范: `{plugin_root}/docs/trajectory-format-mvp.md`
