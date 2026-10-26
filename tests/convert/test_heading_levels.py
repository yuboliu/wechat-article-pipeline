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

    def test_dot1_without_space(self):
        """`1.xxx` 与 `1. xxx` 等价（作者混用是常态，不能靠空格区分章/节）。"""
        self.assertEqual(m.classify_head_number("1.自动封禁体系高效性目标建设实践"), ("dot1", 3))
        self.assertEqual(m.classify_head_number("1. 自动封禁体系建设背景"), ("dot1", 3))
        # 但点号后紧跟数字仍是版本号，不能当编号
        self.assertEqual(m.classify_head_number("802.1Q标准"), ("plain", None))
        self.assertEqual(m.classify_head_number("1.2.1 协议栈"), ("dot", 4))


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

    def test_two_dot_styles_same_article_same_level(self):
        """同篇 `## 1. 甲` 与 `## 2.乙` 必须同级（浅谈自动封禁 一篇 PART 02/03）。"""
        text = "\n\n".join([
            "## 一、总述", "正文。", "## 1. 建设背景", "正文。",
            "## 2.高效性目标建设实践", "正文。",
        ])
        self.assertEqual(heads(text), [
            "## 一、总述", "### 1. 建设背景", "### 2.高效性目标建设实践",
        ])

    def test_bracket_numbered_heading_keeps_level(self):
        """括号编号的标题行仍按「列表项」处理（知识图谱RAG 那篇）。"""
        text = "## （1）朴素 RAG 阶段"
        self.assertEqual(heads(text), ["## （1）朴素 RAG 阶段"])

    def test_numbered_bold_with_trailing_colon_is_heading(self):
        """`**1.xxx：**` 带编号且以冒号收尾 -> 是作者的小标题，不是编号列表项。"""
        text = "\n\n".join([
            "## 全生命周期管理", "正文。", "**1.事前策略预配置与仿真测试：**", "正文。",
        ])
        self.assertIn("### 1.事前策略预配置与仿真测试：", heads(text))

    def test_unnumbered_colon_sentence_still_filtered(self):
        """无编号的`…：`仍是引导句，不能被提成标题（原有闸门不能松）。"""
        text = "**应重点考虑以下技术建议：**"
        self.assertEqual(heads(text), [])


class TestPromoteCnNumberedHeads(unittest.TestCase):
    """`四、…` 掉成段落时补回标题（Gartner 2027 十大趋势 一篇）。"""

    def run_it(self, text):
        return m.promote_cn_numbered_heads(text, [])

    def test_fourth_section_promoted(self):
        text = "\n\n".join([
            "## 一、甲", "正文。", "## 二、乙", "正文。", "## 三、丙", "正文。",
            "四、丁，该如何读？", "正文。",
        ])
        out, notes = self.run_it(text)
        self.assertIn("## 四、丁，该如何读？", out)
        self.assertTrue(notes)

    def test_no_sibling_headings_untouched(self):
        text = "四、这只是一段正文？\n"
        out, notes = self.run_it(text)
        self.assertEqual(out, text)
        self.assertEqual(notes, [])

    def test_duplicate_numeral_not_promoted(self):
        # 已有 `## 一、甲` 时，正文里再出现 `一、…` 不动（防目录项 / 重复段）
        text = "\n\n".join(["## 一、甲", "## 二、乙", "一、重复项", "正文。"])
        out, _ = self.run_it(text)
        self.assertNotIn("## 一、重复项", out)

    def test_sentence_with_period_not_promoted(self):
        text = "\n\n".join(["## 一、甲", "## 二、乙", "三、这一段是正文，写了很长的一句话。"])
        out, _ = self.run_it(text)
        self.assertNotIn("## 三、这一段", out)


class TestNormalizeHeadingLayout(unittest.TestCase):
    def test_blank_line_before_heading_inserted(self):
        self.assertEqual(
            m.normalize_heading_layout(["正文。", "## 标题"]),
            ["正文。", "", "## 标题"],
        )

    def test_existing_blank_not_doubled(self):
        self.assertEqual(
            m.normalize_heading_layout(["正文。", "", "## 标题"]),
            ["正文。", "", "## 标题"],
        )

    def test_number_spacing_normalized(self):
        self.assertEqual(m.normalize_heading_layout(["### 1.xxx"]), ["### 1. xxx"])

    def test_dotted_number_not_split(self):
        self.assertEqual(
            m.normalize_heading_layout(["### 1.2.1 协议栈"]), ["### 1.2.1 协议栈"]
        )

    def test_code_fence_untouched(self):
        lines = ["```", "## 1.x", "```"]
        self.assertEqual(m.normalize_heading_layout(lines), lines)


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

NL = chr(10)


def p(*parts):
    """把若干行拼成「空行分隔」的 Markdown 片段（测试里不写反斜杠转义）。"""
    return (NL + NL).join(parts)


