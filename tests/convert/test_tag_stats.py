# -*- coding: utf-8 -*-
"""标签体系计数重算（scripts/tag_stats.py）的回归测试（纯标准库）。

这里守三件事：
  * 只改数字 —— 标签名、顺序、判定标准等人工内容不能被碰；
  * 幂等 —— 同一份 vault 跑第二遍零改动；
  * 两种显示写法都要认 —— 主题表里的短名（`智能体`）与「其他」行里的
    半截路径（`行业/银行` → 库里实际是 `主题/行业/银行`）。
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
| `主题/AI` | 智能体 1 · RAG 1 |
| `主题/政治` | 暂为一级标签（9 篇），达 2 篇后开二级 |
| 其他 | `行业/银行` 7 · `管理` 7 |

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
        # 半截路径 `行业/银行` 要能对上库里的 `主题/行业/银行`
        self.assertIn("`行业/银行` 1", t)
        # `管理` 是裸名，按末段同名唯一匹配
        self.assertIn("`管理` 1", t)
        # 政治行只改括号里的数，说明性文字原样保留
        self.assertIn("暂为一级标签（1 篇），达 2 篇后开二级", t)
        # 类型 / 来源（表格单元格按显示宽度补过空格，比对前先归一化）
        self.assertIn("| `类型/技术教程` | 2 | 从零入门/系统讲解 |", t)
        self.assertIn("`来源/微信公众号` 2", t)
        # 总量与分布：4 = 3 篇笔记 + 索引页自身
        self.assertIn("全库 **4 篇笔记**", t)
        self.assertIn("`【15】公众号` 2", t)

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

    def test_zero_kept_by_default_pruned_on_demand(self):
        """库里数不到的二级：默认保留并置 0，加 prune_zero 才删。"""
        ts.refresh(self.index, self.vault, apply=True)
        # 把唯一带 RAG 的笔记改掉，RAG 计数应归零
        (self.vault / "【15】公众号" / "b.md").write_text(
            _note(["主题/AI/智能体", "类型/技术教程", "来源/微信公众号"]), encoding="utf-8")
        ts.refresh(self.index, self.vault, apply=True)
        self.assertIn("RAG 0", self._text(), "默认应保留该项并置 0")
        ts.refresh(self.index, self.vault, apply=True, prune_zero=True)
        self.assertNotIn("RAG 0", self._text())

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
