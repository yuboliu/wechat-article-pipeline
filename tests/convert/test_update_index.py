# -*- coding: utf-8 -*-
"""索引更新（scripts/update_index.py）的回归测试（纯标准库）。

这里守的是**落位正确**与**幂等**：
  * 已存在的笔记重跑不能变成两行；
  * 有分组结构的段落要落进对应 `**小组**`，平铺段落不要为一个新二级单开小组
    （那会在图谱里造孤岛叶节点）；
  * `主题/行业/银行` 这类补充语境标签不能拿来决定插到哪个段落。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts"))
import update_index as ui  # noqa: E402

FIXTURE = """---
tags:
  - 类型/索引
---
# 知识库索引

## 一、标签体系

### 1. 主题 `主题/…`

| 一级 | 二级标签（覆盖笔记数） |
| ---- | ---- |
| `主题/AI` | 智能体 2 · RAG 1 |
| `主题/网络` | DNS 1 · SDN 1 |
| `主题/安全` | 网络安全 1 |
| `主题/行业` | 银行 1 |

### 2. 类型 `类型/…`

| 标签 | 数 |
| ---- | ---- |
| `类型/技术教程` | 2 |
| `类型/方案实践` | 1 |

### 3. 来源 `来源/…`

`来源/微信公众号` 3 · `来源/个人整理` 1

## 二、按主题导航

### AI

**智能体与上下文工程**
- [[已有笔记A|笔记 A]] — 摘要 A

**RAG 与知识图谱**
- [[已有笔记B|笔记 B]] — 摘要 B

### 网络

**DNS**
- [[已有笔记C|笔记 C]] — 摘要 C

**SDN / IPv6 / 广域网**
- [[已有笔记D|笔记 D]] — 摘要 D

### 安全

- [[已有笔记E|笔记 E]] — 摘要 E

---

## 三、索引维护

