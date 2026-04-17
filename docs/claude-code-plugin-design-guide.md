# Claude Code 插件设计指南（基于源码深度分析）

> 基于对 oh-my-claudecode（37 Skills, 19 Agents, 20+ Hook Scripts）和 learn-once 的完整源码分析。

---

## 一、插件的本质

一个 Claude Code 插件 = **一组在会话生命周期中自动注入的指令 + 可触发的操作手册 + 事件驱动的安全网**。

Claude Code 通过 `plugin.json` 注册 Skills 和 Agents，通过 `hooks/hooks.json` 注册生命周期钩子。所有组件在会话启动时自动加载到 Claude 的上下文中。

---

## 二、四层架构的精确职责

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 0: AGENTS.md (路由器 + 宪法)                           │
│  定义: 关键词触发规则、Agent 目录、团队管线                    │
│  加载时机: 每次会话启动，始终在系统提示中                       │
├──────────────────────────────────────────────────────────────┤
│  Layer 1: Hooks (hooks.json + 脚本)                           │
│  定义: 事件驱动，静默执行                                      │
│  加载时机: 对应事件发生时自动触发                               │
├──────────────────────────────────────────────────────────────┤
│  Layer 2: Skills (skills/*/SKILL.md)                          │
│  定义: 用户触发后，知道该做什么、怎么编排                        │
│  加载时机: 被关键词或命令触发时才读取                            │
├──────────────────────────────────────────────────────────────┤
│  Layer 3: Agents (agents/*.md)                                │
│  定义: 被 Skill spawn 时注入具体任务，独立执行                   │
│  加载时机: 被 spawn 时才读取                                    │
└──────────────────────────────────────────────────────────────┘
```

**一句话区分**：
- **AGENTS.md** — "谁触发什么"（路由器）
- **Hooks** — "不需要用户知道，自动发生的"
- **Skills** — "用户触发后，知道该做什么、怎么编排"
- **Agents** — "被 Skill 调用，知道怎么把一件事做好"

---

## 三、Hooks 设计

### 3.1 完整生命周期事件

oh-my-claudecode 支持 **11 种事件**：

| 事件 | 时机 | 实际用途 |
|------|------|---------|
| **UserPromptSubmit** | 用户提交 prompt 前 | 关键词检测、Skill 注入、自动召回上下文注入 |
| **SessionStart** | 新会话开始 | 初始化会话状态、加载 notepad |
| **PreToolUse** | Claude 使用工具前 | 验证规则、阻止只读 agent 写文件 |
| **PermissionRequest** | 权限请求时 | 自动化权限决策 |
| **PostToolUse** | 工具使用完成后 | 验证结果、处理 `<remember>` 标签 |
| **PostToolUseFailure** | 工具失败后 | 失败重试、错误记录 |
| **SubagentStart** | 子 Agent 启动时 | 跟踪子 Agent 生命周期 |
| **SubagentStop** | 子 Agent 完成时 | 记录完成状态 |
| **PreCompact** | 上下文压缩前 | 保存重要记忆到文件 |
| **Stop** | Claude 完成响应后 | **持续模式拦截**（阻止 Claude 过早停止） |
| **SessionEnd** | 会话结束时 | 会话清理、生成总结 |

### 3.2 Hook 的输入输出协议

**输入**（stdin JSON）：
```json
{
  "tool_name": "Write",
  "tool_input": { "file_path": "...", "content": "..." },
  "cwd": "/path/to/project",
  "session_id": "abc123"
}
```

**输出**（stdout JSON）：
```json
{
  "continue": true,
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "message to inject into next turn"
  }
}
```

### 3.3 真实 Hook 示例

**Stop Hook — 持续模式拦截**（`persistent-mode.mjs`）：
- 检查 `.omc/state/` 下的 mode 状态文件
- 如果 ralph/autopilot/ultrawork 活跃 → 阻止 Claude 停止
- 输出: `{ decision: "block", reason: "The boulder never stops" }`

**PreToolUse Hook — 规则验证**（`pre-tool-enforcer.mjs`）：
- 阻止只读 agent 调用 Write/Edit
- 验证团队模式下的路由
- 记录 Skill 调用到追踪

**PostToolUse Hook — 结果验证**（`post-tool-verifier.mjs`）：
- 处理 Claude 输出中的 `<remember>` 标签 → 自动保存记忆
- 追加 Bash 命令到 `~/.bash_history`
- 在 70%/90% 上下文使用时发出压缩警告

### 3.4 Hook 设计 Checklist

| 检查项 | 标准 |
|--------|------|
| 执行时间 | < 1 秒（UserPromptSubmit/PreToolUse） |
| 正常情况 | 静默（只报告异常） |
| 失败影响 | 不应该阻塞主流程（除非是 PreToolUse 的 block） |
| 环境变量 | 使用 `$CLAUDE_PLUGIN_ROOT` 定位脚本 |
| 可禁用 | 通过 `OMC_SKIP_HOOKS` 环境变量 |

### 3.5 Hook 的定义位置

```
hooks/hooks.json          ← 主要定义文件
.claude-plugin/plugin.json ← 只声明 skills + mcpServers（不定义 hooks）
```

### 3.6 你的项目 vs 参考实现

| 维度 | oh-my-claudecode | 你的项目 |
|------|-----------------|----------|
| Hook 数量 | 20+（11 种事件） | 1（只有 UserPromptSubmit） |
| Hook 脚本 | 20+ .mjs/.cjs 文件 | 1 个 auto_recall.js |
| Stop Hook | 有（持续模式拦截） | 没有 |
| PostToolUse | 有（验证、记忆） | 没有 |

---

## 四、Skills 设计

### 4.1 四种 Skill 类型

| 类型 | 代表 | 行数范围 | 子 Agent 依赖 |
|------|------|----------|--------------|
| **循环控制器** | ralph(387), self-improve(383) | 300-500 | 有（3-6 种 Agent） |
| **管线编排器** | autopilot, team(969) | 400-1000 | 有（多 Agent 并行） |
| **直接操作** | cancel, remember, trace | 50-200 | 无或少量 |
| **配置型** | omc-setup, configure-notifications(1214) | 200-1200 | 无（交互式） |

### 4.2 SKILL.md 必须包含的结构

```markdown
---
name: <name>                           ← 用户看到的名字
description: <一句话>                   ← 用户输入 /skills 时看到
level: <1-4>                           ← 复杂度
---

## 我是什么
一段话定义职责边界

## 什么时候用我 / 什么时候别用我
Use_When: [...]
Do_Not_Use_When: [...]

## 工作流
Step 1 → Step 2 → Step 3 → ...（编号步骤，不是散文）

## 停止条件
什么情况下退出

## 输出格式
最后报告什么

## 子 Agent 指令（如果需要）
spawn 时传入的具体参数 + 脚本路径
```

### 4.3 两种脚本组织方式

```
方式一：全局共享（被 2+ 组件用）
  scripts/
  ├── cleanup-orphans.mjs    ← cancel + team 共用
  └── run.cjs                ← hook 统一入口

  判断标准：被 2+ Skill 引用，或项目级基础设施脚本

方式二：Skill 专属（只被 1 个 Skill 用）
  skills/self-improve/scripts/
  ├── validate.sh            ← 只被 self-improve 用
  └── plot_progress.py

  判断标准：只属于一个 Skill，且是该 Skill 核心流程的一部分
```

### 4.4 让子 Agent 跑脚本

Skill spawn 子 Agent 时，把脚本路径当参数传进去：

```markdown
在每个执行器的提示词中传递：
  - scripts/validate.sh 的路径
  - 覆盖指令：先运行 validate.sh，再运行 benchmark
```

子 Agent 自己跑：
```bash
./validate.sh plan.json result.json
```

### 4.5 你的项目 vs 参考实现

| 维度 | oh-my-claudecode | 你的项目 |
|------|-----------------|----------|
| Skill 数量 | 37 个 | 4 个 |
| 有 AGENTS.md | 有（定义路由） | **缺失** |
| 脚本组织 | 全局 + Skill 专属 | 全部在 scripts/python/ |
| 循环控制器 | ralph, self-improve | 无 |

---

## 五、Agents 设计

### 5.1 Agent 分三层

| 层 | 模型 | Agent 示例 | 成本 |
|----|------|-----------|------|
| **HIGH** | Opus | architect, critic, planner, debugger | 最高 |
| **MEDIUM** | Sonnet | executor, test-engineer, code-reviewer | 中等 |
| **LOW** | Haiku | explore, verifier, git-master | 最低 |

### 5.2 Agent 的 .md 文件标准结构

```markdown
---
name: executor
description: 专注于实现工作的任务执行者
model: claude-sonnet-4-6
level: 2
---

<Agent_Prompt>
  <Role>        你是谁、做什么、不做什么
  <Constraints> 硬规则（不能越界）
  <Protocol>    工作流程（探索→执行→验证）
  <Tool_Usage>  用什么工具、怎么 spawn 子 Agent
  <Output>      输出格式模板
  <Anti_Patterns> 不能犯的错误
</Agent_Prompt>
```

### 5.3 Agent 没有专属脚本

19 个 Agent 中，**没有一个**被定义为"拥有某个专属脚本"。

所有 Agent 只用：
- Claude 内置工具（Read, Write, Edit, Bash, Grep, Glob）
- Skill spawn 时传入的脚本路径

### 5.4 什么时候需要创建子 Agent

| 场景 | 需要子 Agent？ | 原因 |
|------|---------------|------|
| 单步操作 | 不需要 | Skill 直接做 |
| 需要隔离上下文 | 需要 | 子 Agent 有独立工具权限 |
| 需要不同模型 | 需要 | 子 Agent 可指定 haiku/sonnet/opus |
| 需要并行执行 | 需要 | 多个子 Agent 并行 |
| 复杂多步骤流程 | 需要 | 每个步骤独立负责 |

### 5.5 你的项目 vs 参考实现

| 维度 | oh-my-claudecode | 你的项目 |
|------|-----------------|----------|
| Agent 数量 | 19 个 | 2 个 |
| 模型分层 | 3 层（haiku/sonnet/opus） | 无分层 |
| 通用程度 | 通用工人 | 太专用，可内嵌到 Skill |

---

## 六、Prompt 模板模式

当 Skill 需要 spawn 有特定行为的子 Agent 时，**不要把 prompt 写在 SKILL.md 里**：

```
skills/self-improve/
├── SKILL.md              ← 编排器（383 行）
├── si-researcher.md      ← 子 Agent prompt（74 行）
├── si-benchmark-builder.md  ← 子 Agent prompt
└── si-goal-clarifier.md     ← 子 Agent prompt
```

Skill 的操作：
1. `Read si-researcher.md`
2. `Spawn Agent(prompt: <si-researcher.md内容> + 参数)`
3. 子 Agent 按 prompt 工作

**好处**：
- SKILL.md 保持干净
- Prompt 模板可以独立维护
- 多个 Skill 可以复用同一个 prompt 模板

---

## 七、Skill + Agent + Script 的完整调用链

以 self-improve 的 Step 7 为例：

```
SKILL.md（编排器）
  │
  │  spawn executor(subagent_type="executor", model="opus", prompt="
  │    你是一个 executor。你需要：
  │    1. 实施 plan.json 中的改动
  │    2. 运行 {validate_sh_path} 验证 schema
  │       bash ./validate.sh --worktree {worktree} plan.json result.json
  │    3. 运行 {benchmark_command}
  │       python3 benchmark.py
  │    4. 输出 Benchmark Result JSON
  │  ")
  │
  │  子 Agent 收到后：
  │    - 读自己的通用规则（executor.md）
  │    - 读 Skill 传入的具体指令（prompt）
  │    - 自己跑 validate.sh（bash 命令）
  │    - 自己跑 benchmark.py（bash 命令）
  │    - 返回结果 JSON
```

---

## 八、最终 Checklist

设计一个新的 Claude Code 插件时，逐项检查：

### AGENTS.md
- [ ] 有 name + description
- [ ] 有关键词触发规则
- [ ] 有 Agent 目录声明
- [ ] 有团队管线定义

### Skills
- [ ] SKILL.md 有 name + description（用户能看到）
- [ ] 有 Use_When 和 Do_Not_Use_When
- [ ] 工作流有编号步骤，不是散文
- [ ] 有停止条件
- [ ] 有输出格式定义
- [ ] 如果需要子 Agent，spawn 时传入了脚本路径和参数
- [ ] 复杂子 Agent 的 prompt 拆成单独文件

### Agents
- [ ] 有明确的 Role 和不做什么
- [ ] 有 Constraints（硬规则）
- [ ] 有 Output_Format（报告模板）
- [ ] 没有引用特定 Skill 的逻辑（保持通用）

### 脚本
- [ ] 被 2+ 组件用的脚本在 scripts/ 根目录
- [ ] 只属于一个 Skill 的脚本在 skills/<name>/scripts/
- [ ] 脚本有 --help 和错误退出

### Hooks
- [ ] Hook 命令 < 1 秒
- [ ] 正常情况静默
- [ ] 只做探测或修补，不做编排
- [ ] 使用 $CLAUDE_PLUGIN_ROOT 定位脚本
- [ ] 可通过 OMC_SKIP_HOOKS 禁用

---

## 九、最常见的错误

| 错误 | 应该怎么做 |
|------|-----------|
| 把路由逻辑写在 Skill 里 | 路由逻辑应该在 AGENTS.md |
| Skill 里写了太多判断逻辑 | 应该是工作流步骤，不是判断树 |
| Agent 太轻量（2-3 步操作） | 直接内嵌到 Skill 的工作流里 |
| Hook 做了编排的事 | Hook 只做探测和修补 |
| 脚本全部放在一个目录 | 按共享/专属分开 |
| 子 Agent 需要专属脚本 | 不需要，用共享脚本，路径由 Skill 传入 |
| SKILL.md 里写子 Agent 的完整 prompt | 拆成 prompt 模板文件，被 Skill 读取 |
