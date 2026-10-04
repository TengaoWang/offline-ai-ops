# U 盘便携交付计划（目标目录 F:\GGboys）

> 对应需求文档 1.0 的 FR-10（U 盘即插即用）、3.1/3.2 双后端与纯文件架构、第 5 节非功能需求。本文档基于 2026-10-04 本机资产实测与现有代码审查。

## 1. 结论

**可行，且比预想更省事。** 代码侧的便携打包、双后端、启动器、知识库快照、完整性校验都已就位并有自动化测试覆盖（tests/test_packaging.py）。本机已具备组装所需的大部分大件资产：Ollama 0.35.1、qwen3:8b、bge-m3，且两个模型 blob 均为 GGUF 格式，Ollama 安装目录自带 llama-server.exe。因此 llama.cpp 零安装版可以就地取材完成，几乎不需要额外联网下载。

当前真正的阻塞不是代码，而是三件不在 git 里、需要线下准备的资产：便携 Python 运行时、已发布的 KB 快照（current.json）、以及真实厂商手册。补上这三件，再修掉两处配置不一致，即可在 F:\GGboys 组装出可启动的 U 盘。

## 2. 本机资产盘点（2026-10-04 实测）

| 资产 | 状态 | 位置 / 规模 |
|---|---|---|
| 目标目录 F:\GGboys | 已存在，为空 | F 盘剩余 115.49 GB |
| Ollama | 已安装 0.35.1 | C:\Users\WangTengao\AppData\Local\Programs\Ollama\ |
| 模型 qwen3:8b | 已下载 | blob 4.87 GB，magic=GGUF |
| 模型 bge-m3 | 已下载 | blob 1.08 GB，magic=GGUF |
| Ollama 模型存储 | blobs/ + manifests/ 完整 | 合计约 6.4 GB |
| llama-server.exe | Ollama 自带 | …\Ollama\lib\ollama\llama-server.exe（0.5.0-dev） |
| 便携 Python | 缺失 | runtime/ 为空（被 .gitignore 排除） |
| 已发布 KB 快照 | 缺失 | kb/ 只有开发态 index.db + 测试手册，无 current.json |
| 独立 llama.cpp | 未安装 | 可复用 Ollama 自带的 llama-server.exe 代替 |

## 3. 代码侧能力（已具备）

- 打包：scripts/build_portable.py 把 app、便携 Python、后端、模型、KB 组装成目录并生成 SHA256SUMS.json；组装不联网、不下载。
- 校验：scripts/verify_portable.py 逐文件核对 SHA-256 与关键文件存在性。
- 启动器：scripts/start_windows.ps1 / scripts/start_macos.command，用相对路径定位，启动前查端口、就绪后自动开浏览器，全程只绑定 127.0.0.1。
- 双后端：llm/client.py 同一套代码同时支持 Ollama 与 llama.cpp，由 LLM_BACKEND / LLM_EMBED_BACKEND 切换，标准库实现、不走系统代理。
- 向量库：纯文件 SQLite（FTS5 BM25 + vectors 表存 float32），见 llm/rag.py，比需求文档早先设想的 Chroma 更轻、更便携。
- KB 快照：不可变 revisions/ + current.json 原子发布，见 llm/kb.py，天然适合整目录拷贝。

## 4. 后端选型建议

**默认交付 llama.cpp 零安装版，Ollama 版仅作开发/备选。** 理由：

| 维度 | llama.cpp（推荐） | Ollama |
|---|---|---|
| 目标机要求 | 真零安装，单可执行 + CPU DLL | 需带完整 lib/ollama（含 CUDA/ROCm/Vulkan 约 3 GB），臃肿 |
| 体积 | 后端约 45 MB + GGUF 约 6 GB | 后端约 3 GB + blobs/manifests 约 6.4 GB |
| 数据不出盒 | 只写包内 logs/，无用户目录写入 | ollama serve 会在 ~/.ollama 写 id/history，存在泄漏风险 |
| 来源 | 复用 Ollama 自带 llama-server.exe | 现有安装目录直接复制 |
| 备注 | 需把 blob 重命名为 chat.gguf / embed.gguf | 需验证能否用 OLLAMA_HOME 全量重定向 |

## 5. 目标目录结构（F:\GGboys）

```
F:\GGboys\
  start_windows.cmd / start_windows.ps1   # 双击启动
  config\backend                          # 内容：llama.cpp
  runtime\python\                         # 便携 Python 3.12 + pymupdf/numpy/jieba/PyYAML
  backends\llama.cpp\                     # llama-server.exe + 必要 CPU DLL
  models\                                 # chat.gguf + embed.gguf
  kb\                                     # current.json + revisions\ + docs\
  app\                                    # engine/ llm/ ui/ skills/ scripts/
  logs\                                   # 运行日志
  SHA256SUMS.json                         # 完整性清单
```

## 6. TODO List

### 阶段 0 — 资产准备（阻塞项，缺一不可）

