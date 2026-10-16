# -*- coding: utf-8 -*-
"""「Word 粘贴型」正文标题层级 + 假标题 + 编号列表项的回归测试（纯标准库）。

跑法（在 skill 目录下）：
    python -m unittest discover -s tests -v

覆盖：
  * `shift_body_headings()`（pitfalls #30、#35）—— 正文标题的**最浅层级**要归一到
    `##`：作者粘 `<h1>`/`<h2>` 时偏浅（`# 一、引言` 与文章标题同级）要下移，
    粘 `<h3>`/`<h4>` 时偏深（`### 一、还是从网站开始`）要上移。
  * `demote_fake_headings()`（pitfalls #35）—— 作者把摘要/导语也套了标题样式，
    HTML 里就是真 `<h3>`，markdownify 照实输出 —— 这种「像段落的标题」要降回段落。
  * `rebuild_headings()` 里 `BOLD_LIST_ITEM_RE` 的分支 —— `**3.可视化展示**` 这种
    「编号 + 点号 + 紧跟文字」的加粗行是**列表项**，不是标题。

这三条都会直接影响大纲，改前务必先跑这里。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import to_obsidian as m  # noqa: E402


TITLE = "云原生应用可观测架构设计"
# 真实样本：「不管你是运维还是开发，微服务这些你得知道!」——章节是 Word 的 <h3>、
# 小节是 <h4>，整篇比约定深一级；文首两条「摘要」也被套了 <h3>。
MS_TITLE = "不管你是运维还是开发，微服务这些你得知道!"
# 真实样本：「基于知识图谱增强RAG应用和构建RAG知识库（实践分享）」——标题文字
# **整行被加粗**（`## **1. 引言**`），且章节/小节/子节都是「编号 + 尾点」写法。
RAG_TITLE = "基于知识图谱增强RAG应用和构建RAG知识库（实践分享）"


class TestUnwrapBoldHead(unittest.TestCase):
    """标题整行被加粗（`## **1. 引言**`）→ 拆掉外层 `**`（pitfalls #36）。

    不拆的代价不只是样式：`classify_head_number()` 看到首字符是 `*` 就判 `plain`，
    整篇的编号层级重建会**静默失效**。
    """

    def test_fully_bold_heading_is_unwrapped(self):
        self.assertEqual(m.unwrap_bold_head("**1. 引言**"), "1. 引言")
        self.assertEqual(m.unwrap_bold_head("**2.1. 知识库概述**"), "2.1. 知识库概述")

    def test_partial_bold_is_left_alone(self):
        # 只有「整行恰好是一个加粗块」才拆；半截加粗/普通标题原样返回
        self.assertEqual(m.unwrap_bold_head("**重要**提示"), "**重要**提示")
        self.assertEqual(m.unwrap_bold_head("普通标题"), "普通标题")

    def test_rebuild_headings_strips_bold_and_keeps_number_levels(self):
        text = ("## **1. 引言**\n\n正文。\n\n"
                "## **2. 知识图谱技术**\n\n正文。\n\n"
                "### **2.1. 知识图谱定义**\n\n正文。\n\n"
                "#### **2.1.1. 实体识别**\n\n正文。\n")
        out, _ = m.rebuild_headings(text)
        self.assertIn("## 1. 引言", out)
        self.assertIn("## 2. 知识图谱技术", out)
        self.assertIn("### 2.1. 知识图谱定义", out)
        self.assertIn("#### 2.1.1. 实体识别", out)
        self.assertNotIn("**", out)


class TestParenNumberedBoldItem(unittest.TestCase):
    """`**（1）朴素 RAG…**` 这类**括号编号**加粗行是列表项，不是标题（pitfalls #36）。

    RAG 那篇的 `2.2` 下面并列三条 RAG 阶段，被提升成 `##` 后把 `2.3` 挤成了
    「三个子的节」。括号编号从来不是本项目的标题编号（标题只用 `1` / `1.1` / `01`）。
    """

    def test_paren_number_forms_match(self):
        for t in ("（1）朴素 RAG- Native RAG 阶段", "(1) xxx", "（12）全角数字"):
            self.assertTrue(m.BOLD_LIST_ITEM_RE.match(t), t)

    def test_dotted_forms_keep_existing_semantics(self):
        # 点号**紧跟**非空白 = 列表项；点号后留空格 = 标题（既有口径）
        self.assertTrue(m.BOLD_LIST_ITEM_RE.match("3.可视化展示"))
        self.assertFalse(m.BOLD_LIST_ITEM_RE.match("1. SSL 卸载"))
        self.assertFalse(m.BOLD_LIST_ITEM_RE.match("1.2.1 协议栈"))

    def test_rebuild_headings_keeps_paren_item_as_paragraph(self):
        text = ("### 2.2. RAG技术应用\n\n正文。\n\n"
                "**（1）朴素 RAG- Native RAG 阶段**\n\n正文一。\n\n"
                "**（2）进阶RAG-Advanced RAG 阶段**\n\n正文二。\n\n"
                "### 2.3. 存在不足\n\n正文。\n")
        out, _ = m.rebuild_headings(text)
        self.assertIn("**（1）朴素 RAG- Native RAG 阶段**", out)
        self.assertIn("**（2）进阶RAG-Advanced RAG 阶段**", out)
        self.assertNotIn("# （1）", out)
        self.assertNotIn("# （2）", out)
        # 2.3 必须仍是 ###（不能被三条假标题挤走层级）
        self.assertIn("### 2.3. 存在不足", out)


class TestShiftBodyHeadings(unittest.TestCase):
    """正文标题的绝对层级归一：最浅的一级必须是 `##`。"""

    def _shift(self, text, title=TITLE):
        notes = []
        return m.shift_body_headings(text, title, notes), notes

    def test_word_paste_article_shifted_down_one(self):
        text = "# 一、引言\n\n正文。\n\n## 2.1 全栈覆盖\n\n正文。\n"
        out, notes = self._shift(text)
        self.assertIn("## 一、引言", out)
        self.assertIn("### 2.1 全栈覆盖", out)
        self.assertTrue(notes)

    def test_too_deep_article_shifted_up_one(self):
        """`<h3>`/`<h4>` 形态：最浅的 `###` 上移成 `##`。"""
        text = "### 一、还是从网站开始\n\n正文。\n\n#### 2.1、服务发现\n\n正文。\n"
        out, notes = self._shift(text)
        self.assertIn("## 一、还是从网站开始", out)
        self.assertIn("### 2.1、服务发现", out)
        self.assertTrue(any("上移" in n for n in notes))

    def test_normal_article_untouched(self):
        # 没有正文 H1（抓取器的样式块口径）—— 一个字都不动
        text = "## 容器平台网络模型\n\n### 1.1 容器网络概述\n\n正文。\n"
        out, notes = self._shift(text)
        self.assertEqual(out, text)
        self.assertEqual(notes, [])

    def test_title_repeat_h1_is_dropped_and_not_evidence(self):
        # 正文里只复读了一遍标题 —— 丢掉，且**不**因此触发整体下移
        text = "# %s\n\n## 一、引言\n\n正文。\n" % TITLE
        out, notes = self._shift(text)
        self.assertNotIn("# " + TITLE, out)
        self.assertIn("## 一、引言", out)     # 没有被下移成 ###
        self.assertEqual(notes, ["删除正文里重复的文章标题行"])

    def test_body_h1_inside_fence_untouched(self):
        text = "```\n# 这不是标题\n```\n\n正文。\n"
        out, notes = self._shift(text)
        self.assertEqual(out, text)
        self.assertEqual(notes, [])

    def test_deep_levels_capped_at_six(self):
        text = "# 一、章\n\n###### 六级\n\n正文。\n"
        out, _ = self._shift(text)
        self.assertIn("###### 六级", out)   # 6 级封顶，不再下移


class TestDemoteFakeHeadings(unittest.TestCase):
    """「像段落的标题」降回段落。"""

    def _demote(self, text):
        notes = []
        return m.demote_fake_headings(text, notes), notes

    def test_paragraph_like_heads_are_demoted(self):
        text = "\n".join([
            "### 图片",                                     # markdownify 对「标题里裹图片」的产物
            "",
            "### 本文从一个网站为切入点，随着业务规模的拓展与用户数量的增加，"
            "传统服务模式暴露出诸多待解决的问题。",          # 超长 + 句号
            "",
            "### 一、还是从网站开始",                        # 真标题 —— 不动
        ])
        out, notes = self._demote(text)
        self.assertTrue(out.startswith("图片\n"))
        self.assertIn("\n本文从一个网站为切入点", out)
        self.assertIn("### 一、还是从网站开始", out)
        self.assertEqual(len(notes), 1)

    def test_normal_heads_untouched(self):
        text = "## 二、服务治理的难题\n\n### 2.1、服务发现\n\n### 何谓微服务\n"
        out, notes = self._demote(text)
        self.assertEqual(out, text)
        self.assertEqual(notes, [])

    def test_h1_title_line_is_never_touched(self):
        # 长标题本身不合法？也不是标题行的活 —— H1 是文章标题，一律不碰
        text = "# " + MS_TITLE + "，这是一条很长的标题吗。\n"
        out, notes = self._demote(text)
        self.assertEqual(out, text)
        self.assertEqual(notes, [])

    def test_heads_inside_fence_untouched(self):
        text = "```\n### 本文从某某开始，一个很长很长的段落句子。\n```\n"
        out, notes = self._demote(text)
        self.assertEqual(out, text)
        self.assertEqual(notes, [])


class TestBoldNumberedListItem(unittest.TestCase):
    """`**3.可视化展示**` 是列表项，不该被提成标题。"""

    def test_numbered_list_item_not_promoted(self):
        text = "## 四、实践经验\n\n### 实践一：监控真实用户体验\n\n正文。\n\n**3.可视化展示**\n\n正文。\n"
        out, _ = m.rebuild_headings(text)
        self.assertIn("**3.可视化展示**", out)
        self.assertNotIn("## 3.可视化展示", out)

    def test_multi_level_number_still_promoted(self):
        # `1.2.1 协议栈`：点号后仍是数字 → (?!\d) 放行，照旧是标题
        text = "## 需求分析\n\n**1.2.1 协议栈**\n\n正文。\n"
        out, _ = m.rebuild_headings(text)
        self.assertIn("#### 1.2.1 协议栈", out)

    def test_dot_with_space_still_promoted(self):
        # `1. SSL 卸载`：点后有空格 → 真标题，照旧提升
        text = "## 架构设计\n\n**1. SSL 卸载**\n\n正文。\n"
        out, _ = m.rebuild_headings(text)
        self.assertIn("### 1. SSL 卸载", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
