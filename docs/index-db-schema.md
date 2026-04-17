# 索引文件meta.json和pkl向量文件的的构建

本文件定义索引文件meta.json和pkl向量文件的构建，用于支持：

- 轨迹文件（Markdown）作为权威源
- meta 聚合文件作为派生索引输入（由脚本从轨迹 Markdown 自动抽取生成，非手写）
- 本地索引库存储 **embedding 向量 + 指向轨迹文件的指针 + 最小元信息**
- 支持你已确认的 embedding 策略：
  - `index_text`（`when_to_use + task + tags + trigger_keywords` 拼成短文本）做 embedding
  - `task` 单独做 embedding
  - `when_to_use` 聚合文本可选做单独 embedding
- 支持根据embedding做召回

> 约定：向量以 `float32` 的 **BLOB** 存储；相似度计算在 Python 侧完成（numpy）。

***

## 1. meta.json 格式

`meta.json` 是以 `embedding_text` 为 key 的扁平字典，每个 key 对应一条轨迹的元信息。

```json
{
  "<embedding_text_1>": {
    "trajectory_id": "skill_design_iteration_v1",
    "file_path": "/absolute/path/to/trajectory/file.md"
  },
  "<embedding_text_2>": {
    "trajectory_id": "feishu_wiki_upload_archive_v1",
    "file_path": "/absolute/path/to/another/file.md"
  }
}
```

**字段说明：**

| 字段                      | 类型     | 说明                                                                                           |
| ----------------------- | ------ | -------------------------------------------------------------------------------------------- |
| `<embedding_text>`（key） | string | 该轨迹的索引文本，由 `task + when_to_use + tags + trigger_keywords` 组合生成的短文本。作为 key 保证唯一性，同时可直接用于文本检索。 |
| `trajectory_id`         | string | 轨迹唯一 ID，从 Markdown frontmatter 中解析，稳定不随文件名变更。                                                |
| `file_path`             | string | 指向轨迹 Markdown 文件的绝对路径。用于召回后读取完整轨迹内容。                                                         |

**为什么用 embedding\_text 做 key：**

- 保证唯一性：同一轨迹的不同 embedding\_text（如 index\_text vs task\_text）会生成不同的 key
- 文本可检索：meta.json 本身可以用 grep/FTS 搜索，不需要额外索引
- 避免嵌套：扁平结构比嵌套数组更容易解析和追加

## 2. pkl 文件格式

pkl 文件使用 Python 的 `pickle` 序列化，包含两个平行数组：

```python
{
    "embedding_text": [
        "<embedding_text_1>",
        "<embedding_text_2>",
        ...
    ],
    "embedding": np.array([
        [0.012, -0.034, 0.056, ...],  # embedding_text[0] 对应的向量
        [-0.011, 0.045, -0.023, ...],  # embedding_text[1] 对应的向量
        ...
    ], dtype=np.float32)
}
```

**字段说明：**

| 字段               | 类型           | 说明                                                                                    |
| ---------------- | ------------ | ------------------------------------------------------------------------------------- |
| `embedding_text` | `list[str]`  | 与 `embedding` 数组平行对应的文本列表。每个元素与 meta.json 中的一个 key 一致。                                |
| `embedding`      | `np.ndarray` | shape 为 `(N, D)` 的二维数组，其中 N 为 embedding 数量，D 为向量维度（Jina v3 为 1024）。dtype 为 `float32`。 |

**为什么分开存：**

- **meta.json** 负责文本元信息的存储和检索，人类可读可编辑
- **pkl** 负责向量的二进制存储，支持高效的矩阵运算（numpy 原生支持）
- 召回时只需加载 pkl 做矩阵运算，不需要解析整个 meta.json

## 3. 从 Markdown 生成 meta.json 和 pkl（入库脚本）

入库脚本负责从 `trajectory-format-mvp.md` 规定的 Markdown 文件中解析字段、构建 embedding 文本、调用 Jina API 生成向量、并更新 meta.json 和 pkl。

### 3.1 入库流程

```
输入：轨迹 Markdown 文件路径
输出：更新后的 meta.json + pkl 文件
```

**步骤：**

1. **解析 Markdown frontmatter**：从文件头部的 YAML 块中提取 `trajectory_id`, `task`, `when_to_use`, `tags`, `trigger_keywords` 字段。
2. **构建 embedding 文本**：
   - **主索引文本（index\_text）**：`task + " " + " ".join(when_to_use) + " " + " ".join(tags) + " " + " ".join(trigger_keywords)`。这是用于检索和 embedding 的主要文本，保持简短（建议 < 500 字）。
   - **task 单独文本**：直接使用 `task` 字段的值。用于 task 维度的单独 embedding。
   - **when\_to\_use 聚合文本**：`" ".join(when_to_use)`。可选，用于 when\_to\_use 维度的单独 embedding。
3. **生成 embedding**：使用 Jina API 调用方式，为每个 embedding 文本调用 `https://api.jina.ai/v1/embeddings`。
   - model: `jina-embeddings-v3`
   - task: `text-matching`
   - 使用环境变量 `JINA_API_KEY` 认证
4. **更新 meta.json**：
   - 如果 meta.json 不存在，创建空字典 `{}`
   - 对每个 embedding\_text，写入 `{embedding_text: {"trajectory_id": "<id>", "file_path": "<绝对路径>"}}`
   - 如果同一 `trajectory_id` 已存在，覆盖旧记录
