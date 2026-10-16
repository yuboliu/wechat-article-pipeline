# -*- coding: utf-8 -*-
"""把 <文章>.obsidian.md 落库到 Obsidian vault。

用法:
  python sync_to_vault.py "<文章目录名>" [--vault "<vault 根>"] [--base DIR]
                          [--subfolder 公众号] [--folder 自定义子目录]

约定（重要）:
  * --vault 传的是 **vault 根**，即那个装有 .obsidian 的目录。
    默认值按 `WECHAT_VAULT` 环境变量 → 同目录 `local_config.py` → `~/iNote` 的顺序解析，
    所以「本机 vault 在哪」属于本机配置，不进版本库（见 resolve_vault()）。
  * 笔记落点 = vault/<subfolder>/<标题>/<标题>.md，默认 subfolder=公众号。
    这样才能让 ![[images/xxx]] 这种相对嵌入正确解析，否则图片会全挤进 vault/images/ 互相覆盖。
  * 只复制正文真正引用到的图片，推广图/二维码不复制（保持 vault 干净）。

依赖:
  * 只用 pyyaml（写 frontmatter）。跑法用本 skill 自带 venv：
      <skill>/.venv/Scripts/python.exe
  * 2026-09-23 起**不再依赖 obsidian-direct**（该 skill 已卸载）。create_note 的实现
    已内联到本文件底部，输出与原 obsidian-direct 版本逐字节一致（含 yaml.dump 的
    allow_unicode / default_flow_style=False 参数），历史笔记重跑不会变形。
"""
import argparse
import datetime
import os
import re
import shutil
from pathlib import Path

import yaml

# 2026-09-23：原写死的 `~\WorkBuddy\微信公总号知识库\output` 已不存在，
# 无 --base 时会静默把 output 重建到死路径（pitfalls #18）。改为跟随当前工作目录，
# 与抓取器 wechat_article_to_markdown.py 的 DEFAULT_OUTPUT_DIR（cwd/output）保持一致。
DEFAULT_BASE = str(Path.cwd() / "output")
DEFAULT_SUBFOLDER = "公众号"


def resolve_vault() -> str:
    """解析 vault 根（那个装有 .obsidian 的目录）。

    取值优先级 —— 这样同一份代码能在不同机器上跑，而本机绝对路径不必进版本库：
      1. 环境变量 `WECHAT_VAULT`
      2. 同目录 `local_config.py` 里的 `DEFAULT_VAULT`（本机专用，已 gitignore）
      3. 中性默认 `~/iNote`

    换 vault 目录时：优先改本机 `local_config.py`，不要把绝对路径写回这里。
    """
    env = os.environ.get("WECHAT_VAULT")
    if env:
        return env
    try:
        from local_config import DEFAULT_VAULT as local_vault
    except ImportError:
        local_vault = None
    if local_vault:
        return str(local_vault)
    return str(Path.home() / "iNote")


DEFAULT_VAULT = resolve_vault()
DEFAULT_SUBFOLDER = "公众号"


# ---------------------------------------------------------------------------
# 以下两个函数内联自 obsidian-direct 的 scripts/obsidian_cli.py（行为保持等价）
# ---------------------------------------------------------------------------
def format_frontmatter(fm: dict) -> str:
    """Format dict as YAML frontmatter."""
    if not fm:
        return ""
    return "---\n" + yaml.dump(fm, allow_unicode=True, default_flow_style=False) + "---\n\n"


def safe_name(title: str) -> str:
    """把标题转成合法的文件/目录名（供落库使用）。

    规则与抓取器 `wechat_article_to_markdown.py` 完全一致：把 `[ / \\ ? % * : | " < > ]`
    换成 `_`，截断 80 字符，并去掉结尾的点与空格 —— 这样 vault 里的文件夹名与
    `output/` 下的目录名相同，两处可以互相追溯。

    必要性：微信标题里常见 ASCII `|`（如「F5 数字图书馆 | DNS over HTTPS (DOH)架构」），
    而 Windows 文件名不允许 `| : ? * " < > \\ /`，直接用会
    `OSError: [WinError 123] 文件名、目录名或卷标语法不正确`。
    """
    name = re.sub(r'[/\\?%*:|"<>]', "_", title).strip()
    name = (name or "untitled")[:80]
    return name.rstrip(". ")


