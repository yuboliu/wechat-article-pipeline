"""pytest 根配置：让两套测试都能找到被测模块。

目录约定：

- 抓取脚本 `wechat_article_to_markdown.py` 在**仓库根**（与上游 jackwener 的布局一致，
  这样 `git merge upstream/main` 时路径不漂移）；
- 转换 / 落库 / 校验脚本在 `scripts/`。

两处都插入 `sys.path`，于是：

    python -m pytest tests/ -q -m "not e2e"

一条命令即可同时跑抓取器的 pytest 用例与转换器的 unittest 用例。
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

for _path in (ROOT, os.path.join(ROOT, "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)
