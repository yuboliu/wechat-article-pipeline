# -*- coding: utf-8 -*-
"""落库前文末处理（scripts/sync_to_vault.py::strip_tail_tags）的回归测试。

守的是「旧产物不能让已清理的内容复活」：2026-11-04 起新流水线不再写文末裸标签行，
vault 里 28 篇也统一清掉了；但 `output/` 下的旧 `.obsidian.md` 仍带着，
重新落库就会抄回去。这里验证落库阶段那道幂等兜底。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts"))

try:
    import sync_to_vault as sv  # noqa: E402
except ImportError as e:          # 缺 pyyaml 时跳过，不让测试环境差异变成红灯
    sv = None
    _skip_reason = str(e)


@unittest.skipIf(sv is None, "sync_to_vault 依赖未安装")
class StripTailTagsTest(unittest.TestCase):
    def test_removes_trailing_tag_line(self):
        body = "# 标题\n\n正文最后一句。\n\n#DNS #DoH #F5\n"
        new, dropped = sv.strip_tail_tags(body)
        self.assertTrue(dropped)
        self.assertTrue(new.endswith("正文最后一句。\n"))
        self.assertNotIn("#DNS", new)

    def test_no_tag_line_untouched(self):
        body = "# 标题\n\n正文。\n"
        new, dropped = sv.strip_tail_tags(body)
        self.assertFalse(dropped)
        self.assertEqual(new, body)

    def test_single_hash_word_is_not_tag_line(self):
        """只有一个 `#词` 不算标签行：可能是正文里的话题词或标题残留，别乱删。"""
        body = "# 标题\n\n#单独一个词\n"
        new, dropped = sv.strip_tail_tags(body)
        self.assertFalse(dropped)

    def test_middle_tag_line_kept(self):
        """正文中间的同类行不动 —— 删了就是丢内容。"""
        body = "# 标题\n\n#A #B\n\n后面还有正文。\n"
        new, dropped = sv.strip_tail_tags(body)
        self.assertFalse(dropped)
        self.assertIn("#A #B", new)

    def test_trailing_blank_lines_collapsed(self):
        body = "# 标题\n\n正文。\n\n#A #B\n\n\n"
        new, dropped = sv.strip_tail_tags(body)
        self.assertTrue(dropped)
        self.assertEqual(new, "# 标题\n\n正文。\n")

    def test_idempotent(self):
        body = "# 标题\n\n正文。\n\n#A #B\n"
        once, _ = sv.strip_tail_tags(body)
        twice, dropped = sv.strip_tail_tags(once)
        self.assertFalse(dropped)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
