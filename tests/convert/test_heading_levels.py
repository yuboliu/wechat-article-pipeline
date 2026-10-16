# -*- coding: utf-8 -*-
"""章节层级重建 / 目录块重排的回归测试（纯标准库）。

跑法（在 skill 目录下）：
    python -m unittest discover -s tests -v

覆盖 `rebuild_headings()`（pitfalls #24）与 `rebuild_toc()`。
这两条规则改错的代价是**整篇大纲错乱**，改前务必先跑这里，再拿真实文章重跑回归。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import to_obsidian as m  # noqa: E402


def heads(text):
    """取重建后的标题行。"""
    out, _notes = m.rebuild_headings(text)
    return [ln for ln in out.split("\n") if ln.startswith("#")]


class TestClassify(unittest.TestCase):
    def test_numbering_kinds(self):
        self.assertEqual(m.classify_head_number("1 容器平台网络模型"), ("int", 2))
        self.assertEqual(m.classify_head_number("1.1 容器网络概述"), ("dot", 3))
        self.assertEqual(m.classify_head_number("1.2.1 协议栈"), ("dot", 4))
        self.assertEqual(m.classify_head_number("01安全问题"), ("two", None))
        self.assertEqual(m.classify_head_number("01 安全问题"), ("two", None))
        self.assertEqual(m.classify_head_number("Underlay网络"), ("plain", None))
        # 编号后没有分隔符、也不是两位编号 -> 不是标题编号（防「802.1Q标准」）
        self.assertEqual(m.classify_head_number("802.1Q标准"), ("plain", None))


class TestBoldFilter(unittest.TestCase):
    def test_heading_like(self):
        self.assertTrue(m.bold_can_be_head("需求分析"))
        self.assertTrue(m.bold_can_be_head("Underlay网络"))

    def test_not_heading_like(self):
        self.assertFalse(m.bold_can_be_head("对于 DNS over HTTPS 平台建设，应重点考虑以下技术建议："))
        self.assertFalse(m.bold_can_be_head("以上内容仅供参考。"))
        self.assertFalse(m.bold_can_be_head("图1 网络架构示意图"))
        self.assertFalse(m.bold_can_be_head("很长很长的一段加粗文字" * 8))


class TestRebuildHeadings(unittest.TestCase):
    def test_numbered_bold_lines_get_levels(self):
        text = "\n\n".join(["**1 甲**", "**1.1 乙**", "**1.2.1 丙**", "**1.2.2 丁**"])
        self.assertEqual(heads(text), ["## 1 甲", "### 1.1 乙", "#### 1.2.1 丙", "#### 1.2.2 丁"])

    def test_unnumbered_bold_under_numbered_section(self):
        text = "\n\n".join(["**1.2.2 穿越方式**", "**Underlay网络**", "正文", "**Overlay网络**"])
        self.assertEqual(heads(text), ["#### 1.2.2 穿越方式", "##### Underlay网络", "##### Overlay网络"])

    def test_top_level_plain_and_two_digit(self):
        """F5 那篇的形态：需求分析(##) -> 01安全问题(###) -> 02(###) -> 架构设计(##)"""
        text = "\n\n".join(["**需求分析**", "**01安全问题**", "**02隐私问题**", "**架构设计**"])
        self.assertEqual(heads(text), ["## 需求分析", "### 01安全问题", "### 02隐私问题", "## 架构设计"])

    def test_existing_unnumbered_heading_kept(self):
        """抓取器已定级的无编号标题（思科那篇）保持 ##，不被降级/升级。"""
        text = "\n\n".join(["## AI推理流量四大核心特征", "正文", "## 总结"])
        self.assertEqual(heads(text), ["## AI推理流量四大核心特征", "## 总结"])

    def test_existing_heading_is_relevelled_by_numbering(self):
        """抓取器把多级标题压平成一堆 ##，这里按编号重新拉开。"""
        text = "\n\n".join(["## 1 甲", "## 1.1 乙", "## 1.1.1 丙"])
        self.assertEqual(heads(text), ["## 1 甲", "### 1.1 乙", "#### 1.1.1 丙"])

    def test_bold_sentence_and_caption_are_not_promoted(self):
        text = "\n\n".join(["**对于 DNS over HTTPS 平台建设，应重点考虑以下技术建议：**", "**图1 架构图**"])
        self.assertEqual(heads(text), [])

    def test_code_fence_is_untouched(self):
        text = "```\n**1 不是标题**\n```"
        self.assertEqual(heads(text), [])

    def test_h1_is_untouched(self):
        text = "# 文章标题\n\n**1 甲**"
        self.assertEqual(heads(text), ["# 文章标题", "## 1 甲"])


class TestRebuildToc(unittest.TestCase):
    TOC = ("**1 容器平台网络模型**1.1 容器网络概述1.2 容器网络分类介绍1.2.1 协议栈"
           "1.2.2 穿越方式1.3 总结**2 基于Docker网络基础和实现原理**3 Kubernetes网络场景分析"
           "3.1 容器到容器的通信4.2.1 Flannel4.2.2 OVS")

    def test_mangled_toc_becomes_nested_list(self):
        text = "**目录**\n" + self.TOC
        notes = []
        out = m.rebuild_toc(text, notes)
        self.assertEqual(notes, ["重排目录块为 11 条嵌套列表"])
        body = out
        self.assertIn("- 1 容器平台网络模型", body)
        self.assertIn("  - 1.1 容器网络概述", body)
        self.assertIn("    - 1.2.1 协议栈", body)
        self.assertIn("    - 4.2.1 Flannel", body)

    def test_short_line_is_not_touched(self):
        text = "**目录**\n**1 甲**1.1 乙1.2 丙"
        notes = []
        self.assertEqual(m.rebuild_toc(text, notes), text)
        self.assertEqual(notes, [])

    def test_line_without_toc_heading_is_not_touched(self):
        notes = []
        self.assertEqual(m.rebuild_toc(self.TOC, notes), self.TOC)
        self.assertEqual(notes, [])


class TestFoldEmptyHeads(unittest.TestCase):
    """「大节标题后面一个字都不写」的折叠规则（pitfalls #26）。

    真实样本：「基于基础网络的SDN组网原理分析」—— 大节与小节在 HTML 里
    字号、加粗、有没有编号**全都一样**，只能靠「后面有没有正文」判断。
    """

    @staticmethod
    def folded(text):
        out, _notes = m.fold_empty_heads(text)
        return [ln for ln in out.split("\n") if ln.startswith("#")]

    def test_empty_chapter_head_folds_children(self):
        text = "\n\n".join([
            "## SDN VBC控制平面",          # 后面直接进下一行标题 -> 空章标题
            "## GoBGP消息同步机制",
            "正文内容",
            "### 01GoBGP speaker和RS-Node",
            "正文内容",
            "## SDN VBC 数据平面",         # 后面紧跟编号子节 -> 新的一章
            "正文内容",
            "### 01同VxNet同Hyper通信（二层）",
        ])
        self.assertEqual(self.folded(text), [
            "## SDN VBC控制平面",
            "### GoBGP消息同步机制",
            "#### 01GoBGP speaker和RS-Node",
            "## SDN VBC 数据平面",
            "### 01同VxNet同Hyper通信（二层）",
        ])

    def test_child_already_deeper_is_not_pushed_further(self):
        """折叠量按**差值**算，不是无条件 +1（pitfalls #35）。

        真实样本：「不管你是运维还是开发，微服务这些你得知道!」的
        `## 四、总结` + `### 何谓微服务` —— 后者的 `###` 是 Word 的 `<h4>` 上移来的，
        本来就比空章标题深一级；再 +1 会跳级成 `####`（`##` 直跳 `####`）。
        """
        text = "\n\n".join(["## 四、总结", "### 何谓微服务", "正文内容"])
        self.assertEqual(self.folded(text), ["## 四、总结", "### 何谓微服务"])

    def test_head_with_body_is_not_folded(self):
        text = "\n\n".join(["## 甲", "这里有一段正文。", "## 乙", "正文"])
        self.assertEqual(self.folded(text), ["## 甲", "## 乙"])

    def test_image_and_caption_do_not_count_as_body(self):
        text = "\n\n".join(["## 甲", "![[images/a.png]]", "图1 示意图", "## 乙", "正文"])
        self.assertEqual(self.folded(text), ["## 甲", "### 乙"])

    def test_fenced_headings_are_untouched(self):
        """围栏里的 `##` 不算标题 —— 不能被当成「下一个标题」参与折叠。"""
        text = "## 甲\n\n```\n## 乙\n```"
        out, _notes = m.fold_empty_heads(text)
        self.assertEqual(out, text)

    def test_single_head_is_noop(self):
        text = "## 只有一章"
        self.assertEqual(self.folded(text), ["## 只有一章"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
