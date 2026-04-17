---
name: trajectory-status
description: 查看已沉淀轨迹的统计分析和概览
level: 1
---

# Trajectory Status

## 我是什么

这是一个轨迹状态查看 skill。它读取已入库的轨迹元数据，生成统计分析报告，帮助用户了解当前轨迹经验库的整体情况。

## 什么时候用我 / 什么时候别用我

**Use_When:**
- 用户输入 `/trajectory-status` 或 `/tst`
- 用户说"轨迹状态"、"看看已有的轨迹"、"trajectory status"
- 用户想了解当前经验库里有多少条轨迹、覆盖哪些领域

**Do_Not_Use_When:**
- 用户想沉淀新经验（用 `/trajectory-capture`）
- 用户想获取推荐规划（用 `/trajectory-suggest`）
- 用户想搜索特定轨迹（直接描述任务，会触发 suggest）

## 工作流

### Step 1: 读取元数据

读取 `~/.claude/learn-once/meta/meta.json`。

如果文件不存在或为空，报告：
```
当前轨迹经验库为空。使用 /trajectory-capture 开始沉淀第一条经验轨迹。
```

### Step 2: 统计轨迹信息

从 meta.json 中提取所有唯一的 `trajectory_id`，然后逐一读取对应的轨迹 Markdown 文件，收集以下信息：

1. **轨迹总数**: 不同 trajectory_id 的数量
2. **标签分布**: 从 frontmatter 的 `tags` 字段统计各标签出现频率
3. **适用场景汇总**: 从 `when_to_use` 字段提取场景列表
4. **最近入库**: 按文件修改时间排序，列出最近 3 条轨迹

### Step 3: 生成报告

```markdown
## 轨迹经验库状态

**轨迹总数**: N 条

### 标签分布
| 标签 | 数量 |
|------|------|
| xxx  | N    |

### 最近入库
1. **<trajectory_title>** - <trajectory_id>
   适用场景: <when_to_use 摘要>

2. ...

3. ...

### 索引状态
- meta.json: M 条记录
- embeddings.pkl: K 条向量
- 轨迹目录: N 个 .md 文件
```

### Step 4: 检查索引一致性

对比 meta.json 中的记录数与 trajectories 目录中的 .md 文件数，如果不一致，报告差异。

## 停止条件

- 报告生成完成后停止

## 输出格式

见 Step 3 的模板。如果没有轨迹，直接报告空库状态。
