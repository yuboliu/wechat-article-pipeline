# -*- coding: utf-8 -*-
"""标签体系计数重算（scripts/tag_stats.py）的回归测试（纯标准库）。

这里守五件事：
  * 只改数字与条目 —— 标签名、行顺序、判定标准等人工内容不能被碰；
  * 幂等 —— 同一份 vault 跑第二遍零改动；
  * 三种显示写法都要认 —— 短名（`智能体`）、半截路径（`行业/银行` →
    库里 `主题/行业/银行`）、完整路径；
  * 不漏项 —— 库里有一级标签而表里没这一行时，必须补整行；
  * 不猜 —— 同名多义时报错，绝不静默取 0。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts"))
import tag_stats as ts  # noqa: E402

INDEX = """---
tags:
  - 类型/索引
  - 来源/个人整理
---
# 知识库索引

> 全库 **3 篇笔记**的统一入口。
> 分布：`【15】公众号` 2 · 根目录 1（本页）。

---

## 一、标签体系

### 1. 主题 `主题/…`

| 一级 | 二级标签（覆盖笔记数） |
| ---- | ---- |
| `主题/AI` | 智能体 5 · RAG 5 |
| `主题/政治` | 暂为一级标签（9 篇），达 2 篇后开二级 |
| `主题/行业` | 银行 7 |
| `主题/管理` | 一级直挂（7 篇）——暂无二级 |

### 2. 类型 `类型/…`

| 标签 | 数 | 判定标准 |
| ---- | ---- | ---- |
| `类型/技术教程` | 9 | 从零入门/系统讲解 |
| `类型/索引` | 9 | 本页 |

### 3. 来源 `来源/…`

`来源/个人整理` 9 · `来源/微信公众号` 9

### 4. 维护约定

1. 别造同义标签。

---

