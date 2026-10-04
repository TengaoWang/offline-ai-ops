# 便携包构建与验收

构建过程不会联网、下载模型或安装全局依赖。准备好对应平台的便携 Python、Ollama 或 llama.cpp 运行时、模型文件和已经发布的 `kb/` 后运行：

```bash
python scripts/build_portable.py \
  --platform macos \
  --backend llama.cpp \
  --python-runtime /path/to/python-runtime \
  --backend-runtime /path/to/llama-runtime \
  --models /path/to/models \
  --kb-root /path/to/kb \
  --output /new/path/offline-ai-ops-macos-llama
```

llama.cpp 的模型目录必须包含 `chat.gguf` 和 `embed.gguf`。Ollama 模型目录必须是可离线复制的 `manifests/`、`blobs/` 存储。构建完成后运行：

```bash
python scripts/verify_portable.py /new/path/offline-ai-ops-macos-llama
```

macOS 使用 `start_macos.command`，Windows 使用 `start_windows.cmd`。启动器只绑定回环地址，不运行下载器或包管理器。日志写入包内 `logs/`。

FR-10 只有在干净 Windows 10+ 与 macOS 12+ 上分别对 Ollama、llama.cpp 四组包完成无网启动并保存记录后才算通过。仓库内的脚本通过不等于实机验收通过。
