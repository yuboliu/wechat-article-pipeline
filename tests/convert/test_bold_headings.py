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

    def test_banner_title_split_across_lines(self):
        # `**前半` + 空行 + `后半**`：一对 `**` 被换行拆到两个段落（浅谈自动封禁 一篇）
        title = "浅谈网络安全纵深防御体系之自动封禁能力建设实践"
        text = (
            "![](images/img_001.jpeg)![](images/img_002.png)"
            "**浅谈网络安全纵深防御体系之\n\n自动封禁能力建设实践**\n\n**引言**\n\n正文。\n"
        )
        out = m.strip_dup_title_head(text, title)
        self.assertNotIn("浅谈网络安全纵深防御体系之", out)
        self.assertNotIn("img_001", out)
        # 紧跟的 `**引言**` 不能被当成 banner 的一部分吃掉
        self.assertIn("**引言**", out)
        self.assertIn("正文。", out)

    def test_banner_followed_by_bold_lead(self):
        # banner 拼完标题就收手：后面紧跟的加粗行（`**引言**`）不属于 banner
        title = "网络原来如此之G行数据中心分布式域名解析系统设计"
        text = (
            "**网络原来如此之****G行数据中心分布式域名解析系统设计**\n\n"
            "**引言**\n\n正文。\n"
        )
        out = m.strip_dup_title_head(text, title)
        self.assertIn("**引言**", out)
        self.assertIn("正文。", out)
        self.assertNotIn("网络原来如此之", out)

    def test_lead_bold_line_kept_when_banner_absent(self):
        # 没有 banner 时，正文首行的加粗小标题不能被动
        text = "**引言**\n\n正文。\n"
        self.assertEqual(m.strip_dup_title_head(text, TITLE), text)


class TestNormalizeBoldRuns(unittest.TestCase):
    """≥4 颗星号的「加粗粘连」归一（浅谈自动封禁 一篇的三种形态）。"""

    def run_it(self, text):
        return m.normalize_bold_runs(text, [])

    def test_list_item_four_stars_both_ends(self):
        self.assertEqual(
            self.run_it("- ****外部攻击告警量大，告警疲劳导致人工处置效率低下****"),
            "- **外部攻击告警量大，告警疲劳导致人工处置效率低下**",
        )

    def test_list_item_inner_four_stars(self):
        self.assertEqual(
            self.run_it("- ****高效性****：针对海量告警数据实时分级分类"),
            "- **高效性**：针对海量告警数据实时分级分类",
        )

    def test_list_item_eight_stars_with_dangling_tail(self):
        # `精准性********：****自动封禁…` 归一后剩一个孤儿开标记，要一起摘掉
        self.assertEqual(
            self.run_it("- ****精准性********：****自动封禁效率远超人工处置"),
            "- **精准性**：自动封禁效率远超人工处置",
        )

    def test_part_line_normalized(self):
        # PART 清理能整条吃掉的前提（必须先归一成 `**PART**03**`）
        self.assertEqual(self.run_it("****PART****03****"), "**PART**03**")

    def test_horizontal_rules_untouched(self):
        for hr in ("***", "****", "*****", "---", "___"):
            self.assertEqual(self.run_it(hr), hr)

    def test_plain_paragraph_untouched(self):
        text = "正文里的 **** 不该被动"
        self.assertEqual(self.run_it(text), text)


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
