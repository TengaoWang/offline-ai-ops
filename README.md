# offline-ai-ops：离线 AI 机房运维助手

GGboys · HacKU 2026 · Deep Technology Problem Statement 4（The Capability That Hasn't Travelled）

在断网、资料不能外传的机房里，让现场人员拥有一位「带着厂商手册的资深同事」：
根据故障描述选出排查技能包、在手册里检索依据并给出带出处的回答。模型与知识库全部在本机运行。

## 目录

| 目录 | 内容 | 状态 |
|---|---|---|
| [`llm/`](llm/) | **模型与知识库接口**：`route` / `retrieve` / `ask` / `chat` / `health`，供引擎和界面调用 | 可用 |
| [`eval/`](eval/) | 技能路由的测试数据与评测脚本 | 可用 |
| [`tests/`](tests/) | `llm` 接口的单元测试（不需要 Ollama） | 9 项通过 |
| `kb/docs/` | 厂商手册放这里（不进 git） | — |

## 快速开始

```bash
# 1. 本地模型（只需联网一次）
brew install ollama            # Windows：从 ollama.com 下载安装包
brew services start ollama     # 或另开终端运行 ollama serve
ollama pull qwen3:8b           # 约 5GB

# 2. Python 环境
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt

# 3. 手册放进 kb/docs/ 后建索引，再检查是否就绪
.venv/bin/python -m llm ingest
.venv/bin/python -m llm health

# 4. 试用
.venv/bin/python -m llm route "nginx 起不来"
.venv/bin/python -m llm ask "交换机 CPU 占用率高怎么处理"
```

没有模型时可以先用 mock 模式开发界面：`LLM_MOCK=1 .venv/bin/python -m llm ask "随便问"`。
接口的参数、返回格式和配置见 [`llm/README.md`](llm/README.md)。

## 当前结果

| 项目 | 结果 | 条件 |
|---|---|---|
| 技能路由准确率 | 97.7%（85/87），JSON 合法率 100% | Qwen3-8B 基座 + 提示词（Ollama），不微调；MacBook Air M4 16GB |
| 技能路由耗时 | 平均 0.70 秒/条 | 同上 |
| 手册检索 | 7 个试测问题中 5 个正确章节排第 1；「接口一直是 down」类问题排第 4、第 7 | 《华为 S 系列园区交换机维护宝典》第 25 版，BM25 |

测试集为模板生成的 87 条（测试集中的说法训练与调试时未出现），样本量小，不代表真实场景的普遍准确率。

## 手册

演示使用《华为 S 系列园区交换机维护宝典》（文档版本 25，发布日期 2026-08-31，华为技术有限公司），
2504 页。其版权声明禁止复制传播，因此不放进仓库，请线下或通过 SSD 传递后放入 `kb/docs/`。

## 下一步

- 提高「接口 Down / VLAN 不通」类问题的检索准确度：同义词扩展、向量检索（bge-m3）
- 建立带标准章节的检索测试集，量化每次改动的效果
- 缩短 `ask` 的耗时（交给模型的片段更短）
