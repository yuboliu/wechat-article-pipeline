# -*- coding: utf-8 -*-
"""标签推断引擎（scripts/tag_infer.py）的回归测试（纯标准库）。

跑法（在 skill 目录下）：
    python -m unittest discover -s tests/convert -v      # 只跑转换器这套
    python -m pytest tests/ -q -m "not e2e"              # 全量

重点守两件事：
  1. **体裁判定是「标题级联」，不是纯打分** —— 正文里「如何/落地/模板」满地都是，
     若退回纯加权，教程会被判成随笔、趋势报告会被判成方案实践（2026-11-04 实测
     类型准确率只有 64%）。下面的用例锁住级联顺序。
  2. **frontmatter 的 tags 有两种缩进形态** —— yaml.dump 写的是无缩进，
     Obsidian Linter 会重排成 2 空格缩进。解析器两个都得认，否则存量笔记读不到标签。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import tag_infer as ti  # noqa: E402

TAX = ti.load_taxonomy()

BODY = "正文。" * 200


def doc(title, body=None):
    return "# %s\n\n%s\n" % (title, body if body is not None else BODY)


class TestSplitMd(unittest.TestCase):
    def test_strips_frontmatter_callout_and_tail_tags(self):
        text = ("---\ncreated: '2026-01-01'\ntags:\n- 主题/AI\n---\n\n"
                "# 真标题\n\n> [!info] 文章信息\n> **作者**：某人\n\n正文内容。\n\n"
                "#主题/AI #类型/技术教程\n")
        title, heads, body = ti.split_md(text)
        self.assertEqual(title, "真标题")
        self.assertNotIn("主题/AI", body)       # 文末裸标签行要剥掉
        self.assertNotIn("文章信息", body)      # callout 要剥掉

    def test_title_falls_back_to_frontmatter(self):
        text = '---\ntitle: "剪藏来的标题"\n---\n\n正文，没有 H1。\n'
        title, _, _ = ti.split_md(text)
        self.assertEqual(title, "剪藏来的标题")

    def test_headings_excluded_from_body(self):
        text = "# T\n\n## 小节甲\n\n正文。\n"
        _, heads, body = ti.split_md(text)
        self.assertIn("小节甲", heads)
        self.assertNotIn("小节甲", body)


class TestParseFrontmatterTags(unittest.TestCase):
    def test_no_indent_sequence(self):
        text = "---\ncreated: 'x'\ntags:\n- 主题/AI/RAG\n- 类型/技术教程\n---\n\n# T\n"
        self.assertEqual(ti.parse_frontmatter_tags(text), ["主题/AI/RAG", "类型/技术教程"])

    def test_two_space_indent_sequence(self):
        text = "---\ntags:\n  - 主题/网络/DNS\n  - 来源/微信公众号\n---\n\n# T\n"
        self.assertEqual(ti.parse_frontmatter_tags(text), ["主题/网络/DNS", "来源/微信公众号"])

    def test_inline_sequence(self):
        text = "---\ntags: [主题/AI, 类型/模板]\n---\n\n# T\n"
        self.assertEqual(ti.parse_frontmatter_tags(text), ["主题/AI", "类型/模板"])

    def test_no_frontmatter(self):
        self.assertEqual(ti.parse_frontmatter_tags("# 标题\n\n正文\n"), [])

    def test_tags_key_absent(self):
        self.assertEqual(ti.parse_frontmatter_tags("---\ncreated: 'x'\n---\n\n# T\n"), [])


class TestTypeCascade(unittest.TestCase):
    """体裁判定：标题规则按数组顺序级联，正文只在一条都不中时兜底。"""

    def infer_type(self, title, body=None):
        return ti.infer_type(TAX, title, "", body if body is not None else BODY)["path"]

    def test_tutorial_markers(self):
        for t in ["图解从 IP 到 SRv6：一张网络如何学会连接、隔离与选路？",
                  "从零入门技术文档",
                  "Hermes Agent 学习指南",
                  "一文讲清 FP64、FP32"]:
            self.assertEqual(self.infer_type(t), "类型/技术教程", t)

    def test_practice_beats_opinion(self):
        # 标题同时有「浅谈」（随笔）与「建设实践」（实践）→ 实践优先
        t = "浅谈网络安全纵深防御体系之自动封禁能力建设实践"
        self.assertEqual(self.infer_type(t), "类型/方案实践")

    def test_trend_report(self):
        for t in ["思科2026报告深度解读：AI正在重塑广域网",
                  "Gartner发布2027十大战略技术趋势：AI智能体治理是核心",
                  "MIT发布Agent信心指数：梳理101项技术任务"]:
            self.assertEqual(self.infer_type(t), "类型/趋势解读", t)

    def test_deep_research(self):
        self.assertEqual(self.infer_type("张瑜美股见顶前的财务信号——2000年泡沫复盘"),
                         "类型/深度研报")

    def test_quick_reference_and_template_and_training(self):
        self.assertEqual(self.infer_type("Claude Code 常用命令速查"), "类型/工具速查")
        self.assertEqual(self.infer_type("产业链投资研究 — 提示词模板"), "类型/模板")
        self.assertEqual(self.infer_type("《华为云Stack培训》讲解文字稿"), "类型/培训讲稿")

    def test_title_ending_question_is_not_opinion_by_itself(self):
        # 问号本身不是体裁判据：SRv6 那篇是图解教程，不能因为标题带问号判成随笔
        t = "图解从IP到SRv6：一张网络如何学会连接、隔离与选路？"
        self.assertEqual(self.infer_type(t), "类型/技术教程")

    def test_default_when_nothing_matches(self):
        info = ti.infer_type(TAX, "容器云平台网络架构", "", BODY)
        self.assertEqual(info["path"], "类型/技术教程")
        self.assertEqual(info["via"], "default")

    def test_body_keywords_do_not_hijack_genre(self):
        # 正文里塞满「如何/落地/模板」，也不能把篇教程判成随笔或方案实践
        noisy = "如何 落地 模板 报告 " * 100
        self.assertEqual(self.infer_type("图解某技术原理", noisy), "类型/技术教程")


class TestThemeInference(unittest.TestCase):
    def test_hits_expected_subtag(self):
        body = "DNS 域名解析 递归 权威 DoH 智能解析 " * 20
        themes, _ = ti.infer_theme(TAX, "分布式域名解析系统", "", body)
        tags = [p for p, _ in themes]
        self.assertIn("主题/网络/DNS", tags)

    def test_parent_fallback_when_subtag_weak(self):
        # 四个二级各零星提及一次：一级总够分，但没有哪个二级单独够分 → 回退 主题/AI。
        # 这是「≥2 篇才新开二级」约定的自动兜底，避免图谱里出现只有一篇的叶节点。
        body = "智能体 大模型 提示词 评测 " + BODY
        themes, _ = ti.infer_theme(TAX, "某综述", "", body)
        tags = [p for p, _ in themes]
        self.assertIn("主题/AI", tags)
        for t in tags:
            self.assertFalse(t.startswith("主题/AI/"), "不该出现二级：%s" % tags)

    def test_single_passing_mention_is_not_a_tag(self):
        # 只提了一次「智能体」不足以打标签 —— 宁可少打，也不要噪声
        themes, _ = ti.infer_theme(TAX, "无关标题", "", "智能体 " + BODY)
        self.assertEqual(themes, [])

    def test_no_theme_hit_returns_empty(self):
        tags, _ = ti.infer_theme(TAX, "无关标题", "", "天气不错，今天吃了面条。" * 50)
        self.assertEqual(tags, [])


class TestFinalize(unittest.TestCase):
    def test_fills_type_and_source(self):
        res = {"tags": ["主题/AI/RAG"], "theme_scores": [], "type": {}, "trace": [], "warnings": []}
        out = ti.finalize(res)
        self.assertIn("类型/技术教程", out)
        self.assertIn("来源/微信公众号", out)

    def test_keeps_existing(self):
        res = {"tags": ["主题/AI/RAG", "类型/方案实践", "来源/微信公众号"]}
        self.assertEqual(len(ti.finalize(res)), 3)


class TestTaxonomySelfCheck(unittest.TestCase):
    def test_taxonomy_is_wellformed(self):
        self.assertEqual(ti._self_test(TAX), 0)

    def test_every_subtag_has_keywords(self):
        for e in TAX["theme"]:
            self.assertTrue(e["kw"], "主题标签缺关键词：%s" % e["path"])
        for e in TAX["types"]:
            self.assertTrue(e["kw"] or e.get("kw_title"), "类型缺关键词：%s" % e["path"])


if __name__ == "__main__":
    unittest.main()