- 新增笔记后补齐标签。
"""

TAGS_NET_DNS = ["主题/网络/DNS", "类型/技术教程", "来源/微信公众号"]


class IndexCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = Path(self.tmp) / "【91】知识库索引.md"
        self.path.write_text(FIXTURE, encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self):
        return self.path.read_text(encoding="utf-8")

    def run_update(self, tags, title, summary="一句话", **kw):
        return ui.update_index(self.path, tags, title, summary=summary, **kw)

    def lines(self):
        return [ln.strip() for ln in self.read().split("\n")]


class TestInsertPosition(IndexCase):
    def test_into_existing_subgroup(self):
        self.run_update(TAGS_NET_DNS, "新DNS文章")
        lines = self.lines()
        new_i = lines.index("- [[新DNS文章|新DNS文章]] — 一句话")
        c_i = lines.index("- [[已有笔记C|笔记 C]] — 摘要 C")
        d_i = lines.index("- [[已有笔记D|笔记 D]] — 摘要 D")
        # 落在 DNS 小组内：在 C 之后、下一个小组标题 D 之前
        self.assertEqual(new_i, c_i + 1)
        self.assertLess(new_i, d_i)

    def test_new_subgroup_in_grouped_section(self):
        self.run_update(["主题/网络/K8s网络", "类型/技术教程"], "新K8s文章")
        lines = self.lines()
        self.assertIn("**K8s网络**", lines)
        new_i = lines.index("- [[新K8s文章|新K8s文章]] — 一句话")
        self.assertLess(lines.index("**K8s网络**"), new_i)
        # 仍在「网络」段落内，没有跑到「安全」后面
        self.assertLess(new_i, lines.index("### 安全"))

    def test_flat_section_does_not_create_group(self):
        # 安全段落是平铺列表 → 不该为 网络安全 单开一个 **小组**
        self.run_update(["主题/安全/网络安全", "类型/方案实践"], "新安全文章")
        lines = self.lines()
        self.assertNotIn("**网络安全**", lines)
        new_i = lines.index("- [[新安全文章|新安全文章]] — 一句话")
        e_i = lines.index("- [[已有笔记E|笔记 E]] — 摘要 E")
        self.assertEqual(new_i, e_i + 1)

    def test_secondary_theme_does_not_drive_placement(self):
        # 主题/行业/银行 不能决定段落；应由 主题/网络/DNS 定到「网络」
        tags = ["主题/行业/银行", "主题/网络/DNS", "类型/方案实践", "来源/微信公众号"]
        self.run_update(tags, "银行DNS文章")
        lines = self.lines()
        new_i = lines.index("- [[银行DNS文章|银行DNS文章]] — 一句话")
        self.assertLess(lines.index("### 网络"), new_i)
        self.assertLess(new_i, lines.index("### 安全"))

    def test_unknown_theme_goes_to_fallback_section(self):
        self.run_update(["主题/玄学/占卜", "类型/技术教程"], "无法归类的文章")
        lines = self.lines()
        self.assertIn("### 其他", lines)
        self.assertIn("- [[无法归类的文章|无法归类的文章]] — 一句话", lines)


class TestIdempotent(IndexCase):
    def test_second_run_is_noop(self):
        self.run_update(TAGS_NET_DNS, "新DNS文章")
        first = self.read()
        self.run_update(TAGS_NET_DNS, "新DNS文章")
        self.assertEqual(first, self.read())

    def test_updates_summary_in_place(self):
        self.run_update(TAGS_NET_DNS, "新DNS文章", summary="旧摘要")
        self.run_update(TAGS_NET_DNS, "新DNS文章", summary="新摘要")
        text = self.read()
        self.assertEqual(text.count("[[新DNS文章|"), 1, "不应该出现两行")
        self.assertIn("— 新摘要", text)
        self.assertNotIn("旧摘要", text)

    def test_existing_manual_entry_matched_by_title(self):
        # 库里已有条目（显示名被缩写过）→ 应按 wikilink 目标匹配到，不新增
        self.run_update(["主题/AI/RAG", "类型/技术教程"], "已有笔记B", summary="改写后的摘要")
        text = self.read()
        self.assertEqual(text.count("[[已有笔记B|"), 1)
        self.assertIn("[[已有笔记B|笔记 B]] — 改写后的摘要", text)


class TestRender(unittest.TestCase):
    def test_link_without_display_uses_title(self):
        self.assertEqual(ui.render_line("标题", None, "摘要"), "- [[标题|标题]] — 摘要")

    def test_pipe_is_escaped(self):
        line = ui.render_line("A|B", None, "摘要")
        self.assertIn("\\|", line)

    def test_no_summary_omits_dash(self):
        self.assertEqual(ui.render_line("标题", None, None), "- [[标题|标题]]")


class TestTagRegistration(IndexCase):
    def test_registered_subtag_not_flagged(self):
        # 表格里二级是裸名（`DNS 1`），不该被误报成未登记
        self.assertEqual(ui.unregistered_tags(self.read(), TAGS_NET_DNS), [])

    def test_brand_new_subtag_flagged(self):
        miss = ui.unregistered_tags(self.read(), ["主题/网络/K8s网络"])
        self.assertEqual(miss, ["主题/网络/K8s网络"])

    def test_freeform_tag_ignored(self):
        self.assertEqual(ui.unregistered_tags(self.read(), ["随便一个词"]), [])


class TestDecidePosition(unittest.TestCase):
    def setUp(self):
        import json
        p = Path(HERE).parent.parent / "references" / "index_layout.json"
        self.layout = json.loads(p.read_text(encoding="utf-8"))

    def test_primary_theme_wins(self):
        sec, grp, _ = ui.decide_position(self.layout, ["主题/AI/RAG"])
        self.assertEqual((sec, grp), ("AI", "RAG 与知识图谱"))

    def test_cloud_and_cloudnative_share_section(self):
        sec, _, _ = ui.decide_position(self.layout, ["主题/云原生/容器"])
        self.assertEqual(sec, "云与云原生")

    def test_manual_override(self):
        sec, grp, _ = ui.decide_position(self.layout, ["主题/AI/RAG"],
                                         section="网络", subgroup="DNS")
        self.assertEqual((sec, grp), ("网络", "DNS"))


if __name__ == "__main__":
    unittest.main()