## 二、按主题导航
"""


def _note(tags):
    body = "".join("  - %s\n" % t for t in tags)
    return "---\ntags:\n%s---\n\n# 标题\n\n正文。\n" % body


def _norm(text):
    """把连续空白压成一个空格：表格单元格会按显示宽度补空格，不适合逐字比对。"""
    return " ".join(text.split())


class TagStatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        (self.vault / "【15】公众号").mkdir()
        # 3 篇有内容的笔记 + 索引页自身
        (self.vault / "【15】公众号" / "a.md").write_text(
            _note(["主题/AI/智能体", "主题/行业/银行", "类型/技术教程", "来源/微信公众号"]),
            encoding="utf-8")
        (self.vault / "【15】公众号" / "b.md").write_text(
            _note(["主题/AI/智能体", "主题/AI/RAG", "主题/管理", "类型/技术教程",
                   "来源/微信公众号"]),
            encoding="utf-8")
        (self.vault / "c.md").write_text(
            _note(["主题/政治", "类型/索引", "来源/个人整理"]), encoding="utf-8")
        self.index = self.vault / "【91】知识库索引.md"
        self.index.write_text(INDEX, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _text(self):
        return self.index.read_text(encoding="utf-8")

    def test_counts_recomputed(self):
        ts.refresh(self.index, self.vault, apply=True)
        t = _norm(self._text())
        # 智能体 2 篇、RAG 1 篇；顺序按数量降序
        self.assertIn("智能体 2 · RAG 1", t)
        # 半截路径/短名都要能对上库里的完整标签
        self.assertIn("`主题/行业` | 银行 1", t)
        # 一级直挂：`主题/管理` 被 1 篇笔记直接使用
        self.assertIn("一级直挂（1 篇）——暂无二级", t)
        # 政治行只改括号里的数，说明性文字原样保留
        self.assertIn("暂为一级标签（1 篇），达 2 篇后开二级", t)
        # 类型 / 来源（表格单元格按显示宽度补过空格，比对前先归一化）
        self.assertIn("| `类型/技术教程` | 2 | 从零入门/系统讲解 |", t)
        self.assertIn("`来源/微信公众号` 2", t)
        # 总量与分布：4 = 3 篇笔记 + 索引页自身
        self.assertIn("全库 **4 篇笔记**", t)
        self.assertIn("`【15】公众号` 2", t)

    def test_missing_l1_row_appended(self):
        """库里出现了表里没有的一级标签 → 必须补整行，否则这部分笔记不计入任何数字。"""
        (self.vault / "【15】公众号" / "f.md").write_text(
            _note(["主题/安全/攻防", "类型/技术教程", "来源/微信公众号"]), encoding="utf-8")
        ts.refresh(self.index, self.vault, apply=True)
        t = _norm(self._text())
        self.assertIn("`主题/安全` | 攻防 1", t)

    def test_direct_l1_count_updated(self):
        """一级直挂的篇数也要跟着库走。"""
        (self.vault / "【15】公众号" / "g.md").write_text(
            _note(["主题/管理", "类型/技术教程", "来源/微信公众号"]), encoding="utf-8")
        ts.refresh(self.index, self.vault, apply=True)
        self.assertIn("一级直挂（2 篇）", _norm(self._text()))

    def test_ambiguous_short_name_raises(self):
        """同名不同路径时不能猜：要么写成完整路径，要么报错中止。"""
        (self.vault / "【15】公众号" / "h.md").write_text(
            _note(["主题/工程/提示词", "类型/技术教程", "来源/微信公众号"]), encoding="utf-8")
        (self.vault / "【15】公众号" / "i.md").write_text(
            _note(["主题/金融/提示词", "类型/技术教程", "来源/微信公众号"]), encoding="utf-8")
        text = self._text().replace("智能体 5 · RAG 5", "智能体 5 · 提示词 5")
        self.index.write_text(text, encoding="utf-8")
        with self.assertRaises(ts.AmbiguousTag):
            ts.refresh(self.index, self.vault, apply=True)

    def test_ambiguous_full_path_ok(self):
        """写成完整路径就没有歧义，能精准计数。"""
        (self.vault / "【15】公众号" / "h.md").write_text(
            _note(["主题/工程/提示词", "类型/技术教程", "来源/微信公众号"]), encoding="utf-8")
        (self.vault / "【15】公众号" / "i.md").write_text(
            _note(["主题/金融/提示词", "类型/技术教程", "来源/微信公众号"]), encoding="utf-8")
        text = self._text().replace("智能体 5 · RAG 5", "智能体 5 · `主题/工程/提示词` 5")
        self.index.write_text(text, encoding="utf-8")
        ts.refresh(self.index, self.vault, apply=True)
        self.assertIn("`主题/工程/提示词` 1", _norm(self._text()))

    def test_idempotent(self):
        ts.refresh(self.index, self.vault, apply=True)
        first = self._text()
        n = ts.refresh(self.index, self.vault, apply=True)
        self.assertEqual(n, 0, "第二次运行不应再有改动")
        self.assertEqual(first, self._text())

    def test_does_not_touch_prose(self):
        before = self._text()
        ts.refresh(self.index, self.vault, apply=True)
        after = self._text()
        self.assertIn("1. 别造同义标签。", after)
        # 导航区不应被碰
        self.assertEqual(before.split("## 二、按主题导航")[1],
                         after.split("## 二、按主题导航")[1])

    def test_missing_subtag_appended(self):
        (self.vault / "【15】公众号" / "d.md").write_text(
            _note(["主题/AI/上下文工程", "类型/技术教程", "来源/微信公众号"]),
            encoding="utf-8")
        ts.refresh(self.index, self.vault, apply=True)
        self.assertIn("上下文工程 1", self._text())

    def test_missing_type_row_appended(self):
        (self.vault / "【15】公众号" / "e.md").write_text(
            _note(["主题/AI/智能体", "类型/趋势解读", "来源/微信公众号"]), encoding="utf-8")
        ts.refresh(self.index, self.vault, apply=True)
        t = self._text()
        self.assertIn("`类型/趋势解读`", t)
        self.assertIn("（待补判定标准）", t)

    def test_zero_pruned_by_default(self):
        """库里数不到的二级：默认删掉（索引只列真实存在的）。"""
        ts.refresh(self.index, self.vault, apply=True)
        # 把唯一带 RAG 的笔记改掉，RAG 计数应归零
        (self.vault / "【15】公众号" / "b.md").write_text(
            _note(["主题/AI/智能体", "类型/技术教程", "来源/微信公众号"]), encoding="utf-8")
        ts.refresh(self.index, self.vault, apply=True)
        self.assertNotIn("RAG", self._text(), "默认应删除该项")

    def test_keep_zero_keeps_zero(self):
        ts.refresh(self.index, self.vault, apply=True)
        (self.vault / "【15】公众号" / "b.md").write_text(
            _note(["主题/AI/智能体", "类型/技术教程", "来源/微信公众号"]), encoding="utf-8")
        ts.refresh(self.index, self.vault, apply=True, keep_zero=True)
        self.assertIn("RAG 0", self._text())

    def test_empty_l1_row_removed(self):
        """一级标签在库里彻底消失时，整行删掉，不留 0。"""
        (self.vault / "c.md").write_text(
            _note(["类型/索引", "来源/个人整理"]), encoding="utf-8")
        ts.refresh(self.index, self.vault, apply=True)
        self.assertNotIn("主题/政治", self._text())

    def test_dot_dirs_ignored(self):
        """`.claudian` 这类工具目录不能计入全库篇数。"""
        d = self.vault / ".claudian"
        d.mkdir()
        (d / "system.md").write_text(_note(["主题/AI/智能体"]), encoding="utf-8")
        counter, folders, total, _ = ts.collect(self.vault)
        self.assertEqual(total, 4, "点开头目录里的 md 不应计入（4 = 3 篇 + 索引页）")
        self.assertNotIn(".claudian", folders)
        self.assertEqual(counter["主题/AI/智能体"], 2)

    def test_display_width_pads_cjk(self):
        ts.refresh(self.index, self.vault, apply=True)
        rows = [ln for ln in self._text().splitlines()
                if ln.startswith("| `主题/AI`") or ln.startswith("| `主题/政治`")]
        self.assertTrue(rows)
        widths = {ts._disp(r) for r in rows}
        self.assertEqual(len(widths), 1, "同一张表的行显示宽度应一致（CJK 按 2 计）")


if __name__ == "__main__":
    unittest.main()