5. **追加 pkl**：
   - 如果 pkl 不存在，创建空结构 `{"embedding_text": [], "embedding": np.array([], dtype=np.float32)}`
   - 将新的 embedding\_text 追加到 `embedding_text` 列表
   - 将新的 embedding 向量追加到 `embedding` 数组（使用 `np.vstack` 或 `np.concatenate`）
   - 保存回 pkl 文件

### 3.2 脚本路径约定

- **脚本位置**：`scripts/python/ingest_trajectory.py`
- **meta.json 位置**：`~/.claude/learn-once/meta/meta.json`
- **pkl 文件位置**：`~/.claude/learn-once/index/embeddings.pkl`
- **轨迹文件位置**：`~/.claude/learn-once/trajectories/*.md`

### 3.3 脚本用法

```bash
# 入库单条轨迹
python scripts/python/ingest_trajectory.py ~/.claude/learn-once/trajectories/feishu_wiki_upload_archive_v1.md

# 入库所有轨迹（批量）
python scripts/python/ingest_trajectory.py --all
```

## 4. 从 task 描述召回轨迹（召回脚本）

召回脚本接收一个 task 描述，生成 embedding 后与 pkl 中的向量进行矩阵相似度运算，返回最相似的轨迹文件列表。

### 4.1 召回流程

```
输入：task 描述文本（字符串）+ top_k（默认 5）
输出：[(file_path, score), ...] 列表，按相似度降序排列，按 file_path 去重
```

**步骤：**

1. **生成查询 embedding**：将输入的 task 描述文本通过 Jina API 生成 embedding 向量。
2. **加载 pkl 文件**：从 `~/.claude/learn-once/index/embeddings.pkl` 加载 `embedding_text` 和 `embedding` 数组。
3. **矩阵相似度运算**：
   - 将查询向量 reshape 为 `(1, D)` 形状
   - 计算查询向量与 pkl 中所有向量的余弦相似度
   - 使用 numpy 矩阵运算：`scores = (query @ embedding.T) / (norm_query * norm_embedding)`
   - 得到一个 shape 为 `(N,)` 的相似度数组，每个元素对应 `embedding_text` 中同索引位置的文本
4. **按相似度排序**：对 `(embedding_text, score)` 对按 score 降序排序。
5. **查找文件路径**：对排序后的每个 `embedding_text`，在 meta.json 中查找对应的 `file_path`。
6. **按 file\_path 去重**：同一条轨迹可能有多个 embedding\_text（如 index\_text 和 task\_text），去重时保留相似度最高的那个。
7. **返回 top\_k**：取去重后的前 top\_k 个结果，返回 `[(file_path_1, score_1), (file_path_2, score_2), ...]`。

### 4.2 余弦相似度矩阵运算

```python
import numpy as np

def cosine_similarity_matrix(query: np.ndarray, embeddings: np.ndarray) -> np.ndarray:
    """
    计算查询向量与多个向量的余弦相似度
    
    Args:
        query: shape (D,) 或 (1, D)
        embeddings: shape (N, D)
    
    Returns:
        shape (N,) 的相似度数组
    """
    # 归一化
    query_norm = np.linalg.norm(query)
    emb_norms = np.linalg.norm(embeddings, axis=1)
    
    # 矩阵乘法计算点积
    if query.ndim == 1:
        query = query.reshape(1, -1)
    dot_products = (query @ embeddings.T).flatten()
    
    # 余弦相似度
    similarities = dot_products / (query_norm * emb_norms)
    return similarities
```

### 4.3 脚本用法

```bash
# 召回最相似的 5 条轨迹
python scripts/python/recall_trajectory.py "把本地 docx 文件上传到飞书知识库"

# 指定 top_k
python scripts/python/recall_trajectory.py "如何设计 agent team 的团队结构" --top-k 3

# 输出 JSON 格式
python scripts/python/recall_trajectory.py "飞书知识库上传" --top-k 5 --json
```

### 4.4 脚本路径约定

- **脚本位置**：`scripts/python/recall_trajectory.py`
- **pkl 文件位置**：`~/.claude/learn-once/index/embeddings.pkl`
- **meta.json 位置**：`~/.claude/learn-once/meta/meta.json`

## 5. 文件总览

| 文件                                              | 职责                                    |
| ----------------------------------------------- | ------------------------------------- |
| `docs/trajectory-format-mvp.md`                 | 定义轨迹 Markdown 的格式规范（权威源）              |
| `docs/embedding.md`                             | 定义 Jina Embedding API 的调用方式           |
| `docs/index-db-schema.md`（本文件）                  | 定义 meta.json 和 pkl 的格式，以及入库/召回流程      |
| `scripts/python/ingest_trajectory.py`           | 入库脚本：Markdown → meta.json + pkl       |
| `scripts/python/recall_trajectory.py`           | 召回脚本：task 描述 → \[(file\_path, score)] |
| `~/.claude/learn-once/config.json`          | 配置文件，存放 JINA\_API\_KEY 等配置            |
| `~/.claude/learn-once/meta/meta.json`       | 元信息聚合文件                               |
| `~/.claude/learn-once/index/embeddings.pkl` | 向量存储文件                                |
| `~/.claude/learn-once/trajectories/*.md`    | 轨迹 Markdown 文件（权威源）                   |

