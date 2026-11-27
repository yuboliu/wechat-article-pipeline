# -*- coding: utf-8 -*-
"""to_obsidian.py「去缩进」规则的回归测试（纯标准库，零网络）。

跑法（在 skill 目录下）：
    python -m unittest discover -s tests/convert -v

背景（pitfalls #74）：券商研报正文用 `style="text-indent:2em"`，抓取后每段带 4 个
前导空格；CommonMark 里「空行 + 4 空格起头」就是**缩进代码块**，这些段落进 Obsidian
会整段渲染成灰底等宽代码，而 Tier-1 八项检查只认 ``` 围栏，一条都拦不住。

这个函数的风险方向和推广截断相反：**漏掉只是难看，多删是改内容**（把嵌套列表、
表格、引用、软换行拆散）。所以下面每条 `keep` 用例和 `dedent` 用例同等重要。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import to_obsidian as m  # noqa: E402


class TestDedent(unittest.TestCase):
    def run_dedent(self, text):
        return m.dedent_indented_paragraphs(text)

    # ---- 该去的 ----

    def test_indented_paragraph_after_blank(self):
        src = "正文一。\n\n    **导航**：V1 里功能分布在各页面。\n\n正文二。\n"
        out, n = self.run_dedent(src)
        self.assertEqual(n, 1)
        self.assertIn("\n**导航**：V1 里功能分布在各页面。\n", out)
        self.assertNotIn("    **导航**", out)

    def test_continuation_lines_of_same_block(self):
        """整段被顶出 4 空格且跨多行：首行靠「上一行是空行」开闸，后续行跟着走。"""
        src = "前言。\n\n    第一行段落文字。\n    第二行段落文字。\n\n结尾。\n"
        out, n = self.run_dedent(src)
        self.assertEqual(n, 2)
        self.assertIn("\n第一行段落文字。\n第二行段落文字。\n", out)

    def test_indented_pure_bold_line(self):
        """整行加粗（`**摘要**`）被顶出 4 空格时也要拉回来，否则同样变代码块。"""
        out, n = self.run_dedent("x\n\n    **摘要**\n\n正文。\n")
        self.assertEqual(n, 1)
        self.assertTrue(out.startswith("x\n\n**摘要**\n"))

    def test_three_space_indent_is_kept(self):
        """1~3 空格不构成缩进代码块，动了只会破坏软换行。"""
        out, n = self.run_dedent("段落。\n\n   三空格。\n")
        self.assertEqual(n, 0)
        self.assertIn("\n   三空格。", out)

    # ---- 不许动的 ----

    def test_nested_list_item_kept(self):
        src = "- 父项\n    - 子项\n    - 子项二\n- 父项二\n"
        out, n = self.run_dedent(src)
        self.assertEqual(n, 0, "嵌套列表的缩进是结构，不能去")
        self.assertEqual(out, src)

    def test_list_continuation_kept(self):
        """缩进列表的续行：上一非空行是列表项，不是空行 → 不开闸。"""
        src = "- 父项说明\n    续行文字。\n\n    **段首**：新段落。\n"
        out, n = self.run_dedent(src)
        self.assertEqual(n, 1, "只该处理空行之后那一段")
        self.assertIn("\n    续行文字。\n", out)
        self.assertIn("\n**段首**：新段落。\n", out)

    def test_ordered_list_kept(self):
        src = "1. 甲\n    1. 乙\n\n    2. 丙\n"
        out, n = self.run_dedent(src)
        self.assertEqual(n, 0)
        self.assertEqual(out, src)

    def test_table_row_kept(self):
        src = "| 列 | 值 |\n| --- | --- |\n    | 甲 | 1 |\n"
        out, n = self.run_dedent(src)
        self.assertEqual(n, 0)
        self.assertEqual(out, src)

    def test_quote_kept(self):
        src = "> 引用一\n\n    > 缩进引用\n"
        out, n = self.run_dedent(src)
        self.assertEqual(n, 0)
        self.assertEqual(out, src)

    def test_fenced_code_kept(self):
        """围栏内部的缩进是代码语义。"""
        src = "说明。\n\n    ```\n    def f():\n        return 1\n    ```\n\n后文。\n"
        out, n = self.run_dedent(src)
        self.assertEqual(n, 0)
        self.assertEqual(out, src)

    def test_unfenced_code_after_blank_is_kept_when_marker_like(self):
        """围栏外的缩进块若像列表/图片/标题，一律不动（宁可漏也不改）。"""
        src = "\n    ![图](images/a.png)\n\n    ## 假标题\n"
        out, n = self.run_dedent(src)
        self.assertEqual(n, 0)

    def test_blank_and_whitespace_only_lines_untouched(self):
        src = "甲。\n\n    \n\n乙。\n"
        out, n = self.run_dedent(src)
        self.assertEqual(n, 0)
        self.assertEqual(out, src)


class TestConvertAppliesDedent(unittest.TestCase):
    """端到端：convert() 产出的文件里不能再出现「空行 + 4 空格段落」。"""

    def test_convert_output_has_no_indented_paragraph(self):
        art = "测试文章"
        with tempfile.TemporaryDirectory() as base:
            d = os.path.join(base, art)
            os.makedirs(d)
            src = os.path.join(d, art + ".md")
            with open(src, "w", encoding="utf-8") as f:
                f.write(
                    "# 测试文章\n\n"
                    "> 公众号: 某号\n> 发布时间: 2026-11-05 10:00:00\n"
                    "> 原文链接: https://mp.weixin.qq.com/s/abc\n\n---\n\n"
                    "开头一段，正文内容足够长，不会被当成标题。\n\n"
                    "    **对人：**网页负责看图、改稿、录音。\n\n"
                    "    **对 AI 客户端：**MCP 把同一套工具接到客户端。\n\n"
                    "中间一段，正文内容足够长，不会被当成标题。\n\n"
                    "    结论一段，正文内容足够长，不会被当成标题。\n\n"
                    "结尾一段，正文内容足够长，不会被当成标题。\n"
                )
            dst = m.convert(art, base, ["主题/AI/智能体"], date_override="2026-11-05")
            with open(dst, encoding="utf-8") as f:
                out = f.read()

        body = out.split("---\n\n", 2)[-1]
        bad = [ln for ln in body.split("\n")
               if ln.startswith("    ") and not ln.lstrip().startswith(("-", "|", ">", "![", "#"))]
        self.assertEqual(bad, [], "仍有 4 空格缩进段落：%r" % bad)
        self.assertIn("**对人：**网页负责看图、改稿、录音。", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