def create_note(vault: Path, title: str, content: str = "", folder: str = None,
                tags: list = None) -> Path:
    """Create a new note，返回笔记路径。"""
    note_dir = vault / folder if folder else vault
    note_dir.mkdir(parents=True, exist_ok=True)

    safe_title = re.sub(r'[<>:"/\\|?*]', "", title)
    note_path = note_dir / ("%s.md" % safe_title)

    fm = {"created": datetime.datetime.now().isoformat()}
    if tags:
        fm["tags"] = tags

    full_content = format_frontmatter(fm) + content
    # 显式 newline="\n"，避免 Windows 下 write_text 把 \n 翻成 \r\n（vault 既有笔记统一 LF）
    with open(note_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(full_content)

    return note_path


def extract(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        raise SystemExit("未找到 frontmatter")
    fm_raw, body = m.group(1), text[m.end():]

    mt = re.search(r"^tags:\n((?:- .+$\n?)+)", fm_raw, re.MULTILINE)
    tags = [t.lstrip("- ").strip() for t in mt.group(1).splitlines()] if mt else []

    mh = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if not mh:
        raise SystemExit("未找到 H1 标题")
    title = mh.group(1).strip()

    return title, tags, body.lstrip("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir_name", help="文章目录名（output 下的子目录）")
    ap.add_argument("--vault", default=DEFAULT_VAULT,
                    help="vault 根（含 .obsidian 的目录）；默认 WECHAT_VAULT 环境变量 > "
                         "scripts/local_config.py > ~/iNote")
    ap.add_argument("--base", default=DEFAULT_BASE, help="output 根目录")
    ap.add_argument("--subfolder", default=DEFAULT_SUBFOLDER,
                    help="vault 下的一级分类目录，默认 公众号")
    ap.add_argument("--folder", help="vault 下的最终子目录（默认=<subfolder>/<标题>）")
    a = ap.parse_args()

    src_dir = Path(a.base) / a.dir_name
    src_md = src_dir / (a.dir_name + ".obsidian.md")
    text = src_md.read_text(encoding="utf-8")
    title, tags, body = extract(text)

    vault = Path(a.vault)
    if not vault.is_dir():
        raise SystemExit("vault 不存在：%s" % vault)
    if not (vault / ".obsidian").is_dir():
        print("  WARN: %s 下没有 .obsidian，确认这是 vault 根？" % vault)
    # 标题里的 `| : ? * " < > \ /` 是文件系统非法字符，必须先转义再做目录名/文件名。
    # H1 正文里保留原样（那是笔记内容），只有落点路径用转义后的名字。
    safe_title = safe_name(title)
    if safe_title != title:
        print("  标题含文件系统非法字符，路径已转义：%s" % safe_title)
    folder = a.folder or "%s/%s" % (a.subfolder, safe_title)
    print("VAULT :", vault)
    print("FOLDER:", folder)

    note_path = create_note(vault, safe_title, body, folder=folder, tags=tags)
    # 保底：万一将来换回会翻 \n 的写入方式，这里统一回 LF，避免同批笔记出现两种换行符。
    raw = note_path.read_bytes()
    if b"\r\n" in raw:
        note_path.write_bytes(raw.replace(b"\r\n", b"\n"))
        print("  换行符归一化：CRLF -> LF")
    print("NOTE:", note_path)
    print("TAGS:", tags)

    refs = sorted(set(re.findall(r"!\[\[images/([^\]]+)\]\]", body)))
    dst_img_dir = vault / folder / "images"
    dst_img_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in refs:
        src = src_dir / "images" / name
        if not src.exists():
            print("  MISSING SOURCE:", name)
            continue
        shutil.copy2(src, dst_img_dir / name)
        copied += 1
        print("  IMG copied:", name, src.stat().st_size, "bytes")
    print("引用 %d 张 / 复制 %d 张" % (len(refs), copied))


if __name__ == "__main__":
    main()
