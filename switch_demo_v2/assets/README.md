# 内嵌手册资产

运行包需要在本目录保留 `华为S系列园区交换机维护宝典.pdf`。程序通过相对路径读取它，因此整个 `switch_demo_v2/` 目录可以移动到其他电脑。

本次核对的文件信息：

- 文件大小：69,303,713 字节
- SHA-256：`FE9E2CE0CECD9A2542D492B91DFFB05C86C56B99E9299BF501E0A36263C61B23`

PDF 受项目 `.gitignore` 排除，不会随普通 Git 提交上传；制作线下演示包时需连同本地 PDF 一并打包，并由项目方确认相应的使用与分发权限。

`manual-pages/` 保存从该 PDF 生成的引用页预览，确保目标电脑即使没有可嵌入的 PDF 浏览器插件，小窗也能显示原件对应页面。需要重新生成时，在 `offline-ai-ops` 目录执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 switch_demo_v2\render_manual_pages.py
```