- [ ] T0-1 便携 Python：准备 Windows embeddable Python 3.12，装入 pymupdf、numpy、jieba、PyYAML 及对应原生 .pyd，放 runtime/python/。注意 .pyd 必须与 Python ABI/架构（x64）严格匹配。
- [ ] T0-2 llama.cpp 后端：从 Ollama lib/ollama/ 提取 llama-server.exe + CPU 侧依赖 DLL（libllama*.dll、ggml*.dll、ggml-cpu-*.dll、libomp.dll、libc++.dll、libunwind.dll、libwinpthread-1.dll），不打包 cuda_v* / rocm_v* / vulkan，验证脱离 Ollama 独立启动。
- [ ] T0-3 模型：把 qwen3:8b 与 bge-m3 的 blob 复制并重命名为 chat.gguf / embed.gguf；评估是否补充 qwen3:4b（8 GB CPU-only 目标机跑 8b 有 OOM 风险，见风险 R-2）。
- [ ] T0-4 KB 发布：上传真实华为 S5700 手册，python -m llm ingest 后走 publish() 生成 current.json + revisions/（当前 kb/ 无 current.json，build_portable.py 会因缺它直接退出）。

### 阶段 1 — 代码/配置修复

- [ ] T1-1 对齐模型名：config.py 默认 MODEL=qwen3:8b，而 start_windows.ps1 给 chat 打的 --alias qwen3:4b，两者不一致；需统一为实际部署模型，并在启动脚本显式导出 LLM_MODEL / LLM_EMBED_MODEL。
- [ ] T1-2 验证 llama-server 的 --alias 与 /v1/chat/completions 的 model 校验行为，确认请求名与 alias 不匹配时不会 404。
- [ ] T1-3 若换 4b：重跑 eval/eval_p0_quality.py 复验技能路由准确率（当前 97.7% 是 8b 基座）。

### 阶段 2 — 组装与校验

- [ ] T2-1 运行 build_portable.py --platform windows --backend llama.cpp --output F:\GGboys。
- [ ] T2-2 运行 verify_portable.py F:\GGboys，SHA-256 全部通过。
- [ ] T2-3 本机冒烟：从 F:\GGboys 双击启动，拔网线/关 Wi-Fi，走场景 A / B / D 全流程。

### 阶段 3 — 实机验收（对应 FR-10，脚本通过不等于验收通过）

- [ ] T3-1 干净 Windows 10+ × llama.cpp：无网、非管理员、U 盘路径启动，留记录。
- [ ] T3-2（可选）干净 macOS 12+ × llama.cpp 启动记录。
- [ ] T3-3（可选）Ollama 版双保险启动记录。
- [ ] T3-4 8 GB CPU-only 目标机的质量与单轮 ≤ 30 秒复验。
- [ ] T3-5 FR-1 物理断网出站连接记录；FR-7 至少 5 条结论逐条人工核对原手册页码。

## 7. 风险点

| 等级 | 风险 | 说明 | 对策 |
|---|---|---|---|
| 高 | R-1 便携 Python 原生依赖 | pymupdf、numpy 是二进制扩展，.pyd 必须与便携 Python ABI/架构匹配，是最大工作量 | 用官方 embeddable 包 + 预编译 wheel 定向安装；锁定版本并写进构建说明 |
| 高 | R-2 8 GB CPU-only 跑 8b OOM/超时 | qwen3:8b 加载约 5 GB，叠加 KV cache 易超 8 GB 门槛 | 默认切 qwen3:4b（约 3 GB），8b 仅作高性能机选项；切模型必须重跑 eval |
| 高 | R-3 KB 未发布 + 手册版权 | 当前无 current.json，真实手册受版权限制不进 git，只能线下传递 | T0-4 先发布再打包；用手册前确认分发授权 |
| 中 | R-4 模型名不一致（现成 bug） | config.py 默认 qwen3:8b vs 启动脚本 --alias qwen3:4b | T1-1 统一并显式导出 LLM_MODEL |
| 中 | R-5 Ollama 数据泄漏 | 若走 Ollama 方案，serve 会写 ~/.ollama（id/history），违背数据不出盒 | 验证 OLLAMA_HOME 全量重定向；否则只交付 llama.cpp 版 |
| 中 | R-6 换模型影响路由准确率 | 技能路由 97.7% 基于 8b，4b 可能下降 | 换 4b 前重跑 eval_p0_quality.py，低于阈值则保留 8b 或调整提示词 |
| 低 | R-7 U 盘盘符变化 | Windows 上 U 盘盘符不定 | 已用相对路径定位，无硬编码路径 |
| 低 | R-8 端口冲突 | 8765 / 8080 / 8081 被占用 | 已有 scripts/check_ports.py 启动前校验 |

## 8. 验收口径（对照 FR-10 与需求文档）

- 插入 U 盘，双击 start_windows.cmd，3 分钟内浏览器打开 UI（127.0.0.1:8765）。
- 全程零网络请求；日志、对话、向量库、技能库全部留在 U 盘内。
- 干净机器非管理员、无任何依赖即可运行。
- verify_portable.py 完整性校验通过；模型 / KB / 后端三件资产 SHA-256 与清单一致。

