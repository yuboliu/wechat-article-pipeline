# -*- coding: utf-8 -*-
"""文首重复标题 banner / 加粗小标题配对 / 空章折叠 的回归测试（纯标准库）。

跑法（在 skill 目录下）：
    python -m unittest discover -s tests -v

覆盖 `strip_dup_title_head()`、`normalize_bold_headings()`（pitfalls #28），
以及 `fold_empty_heads()` 里「后面紧跟带编号小节时不折叠」的分支。
这几条规则改错的代价是**大纲错乱或整块内容被吃掉**，改前务必先跑这里。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import to_obsidian as m  # noqa: E402


TITLE = "网络原来如此之G行数据中心分布式域名解析系统设计"

BANNER = """---
![](images/img_001.png)**网络原来如此之**

**G行数据中心分布式域名解析系统设计**

![](images/img_002.png)![](images/img_003.png)

当金融机构逐步向多数据中心架构演进时。
"""


class TestStripDupTitleHead(unittest.TestCase):
    def test_banner_removed(self):
        out = m.strip_dup_title_head(BANNER, TITLE)
        self.assertEqual(out, "当金融机构逐步向多数据中心架构演进时。\n")

    def test_non_duplicate_head_untouched(self):
        # 加粗文字拼起来 != H1：一个字都不动（SDN 那篇的文首就长这样）
        text = "**SDN VBC控制平面**\n\n**GoBGP消息同步机制**\n\n![](images/img_001.png)\n\n图1 示意\n"
        self.assertEqual(m.strip_dup_title_head(text, "基于基础网络的SDN组网原理分析"), text)

    def test_lead_paragraph_untouched(self):
        # `**【导读】**本文…` 是正文引子，不是 banner
        text = "**【导读】**本文帮助读者系统了解容器云网络架构。\n\n**目录**\n"
        self.assertEqual(m.strip_dup_title_head(text, "容器云平台网络架构"), text)

    def test_plain_lead_untouched(self):
        text = "当金融机构逐步向多数据中心架构演进时。\n"
        self.assertEqual(m.strip_dup_title_head(text, TITLE), text)


def norm(text):
    out, _notes = m.normalize_bold_headings(text)
    return out


class TestNormalizeBoldHeadings(unittest.TestCase):
    def test_join_split_digits(self):
        self.assertEqual(norm("**0****1****动静区分**"), "**01 动静区分**")

    def test_bare_chapter_number_normalized(self):
        self.assertEqual(norm("**0****1**"), "**01**")

    def test_chapter_title_and_section_on_one_line(self):
        out = norm("**策略设计****01****智能解析机制**")
        self.assertIn("**策略设计**", out)
        self.assertIn("**01 智能解析机制**", out)

    def test_section_title_glued_to_body(self):
        out = norm("**03****域名解析时延**域名解析作为网络访问的第一步，必然会消耗一定的时延。")
        self.assertTrue(out.startswith("**03 域名解析时延**\n\n"))
        self.assertIn("域名解析作为网络访问的第一步", out)

    def test_dotted_section_glued_to_body(self):
        # `**1. SSL 卸载。**正文…` —— 加粗块把标题那句的句号也包进去了，要一并剥掉
        out = norm("**1. SSL 卸载。**实现对 DoH 请求的 SSL 卸载，可构建弹性的 SSL 卸载池实现。")
        self.assertTrue(out.startswith("**1. SSL 卸载**\n\n"))

    def test_list_item_and_emphasis_untouched(self):
        for text in (
            "- **负载分担**：递归服务器直接面对客户，访问压力较大。",
            "**DNS flood攻击**，主要通过短时间发起大量的DNS请求。",
        ):
            self.assertEqual(norm(text), text)

    def test_toc_line_untouched(self):
        # 容器云的目录被压成一行：`1` 开头的加粗块不能被当小节标题拆掉
        text = "**1 容器平台网络模型**1.1 容器网络概述1.2 容器网络分类介绍"
        self.assertEqual(norm(text), text)

    def test_fenced_block_untouched(self):
        text = "```\n**0****1****甲**\n```\n"
        self.assertEqual(norm(text), text)


class TestFoldEmptyHeads(unittest.TestCase):
    def test_numbered_children_not_folded(self):
        # 紧跟的是带编号小节 -> 层级已由编号定好，不该再折（G行那篇的 04 章）
        text = "## 域名安全设计\n\n### 01 安全威胁防御\n\n正文。\n\n## 总结\n\n正文。\n"
        out, notes = m.fold_empty_heads(text)
        self.assertEqual(out, text)
        self.assertEqual(notes, [])

    def test_plain_children_still_folded(self):
        # 紧跟的是无编号标题 -> 老行为保持不变（SDN 那篇）
        text = "## SDN VBC控制平面\n\n## GoBGP消息同步机制\n\n### 01 x\n\n正文。\n"
        out, _notes = m.fold_empty_heads(text)
        self.assertIn("### GoBGP消息同步机制", out)


class TestDottedSectionLevel(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(m.classify_head_number("1. SSL 卸载"), ("dot1", 3))
        self.assertEqual(m.classify_head_number("1.2.1 协议栈"), ("dot", 4))
        self.assertEqual(m.classify_head_number("1 容器平台网络模型"), ("int", 2))
        self.assertEqual(m.classify_head_number("01 安全问题"), ("two", None))
        self.assertEqual(m.classify_head_number("总结"), ("plain", None))

    def test_int_is_not_split_head(self):
        # `1 标题`（无点）是顶级章节写法，不能被当成小节从正文里拆出来
        self.assertIsNone(m.SPLIT_HEAD_RE.match("1 容器平台网络模型"))

    def test_dot1_does_not_raise_num_depth(self):
        # `1.` 小节之后的**无编号章标题**必须留在 ##，不能被 num_depth 顶到 ####
        text = "## 架构设计\n\n**1. SSL 卸载**\n\n正文。\n\n**架构分析**\n\n正文。\n"
        out, _notes = m.rebuild_headings(text)
        self.assertIn("### 1. SSL 卸载", out)
        self.assertIn("## 架构分析", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
