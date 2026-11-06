# -*- coding: utf-8 -*-
"""校验器 · 图片计数检查（verify_wechat_md.check_image_count）回归测试。

守一个边界：**零引用且没有 images/ 目录 → PASS**。
纯文本类文章（研报解读、政策原文）裁掉推广后可能一张图都不剩，落库时不会建
`images/` 目录；旧逻辑见到「目录不存在」就判 WARN，于是每篇纯文本笔记都挂着
「建议人工过目」，把真正的告警淹掉（2026-11-06 思科 Splunk 那篇就是）。
有引用却找不到目录，仍然必须 WARN —— 那才是真的缺图。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts"))

import verify_wechat_md as v  # noqa: E402


class ImageCountTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, text, images_dir):
        rep = v.Report()
        v.check_image_count(text, str(images_dir), rep)
        name, status, details = rep.items[0]
        return status, details

    def test_no_refs_no_dir_is_pass(self):
        status, details = self._run("正文，没有任何图片。\n", self.dir / "images")
        self.assertEqual(v.PASS, status, details)

    def test_refs_without_dir_is_warn(self):
        status, details = self._run("![[images/img_001.png]]\n", self.dir / "images")
        self.assertEqual(v.WARN, status, details)

    def test_refs_and_matching_files_is_pass(self):
        d = self.dir / "images"
        d.mkdir()
        (d / "img_001.png").write_bytes(b"x")
        status, details = self._run("![[images/img_001.png]]\n", d)
        self.assertEqual(v.PASS, status, details)

    def test_vault_full_path_form_is_recognized(self):
        """落库后是 `![[【15】公众号/【030】标题/images/x.png]]`，也要认得出引用。"""
        d = self.dir / "images"
        d.mkdir()
        (d / "x.png").write_bytes(b"x")
        status, details = self._run("![[【15】公众号/【030】标题/images/x.png]]\n", d)
        self.assertEqual(v.PASS, status, details)


if __name__ == "__main__":
    unittest.main()
