# -*- coding: utf-8 -*-
"""「一位数章号 / 两位数节号」体系 + 正文结束标记的回归测试（纯标准库）。

跑法（在 skill 目录下）：
    python -m unittest discover -s tests -v

覆盖（都是「浅谈G行大模型上云部署方案」一篇暴露出来的新形态，pitfalls #32、#33）：
  * `strip_dup_title_head()` —— banner 尾巴上的 `***DeepSeek***`（粗+斜体装饰）要
    跟着标题一起删，但**不能**把首屏的 `**引言**` 也删掉。
  * `_pair_number_title()` —— 编号被挤到加粗块**开头**时（`**3****大****模型上云成果**`），
    后面的碎片要拼回去。
  * `normalize_bold_headings()` 形态 4 —— 章号独占加粗块、标题在块**外**同一行
    （`**4**总结` / `**1******大模型上云技术挑战****`）。
  * `merge_numbered_names()` —— 同一套 `**NN**` + `**名称**` 语法，靠「全文有没有
    一位数章号」决定是 `##` 还是 `###`（这是本次最容易误伤别人的一条）。
  * `find_promo_end()` —— `**END**![](images/…)` 这种「结束标记 + 装饰图」。

这几条都会直接影响大纲与文末截断，改前务必先跑这里。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import to_obsidian as m  # noqa: E402


TITLE = "浅谈G行大模型上云部署方案"
BODY = "正文段落，这里是一段足够长的内容，用来把全文长度撑起来。" * 8


class TestBannerDeco(unittest.TestCase):
    """banner 尾巴的 `***DeepSeek***` 要删；`**引言**` 不能误删。"""

    def test_triple_star_tagline_removed_with_banner(self):
        text = ("**浅谈G行大模型**\n\n**上云部署方案**\n\n***DeepSeek***\n\n"
                "![](images/img_003.gif)**引言**\n\n正文。\n")
        out = m.strip_dup_title_head(text, TITLE)
        self.assertNotIn("浅谈G行大模型", out)
        self.assertNotIn("DeepSeek", out)
        # 首屏的 `**引言**` 是正文小标题，必须留下
        self.assertIn("**引言**", out)

    def test_bold_only_next_line_not_swallowed(self):
        # 只有 `**纯粗**`（没有三颗星）时不吃 —— 那可能是正文小标题
        text = "**浅谈G行大模型**\n\n**上云部署方案**\n\n![[images/a.png]]\n\n**引言**\n\n正文。\n"
        out = m.strip_dup_title_head(text, TITLE)
        self.assertNotIn("浅谈G行大模型", out)
        self.assertIn("**引言**", out)

    def test_banner_without_tail_unchanged_behavior(self):
        text = "**浅谈G行大模型**\n\n**上云部署方案**\n\n正文开始。\n"
        out = m.strip_dup_title_head(text, TITLE)
        self.assertEqual(out.strip(), "正文开始。")

    def test_non_matching_banner_left_alone(self):
        text = "**完全不相干的东西**\n\n正文。\n"
        self.assertEqual(m.strip_dup_title_head(text, TITLE), text)


class TestPairNumberTitle(unittest.TestCase):
    """编号在加粗块开头时，后面全是文字碎片 → 拼成一条。"""

    def test_number_first_then_split_name(self):
        self.assertEqual(m._pair_number_title(["3", "大", "模型上云成果"]),
                         ["3 大模型上云成果"])

    def test_number_in_the_middle_keeps_old_behavior(self):
        self.assertEqual(m._pair_number_title(["策略设计", "01", "智能解析机制"]),
                         ["策略设计", "01 智能解析机制"])

    def test_number_pair_still_joined(self):
        self.assertEqual(m._pair_number_title(["01", "动静区分"]), ["01 动静区分"])

    def test_plain_name_untouched(self):
        self.assertEqual(m._pair_number_title(["需求分析"]), ["需求分析"])


class TestNormalizeFormFour(unittest.TestCase):
    """章号独占加粗块、标题在块外同一行。"""

    def _norm(self, text):
        return m.normalize_bold_headings(text)[0]

    def test_number_block_then_title_same_line(self):
        out = self._norm("**4**总结\n")
        self.assertIn("**4 总结**", out)

    def test_stray_asterisks_around_title_cleaned(self):
        out = self._norm("**1******大模型上云技术挑战****\n")
        self.assertIn("**1 大模型上云技术挑战**", out)

    def test_long_body_after_number_not_turned_into_heading(self):
        line = "**1**这是一段很长的正文，带句号，明显不是标题。\n"
        self.assertEqual(self._norm(line), line)


class TestMergeNumberedNames(unittest.TestCase):
    """同一语法、两种口径 —— 靠「全文有没有一位数章号」区分。"""

    def test_single_digit_chapter_and_two_digit_section(self):
        text = ("**2**\n\n**大模型上云部署方案**\n\n正文。\n\n"
                "**03**\n\n**AI算力硬件感知调度：实现异构算力最优分配**\n\n正文。\n")
        out, notes = m.merge_numbered_names(text)
        self.assertIn("## 2 大模型上云部署方案", out)
        self.assertIn("### 03 AI算力硬件感知调度：实现异构算力最优分配", out)
        self.assertTrue(notes)

    def test_two_digit_chapter_when_no_single_digit(self):
        # 「G行 DNS」口径：两位数就是章 → `## 名称`，编号丢掉。
        # 原文是被切碎的 `**0****1**` —— 走真实链路（归一化先把它合回 `**01**`）
        raw = "**0****1**\n\n**架构设计**\n\n正文。\n\n**02**\n\n**域名规划**\n\n正文。\n"
        norm = m.normalize_bold_headings(raw)[0]
        out, _ = m.merge_numbered_names(norm)
        self.assertIn("## 架构设计", out)
        self.assertIn("## 域名规划", out)
        self.assertNotIn("### 01 架构设计", out)

    def test_single_digit_chapter_only(self):
        out, _ = m.merge_numbered_names("**3**\n\n**大模型上云成果**\n\n正文。\n")
        self.assertIn("## 3 大模型上云成果", out)

    def test_untouched_when_no_number_pair(self):
        text = "## 需求分析\n\n正文。\n"
        out, notes = m.merge_numbered_names(text)
        self.assertEqual(out, text)
        self.assertEqual(notes, [])


class TestFindPromoEnd(unittest.TestCase):
    """`**END**` + 署名/推荐阅读 的截断。"""

    def _doc(self, tail):
        return "标题。\n\n" + BODY + "\n\n" + tail

    def test_end_marker_with_image_and_signature(self):
        text = self._doc("**END**![](images/img_013.gif)\n\n**作者：赵序光**\n\n简介。\n\n"
                         "**编辑：郜斌**\n\n简介。\n\n**往期推荐**\n\n"
                         "1\n\n[某文](https://mp.weixin.qq.com/s?__biz=x)\n")
        idx = m.find_promo_end(text)
        self.assertNotEqual(idx, -1)
        self.assertTrue(text[idx:].startswith("**END**"))

    def test_bare_wan_marker(self):
        text = self._doc("完\n\n**作者：张三**\n\n简介。\n\n**编辑：李四**\n\n简介。\n")
        self.assertNotEqual(m.find_promo_end(text), -1)

    def test_rejected_when_marker_too_early(self):
        # 标记在文首（尾巴占比 > 60%）→ 不认，防正文中段的 END
        text = "**END**\n\n" + BODY + "\n"
        self.assertEqual(m.find_promo_end(text), -1)

    def test_rejected_without_promo_evidence(self):
        # 标记位置合格，但后面没有任何推广特征（没有署名、没有推荐链接）→ 不认
        text = BODY + "\n\n**END**\n\n" + BODY + "\n"
        self.assertEqual(m.find_promo_end(text), -1)

    def test_rejected_inside_fence(self):
        text = self._doc("```\n**END**\n```\n\n**作者：张三**\n\n简介。\n\n**编辑：李四**\n\n简介。\n")
        self.assertEqual(m.find_promo_end(text), -1)

    def test_long_word_starting_with_wan_not_matched(self):
        self.assertIsNone(m.PROMO_END_RE.match("**完整版内容**"))

    def test_f5_shape_prefers_earlier_tail(self):
        # `end` 夹在推广块**内部**（关注引导在它前面）→ 取更靠前者才不会留下关注块
        text = (BODY + "\n\n**关注 F5社区 微信公众号**\n\n![](images/img_007.jpeg)\n\n"
                "扫描上方二维码\n\n添加市场部助理小安，加入F5微信技术群\n\nend\n\n"
                "**0****1**\n\n[某文](https://mp.weixin.qq.com/s?__biz=x)\n")
        t, e = m.find_promo_tail(text), m.find_promo_end(text)
        self.assertNotEqual(t, -1)
        self.assertNotEqual(e, -1)
        self.assertLess(t, e)      # convert() 取 min(t, e)


class TestSingleDotNumberScope(unittest.TestCase):
    """`1. xxx` 是「章」还是「节」，取决于**全文有没有两级点号**（pitfalls #36）。

    同一套「单级点号」写法在两篇真实文章里含义相反：
      * 「F5 数字图书馆」——章是**无编号**的 `## 架构设计`，`1. SSL 卸载` 是它下面的
        **节**（每章重新编号），全文没有两级点号 ⇒ 保持 `###`；
      * 「基于知识图谱增强RAG…」——`1. 引言` 是**章**、`2.1. 知识库概述` 是节、
        `5.3.1. …` 是子节，编号自带层级 ⇒ `1.` 提到 `##`。
    判据由 `rebuild_headings()` 第一遍扫描给出（只扫可能当标题的行，避开正文里的
    `802.1Q标准` 这类数字）。
    """

    def test_dot1_default_is_section(self):
        self.assertEqual(m.classify_head_number("1. SSL 卸载"), ("dot1", 3))

    def test_dot1_with_multi_dot_is_chapter(self):
        self.assertEqual(m.classify_head_number("1. 引言", multi_dot=True), ("dot1", 2))

    def test_f5_style_article_unchanged(self):
        """无两级点号 ⇒ `1.`/`2.` 仍是 `###`，无编号章仍是 `##`。"""
        text = ("## 架构设计\n\n正文。\n\n"
                "### 1. SSL 卸载\n\n正文。\n\n"
                "### 2. 源地址透传\n\n正文。\n\n"
                "## 架构分析\n\n正文尾。\n")
        out, _ = m.rebuild_headings(text)
        self.assertIn("## 架构设计", out)
        self.assertIn("### 1. SSL 卸载", out)
        self.assertIn("### 2. 源地址透传", out)
        self.assertIn("## 架构分析", out)

    def test_multi_dot_article_gets_full_hierarchy(self):
        """有 `2.1.` ⇒ `1.` 是章、`2.1.` 是节、`5.3.1.` 是子节。"""
        text = ("## 1. 引言\n\n正文。\n\n"
                "## 2. RAG 知识库\n\n正文。\n\n"
                "### 2.1. 知识库概述\n\n正文。\n\n"
                "### 2.2. RAG技术应用\n\n正文。\n\n"
                "## 3. 知识图谱技术\n\n正文。\n\n"
                "### 3.1. 知识图谱定义\n\n正文。\n\n"
                "## 5. 基于知识图谱构建RAG知识库\n\n正文。\n\n"
                "### 5.3. 关键技术\n\n正文。\n\n"
                "#### 5.3.1. 领域知识图谱构建\n\n正文。\n")
        out, _ = m.rebuild_headings(text)
        self.assertIn("## 1. 引言", out)
        self.assertIn("## 2. RAG 知识库", out)
        self.assertIn("### 2.1. 知识库概述", out)
        # 关键：那条「恰好没被加粗」的章标题不再掉到 ###
        self.assertIn("## 3. 知识图谱技术", out)
        self.assertIn("### 3.1. 知识图谱定义", out)
        self.assertIn("#### 5.3.1. 领域知识图谱构建", out)

    def test_body_line_starting_with_digits_does_not_trigger_multi_dot(self):
        """正文行首的 `802.1Q标准定义了…` 不能把 `1.` 误判成章。

        第一遍扫描**只看**「`#` 标题行 + 独占一行的加粗行」；若图省事对全文扫
        `\\d+\\.\\d+`，这行就会中招，整篇层级会跟着歪。
        """
        text = ("## 引言\n\n正文。\n\n"
                "### 1. SSL 卸载\n\n"
                "802.1Q标准定义了 VLAN 标签，最多支持 4094 个 VLAN。\n\n"
                "正文尾。\n")
        out, _ = m.rebuild_headings(text)
        self.assertIn("### 1. SSL 卸载", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