## 9. 范围决策（已确认 2026-10-04）

1. 平台：**仅交付 Windows 版（Win × llama.cpp）**。macOS 与 Ollama 版按范围豁免，不再作为本次交付项；FR-10 的验收口径以本决策为准。
2. 模型：维持 qwen3:8b（本机已就绪）；若 8 GB CPU-only 目标机实测超时/OOM，再切 qwen3:4b 并重跑 eval。
3. 手册：真实华为 S5700 手册受版权限制未入库，先用测试手册跑通链路，拿到手册后重新发布 KB。

## 9.1 开发提交时的 U 盘兼容要求（给全体开发者）

日常开发在电脑 git 仓库进行，最终由 `build_portable.py` 组装成 U 盘可运行产物。为不破坏 U 盘挂载能力，提交代码时请遵守以下红线：

1. **路径不写死**：一律用 `pathlib.Path` 和 `config.ROOT` 相对定位，禁止硬编码绝对路径（U 盘盘符、用户名、本机目录都不固定）。
2. **保持离线**：任何功能不得在启动或运行期访问外网；新增代码不得引入需要联网的调用。
3. **依赖进 requirements.txt**：便携 Python 只预装了 `requirements.txt` 里的包。新增第三方依赖必须同步加进去，否则 U 盘上跑不起来；且必须是 3.12 有预编译 wheel 的纯/稳定包。
4. **兼容 Python 3.12**：便携运行时是 3.12，避免使用更新版本才有的语法/API（`hashlib.file_digest` 这类 3.11+ 的可用）。
5. **跨平台**：本次只交付 Windows，但仍保持代码可移植（`os.name` 判断、`pathlib` 处理分隔符），不写死平台假设。
6. **新增顶层模块要登记**：若新增 `engine/`、`llm/`、`ui/` 之外的新顶层 Python 包，必须同步加进 `scripts/build_portable.py` 的 `APP_ITEMS`，否则不会被装进 U 盘。
7. **大文件不进 git**：模型、GGUF、便携 Python、后端二进制、KB 快照一律线下传递，不进 git；代码里引用它们用 `config.ROOT` 相对定位。
8. **改启动脚本守约**：改 `scripts/start_windows.ps1` / `start_macos.command` 时，保持只绑定 `127.0.0.1`、不下载、不装依赖；llama-server 的 `--alias` 必须与实际模型名一致。
9. **换行符**：遵守 `.gitattributes`（源码 LF、Windows 脚本 CRLF），避免产生行尾符假 diff。

## 10. 执行记录（2026-10-04 已完成）

- F 盘已格式化为 exFAT（卷标 GGboys），解除 FAT32 的 4 GB 单文件限制。
- 已组装到 `F:\GGboys`：app + 便携 Python 3.12 + llama.cpp 后端 + 模型（chat/embed）+ 已发布 KB，占用约 6.47 GB；`verify_portable.py` 通过（2305 文件，哈希一致）。
- 端到端冒烟通过：`/api/health` 返回 `rag_ready=true`、`backend=llama.cpp`、`index=true`（3 片段 + 3 向量）、`vector_ready=true`、`retrieval_mode=hybrid`、`errors=[]`；chat（qwen3:8b）与 embed（bge-m3）均正常推理。
- 过程中修复了 4 处 Windows/llama.cpp 便携化的实际阻塞：
  1. `llm/kb.py`：`publish()` 在 Windows 对只读文件 `os.fsync` 报 `Bad file descriptor` → 加 `os.name != "nt"` 判断。
  2. `llm/client.py`：llama.cpp 分支未禁用 qwen3 thinking，答案进 `reasoning_content` 而 `content` 为空 → 加 `/no_think`。
  3. `llm/config.py`：打包后 `ROOT` 指向 `app/`，KB 默认路径算错 → 加 `app` 目录检测抬升到 U 盘根。
  4. `scripts/start_windows.ps1` / `start_macos.command`：llama-server `--alias qwen3:4b` 与实际模型 8b 不一致 → 统一为 `qwen3:8b`。
- 当前 KB 用的是测试手册（真实华为 S5700 手册受版权限制，暂未入库）。
- P0-1 修复（数据不出盒）：前端会话 / Evidence / 技能回放原存浏览器 localStorage，现改为经 `/api/state` 落到 U 盘 `data/` 目录（后端 `config.DATA_DIR` + `ui/service.py` 读写 + `ui/static/app.js` 改用 fetch），`data/` 已加入 `.gitignore`。

## 11. 仍待完成

- 替换真实华为 S5700 手册后重新发布 KB 并重新打包。
- 干净 Windows 10+ × llama.cpp 无网、非管理员、U 盘路径启动记录（FR-10，仅 Win）。
- 8 GB CPU-only 目标机的质量与「单轮 ≤ 30 秒」复验；若换 `qwen3:4b`，必须重跑 `eval/eval_p0_quality.py`。
- P0-1 修复已实现并本地验证，待重新打包到 U 盘后做一轮回归验证。