class TestCnHeadsWithoutAnchor(unittest.TestCase):
    """中文序号章标题**全部**掉成段落时（pitfalls #50）。

    实测「从 RAGFlow 到 GraphRAG」：`一、`/`二、`/`三、` 三条章标题都是普通段落，
    旧规则要求「全文已有 ≥2 个中文序号标题」才肯补级，于是整篇一章都没有。
    """

    def test_all_paragraph_cn_heads_promoted(self):
        text = p("一、甲", "正文一。", "二、乙", "正文二。", "三、丙", "正文三。") + NL
        out, notes = m.promote_cn_numbered_heads(text, [])
        self.assertIn("## 一、甲", out)
        self.assertIn("## 二、乙", out)
        self.assertIn("## 三、丙", out)
        self.assertTrue(notes)

    def test_non_sequential_not_promoted(self):
        # 序号不连续 -> 大概率是正文里顺口写的，整组不动
        text = p("一、甲", "正文。", "三、乙", "正文。", "五、丙", "正文。") + NL
        out, notes = m.promote_cn_numbered_heads(text, [])
        self.assertEqual(out, text)
        self.assertEqual(notes, [])

    def test_too_few_candidates(self):
        text = p("一、甲", "正文。", "二、乙", "正文。") + NL
        out, notes = m.promote_cn_numbered_heads(text, [])
        self.assertEqual(notes, [])

    def test_sentence_like_candidate_not_promoted(self):
        text = p("一、甲", "正文。", "二、乙", "正文。", "三、丙这一段其实是正文句子。") + NL
        out, notes = m.promote_cn_numbered_heads(text, [])
        self.assertEqual(notes, [])

    def test_cn_num_parser(self):
        self.assertEqual(m.cn_num_to_int("一"), 1)
        self.assertEqual(m.cn_num_to_int("十"), 10)
        self.assertEqual(m.cn_num_to_int("十一"), 11)
        self.assertEqual(m.cn_num_to_int("二十一"), 21)
        self.assertIsNone(m.cn_num_to_int("甲"))


class TestDunSectionsUnderCnHeads(unittest.TestCase):
    """章用中文序号、节用 `1、2、` 顿号时，节必须挂在章下一级（pitfalls #51）。"""

    def test_dun_section_demoted(self):
        text = p("## 一、章甲", "正文。", "## 1、节一", "正文。", "## 2、节二", "正文。") + NL
        out, _notes = m.rebuild_headings(text)
        self.assertIn("### 1、节一", out)
        self.assertIn("### 2、节二", out)

    def test_no_cn_anchor_keeps_top_level(self):
        # 没有中文序号章体系时，`1、` 仍是顶级（不能凭空降级）
        text = p("## 1、章一", "正文。", "## 2、章二", "正文。") + NL
        out, _notes = m.rebuild_headings(text)
        self.assertIn("## 1、章一", out)
        self.assertIn("## 2、章二", out)


class TestBracketHeads(unittest.TestCase):
    """`（1）xxx` 括号编号小节的补级（pitfalls #52）。"""

    def test_group_promoted_same_level(self):
        text = p("## 二、章", "### 2、分层",
                 "（1）图构建引擎", "正文。",
                 "（2）图数据库与存储层", "正文。",
                 "（3）图推理与检索层", "正文。") + NL
        out, notes = m.promote_bracket_heads(text)
        self.assertIn("#### （1）图构建引擎", out)
        self.assertIn("#### （2）图数据库与存储层", out)
        self.assertIn("#### （3）图推理与检索层", out)
        self.assertTrue(notes)

    def test_long_lead_in_not_promoted(self):
        # 带正文的长句（含句号）是段落，不是小节标题
        text = p("## 二、章",
                 "（1）全局推理能力：GraphRAG 能够整合多个文档。",
                 "（2）强可解释性：每个答案均可溯源。",
                 "（3）知识抽象：能自动梳理主题。") + NL
        out, notes = m.promote_bracket_heads(text)
        self.assertEqual(out, text)
        self.assertEqual(notes, [])

    def test_non_sequential_not_promoted(self):
        text = p("## 章", "（1）甲", "正文。", "（3）乙", "正文。", "（4）丙", "正文。") + NL
        out, notes = m.promote_bracket_heads(text)
        self.assertEqual(notes, [])

    def test_fenced_bracket_lines_untouched(self):
        text = p("## 章", "```", "（1）甲", "（2）乙", "（3）丙", "```") + NL
        out, notes = m.promote_bracket_heads(text)
        self.assertEqual(out, text)


class TestEmptyTableHeader(unittest.TestCase):
    """空表头 -> 首条正文行顶上去（pitfalls #49）。"""

    def test_empty_header_promoted(self):
        # 表格行必须**相邻**（p() 插的是空行，会把表格拆散），这里直接拼单换行
        text = NL.join(["|  |  |", "| --- | --- |", "| **层次** | **回答的问题** |",
                        "| 协议状态 | 是否建立？ |"]) + NL
        out = m.fix_empty_table_header(text, [])
        self.assertEqual(
            out, NL.join(["| 层次 | 回答的问题 |", "| --- | --- |",
                          "| 协议状态 | 是否建立？ |"]) + NL)

    def test_normal_table_untouched(self):
        text = NL.join(["| 甲 | 乙 |", "| --- | --- |", "| 1 | 2 |"]) + NL
        self.assertEqual(m.fix_empty_table_header(text, []), text)

    def test_header_only_untouched(self):
        text = NL.join(["|  |  |", "| --- | --- |"]) + NL
        self.assertEqual(m.fix_empty_table_header(text, []), text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
