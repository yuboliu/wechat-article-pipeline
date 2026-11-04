# -*- coding: utf-8 -*-
"""落库编号（scripts/sync_to_vault.py 的 find_numbered / next_number）回归测试。

命名的约定是 `【15】公众号/【015】标题/【015】标题.md`。守两件事：
  * 重跑同一篇 → **复用**已有编号，不能新建一个未编号的孪生目录；
  * 新笔记 → 接在目录内最大号后面，编号连续。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts"))

try:
    import sync_to_vault as sv  # noqa: E402
except ImportError as e:
    sv = None
    _skip_reason = str(e)


@unittest.skipIf(sv is None, "sync_to_vault 依赖未安装")
class NumberingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.parent = Path(self.tmp.name) / "【15】公众号"
        self.parent.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _mk(self, name):
        (self.parent / name).mkdir()

    def test_next_number_starts_at_one(self):
        self.assertEqual(sv.next_number(self.parent), 1)

    def test_next_number_is_max_plus_one(self):
        for n in ("【001】A", "【007】B", "【003】C"):
            self._mk(n)
        self.assertEqual(sv.next_number(self.parent), 8, "应取最大号 7 加一，不是按数量算")

    def test_next_number_ignores_non_numbered(self):
        self._mk("旧目录")
        self._mk("【004】X")
        self.assertEqual(sv.next_number(self.parent), 5)

    def test_find_numbered_hits_existing(self):
        self._mk("【012】F5 数字图书馆 _ DNS over HTTPS (DOH)架构")
        hit = sv.find_numbered(self.parent, "F5 数字图书馆 _ DNS over HTTPS (DOH)架构")
        self.assertIsNotNone(hit, "重跑时必须认出已编号目录")
        self.assertEqual(hit[1], 12)

    def test_find_numbered_ignores_partial_title(self):
        """`【012】长标题` 不能被当成短标题的命中。"""
        self._mk("【012】F5 数字图书馆")
        self.assertIsNone(sv.find_numbered(self.parent, "DNS 架构"))

    def test_find_numbered_none_when_absent(self):
        self._mk("【001】别的笔记")
        self.assertIsNone(sv.find_numbered(self.parent, "全新的一篇"))

    def test_three_digit_padding(self):
        self._mk("【028】最后一篇")
        n = sv.next_number(self.parent)
        self.assertEqual("【%03d】新笔记" % n, "【029】新笔记")

    def test_numbered_name_roundtrip(self):
        """编号后的目录名再被 find_numbered 认出来，保证幂等链条闭合。"""
        name, _ = sv.find_numbered(self.parent, "不存在") or (None, None)
        self.assertIsNone(name)
        self._mk("【005】回环测试")
        name, num = sv.find_numbered(self.parent, "回环测试")
        self.assertEqual((name, num), ("【005】回环测试", 5))


if __name__ == "__main__":
    unittest.main()
