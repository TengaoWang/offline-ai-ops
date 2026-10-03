"""生成测试用的迷你手册 PDF（3 页，带书签目录），用于验证建索引、页码和章节是否正确。

内容为测试专用的简化示例，不是真实厂商手册。运行：python tests/make_fixture.py
"""

from pathlib import Path

import pymupdf

PAGES = [
    ("1 VLAN 配置", 1, "配置接口链路类型为 Trunk：\nsystem-view\ninterface GigabitEthernet 0/0/1\n"
                       "port link-type trunk\nport trunk allow-pass vlan 10 20\nquit"),
    ("2 故障处理", 1, "本章介绍常见故障的排查方法。"),
    ("2.1 接口无法 Up", 2, "使用 display interface brief 查看接口状态。\n"
                         "如果接口显示 administratively down，说明接口被手动关闭，\n"
                         "进入接口视图执行 undo shutdown 恢复。"),
]


def build(path: Path) -> Path:
    doc = pymupdf.open()
    toc = []
    for page_no, (title, level, body) in enumerate([PAGES[0], PAGES[1], PAGES[2]], start=1):
        page = doc.new_page()
        page.insert_text((50, 72), title, fontname="china-s", fontsize=16)
        page.insert_text((50, 110), body, fontname="china-s", fontsize=11)
        toc.append([level, title, page_no])
    doc.set_toc(toc)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


if __name__ == "__main__":
    print(build(Path(__file__).parent / "fixtures" / "docs" / "测试手册.pdf"))
