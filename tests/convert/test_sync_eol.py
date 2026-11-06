# -*- coding: utf-8 -*-
"""落库行尾（sync_to_vault.detect_vault_eol / create_note）回归测试。

背景（pitfalls #69）：`create_note()` 曾经写死 `newline="\\n"`，注释还写着
「vault 既有笔记统一 LF」。但 2026-11-06 实测本机 vault：63 篇 CRLF、8 篇 LF ——
Obsidian 在 Windows 上保存的笔记是 CRLF，而被 update_index 反复重写过的索引页是 LF。
结果新落库的笔记与全库不一致，`git diff` / OneDrive 版本比对时整篇都算改动。

现在的行为是**探测已有笔记的主流行尾并跟随**，而不是写死也不是猜。
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
class EolFollowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        (self.vault / ".obsidian").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _seed(self, eol, n=3):
        for i in range(n):
            (self.vault / ("note%d.md" % i)).write_bytes(
                ("第一行" + eol + "第二行" + eol).encode("utf-8"))

    def _written(self):
        p = sv.create_note(self.vault, "新笔记", "正文第一段\n\n正文第二段\n", tags=["类型/技术教程"])
        return p.read_bytes()

    def test_crlf_vault_gets_crlf(self):
        self._seed("\r\n")
        data = self._written()
        self.assertGreater(data.count(b"\r\n"), 0)
        self.assertEqual(0, data.count(b"\n") - data.count(b"\r\n"), "不应残留裸 LF")
        self.assertNotIn(b"\r\r\n", data, "不能出现二次转义")

    def test_lf_vault_gets_lf(self):
        self._seed("\n")
        data = self._written()
        self.assertEqual(0, data.count(b"\r\n"), "纯 LF 库里不应出现 CRLF")
        self.assertGreater(data.count(b"\n"), 0)

    def test_empty_vault_defaults_to_crlf(self):
        """一个样本都没有时按 Windows 惯例取 CRLF。"""
        data = self._written()
        self.assertGreater(data.count(b"\r\n"), 0)
        self.assertNotIn(b"\r\r\n", data)

    def test_dot_dirs_are_ignored(self):
        """.obsidian/ 下的 .md（插件缓存等）不参与投票。"""
        self._seed("\r\n")
        for i in range(10):
            (self.vault / ".obsidian" / ("cache%d.md" % i)).write_bytes(b"a\nb\nc\n")
        self.assertEqual("\r\n", sv.detect_vault_eol(self.vault))

    def test_mixed_content_is_normalized(self):
        """content 里已经混了 \\r\\n 时不能变成 \\r\\r\\n。"""
        self._seed("\r\n")
        p = sv.create_note(self.vault, "混合", "甲\r\n乙\n丙\n")
        data = p.read_bytes()
        self.assertNotIn(b"\r\r\n", data)


if __name__ == "__main__":
    unittest.main()
