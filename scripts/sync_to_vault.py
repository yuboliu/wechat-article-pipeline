# -*- coding: utf-8 -*-
"""把 <文章>.obsidian.md 落库到 Obsidian vault。

用法:
  python sync_to_vault.py "<文章目录名>" [--vault "<vault 根>"] [--base DIR]
                          [--subfolder 公众号] [--folder 自定义子目录]
                          [--update-index --summary "…"] [--display 短名]
                          [--section 段落] [--subgroup 小组]

约定（重要）:
  * --vault 传的是 **vault 根**，即那个装有 .obsidian 的目录。
    默认值按「命令行 > 环境变量 WECHAT_VAULT > 仓库根 .env > 报错」解析，
    所以「本机 vault 在哪」属于本机配置，不进版本库（见 scripts/env_config.py）。
    首次使用先跑 `python scripts/setup_env.py` 生成 .env。
  * 笔记落点 = vault/<subfolder>/<标题>/<标题>.md，默认 subfolder=公众号。
    这样才能让图片嵌入正确解析，否则图片会全挤进 vault/images/ 互相覆盖。
  * 只复制正文真正引用到的图片，推广图/二维码不复制（保持 vault 干净）。
  * 图片嵌入默认改写成 **vault 全路径**（`![[公众号/标题/images/x.png]]`）。
    原因：vault 开了 `alwaysUpdateLinks`，Obsidian 一打开笔记就会把 `![[images/x.png]]`
    改写成全路径；与其等它改，不如落库时就写对 —— 多篇笔记的 `img_001.png` 同名，
    相对写法在笔记未打开前是歧义的。

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
import sys
from pathlib import Path

import yaml

# scripts/ 下同目录导入：直接运行本文件时 python 会把 scripts/ 放进 sys.path，
# 但被当成模块 import（测试 / 其他脚本）时不会，所以显式补一次。
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import env_config  # noqa: E402

# 2026-09-23：原写死的 `~\WorkBuddy\微信公总号知识库\output` 已不存在，
# 无 --base 时会静默把 output 重建到死路径（pitfalls #18）。改为跟随当前工作目录，
# 与抓取器 wechat_article_to_markdown.py 的 DEFAULT_OUTPUT_DIR（cwd/output）保持一致。
DEFAULT_BASE = env_config.resolve_output_base()
DEFAULT_SUBFOLDER = env_config.DEFAULT_SUBFOLDER


def resolve_vault(cli=None, required=True) -> str:
    """解析 vault 根。转调 env_config，保留本函数名以兼容既有调用方。

    解析顺序见 env_config.resolve_vault()：命令行 > 环境变量 > .env > 报错。
    换 vault 目录时改 .env（跑 scripts/setup_env.py），**不要**把绝对路径写回代码。
    """
    return env_config.resolve_vault(cli=cli, required=required)


def resolve_subfolder(explicit=None) -> str:
    """解析落库的一级目录名。转调 env_config（支持 *公众号 这类通配）。"""
    return env_config.resolve_subfolder(cli=explicit)



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
    body = text[m.end():]

    # tags 交给 tag_infer 统一解析（兼容无缩进 / 2 空格缩进 / 行内写法）——
    # 这里原本只认 `^tags:\n- x`，一旦文件被 Obsidian Linter 重排过就读不到标签。
    try:
        from tag_infer import parse_frontmatter_tags
        tags = parse_frontmatter_tags(text)
    except Exception:
        tags = []

    mh = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if not mh:
        raise SystemExit("未找到 H1 标题")
    title = mh.group(1).strip()

    return title, tags, body.lstrip("\n")


# ---------------------------------------------------------------------------
# 图片嵌入路径改写
# ---------------------------------------------------------------------------
# wikilink 里有语法含义、或会让 Obsidian 解析歧义的字符：遇到就不改，保持相对写法
_LINK_UNSAFE = set("[]|#^")


def absolutize_images(body: str, folder: str) -> tuple:
    """把 `![[images/x.png]]` 改写成 `![[<folder>/images/x.png]]`。

    返回 (新正文, 改写张数)。folder 含 wikilink 保留字符时原样返回 —— 宁可不改，
    也不要写出一条点不开的链接。
    """
    if any(ch in folder for ch in _LINK_UNSAFE):
        return body, 0
    folder = folder.replace("\\", "/").strip("/")
    pat = re.compile(r"!\[\[images/([^\]]+)\]\]")
    n = len(pat.findall(body))
    if not n:
        return body, 0
    new = pat.sub(lambda m: "![[%s/images/%s]]" % (folder, m.group(1)), body)
    return new, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir_name", help="文章目录名（output 下的子目录）")
    ap.add_argument("--vault", default=None,
                    help="vault 根（含 .obsidian 的目录）；默认按 命令行 > 环境变量 "
                         "WECHAT_VAULT > 仓库根 .env 解析。未配置时报错并提示跑 "
                         "scripts/setup_env.py")
    ap.add_argument("--base", default=None,
                    help="output 根目录；默认按 WECHAT_OUTPUT_BASE > <当前目录>/output")
    ap.add_argument("--subfolder", default=None,
                    help="vault 下的一级分类目录；默认按 WECHAT_SUBFOLDER_PATTERN "
                         "通配解析（可匹配「【15】公众号」这类带前缀目录），回落「公众号」")
    ap.add_argument("--folder", help="vault 下的最终子目录（默认=<subfolder>/<标题>）")
    ap.add_argument("--relative-links", action="store_true",
                    help="图片保持 ![[images/x.png]] 相对写法，不改成 vault 全路径")
    ap.add_argument("--update-index", action="store_true",
                    help="落库后把这篇文章登记进《知识库索引》的主题导航")
    ap.add_argument("--summary", help="索引导航行破折号后的一句话价值点（agent 读全文后给）")
    ap.add_argument("--display", help="索引里显示的短名（默认与标题相同）")
    ap.add_argument("--section", help="强制指定索引段落（如 网络）")
    ap.add_argument("--subgroup", help="强制指定索引小组（如 DNS）")
    a = ap.parse_args()

    base = a.base or env_config.resolve_output_base()
    vault_str = resolve_vault(a.vault)          # 未配置 → 这里给出可操作的报错

    src_dir = Path(base) / a.dir_name
    src_md = src_dir / (a.dir_name + ".obsidian.md")
    text = src_md.read_text(encoding="utf-8")
    title, tags, body = extract(text)

    vault = Path(vault_str)
    if not vault.is_dir():
        raise SystemExit("vault 不存在：%s" % vault)
    if not (vault / ".obsidian").is_dir():
        print("  WARN: %s 下没有 .obsidian，确认这是 vault 根？" % vault)
    # 标题里的 `| : ? * " < > \ /` 是文件系统非法字符，必须先转义再做目录名/文件名。
    # H1 正文里保留原样（那是笔记内容），只有落点路径用转义后的名字。
    safe_title = safe_name(title)
    if safe_title != title:
        print("  标题含文件系统非法字符，路径已转义：%s" % safe_title)

    subfolder = resolve_subfolder(a.subfolder)
    folder = a.folder or "%s/%s" % (subfolder, safe_title)
    print("VAULT :", vault)
    print("FOLDER:", folder)

    if not a.relative_links:
        body, n_img = absolutize_images(body, folder)
        if n_img:
            print("  图片嵌入改写为 vault 全路径：%d 张" % n_img)

    note_path = create_note(vault, safe_title, body, folder=folder, tags=tags)
    # 保底：万一将来换回会翻 \n 的写入方式，这里统一回 LF，避免同批笔记出现两种换行符。
    raw = note_path.read_bytes()
    if b"\r\n" in raw:
        note_path.write_bytes(raw.replace(b"\r\n", b"\n"))
        print("  换行符归一化：CRLF -> LF")
    print("NOTE:", note_path)
    print("TAGS:", tags)

    refs = sorted(set(re.findall(r"!\[\[([^\]]*?/?images/[^\]]+)\]\]", body)))
    dst_img_dir = vault / folder / "images"
    dst_img_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for ref in refs:
        name = ref.rsplit("/", 1)[-1]
        src = src_dir / "images" / name
        if not src.exists():
            print("  MISSING SOURCE:", name)
            continue
        shutil.copy2(src, dst_img_dir / name)
        copied += 1
        print("  IMG copied:", name, src.stat().st_size, "bytes")
    print("引用 %d 张 / 复制 %d 张" % (len(refs), copied))

    if a.update_index:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in os.sys.path:
            os.sys.path.insert(0, here)
        import update_index as ui
        try:
            idx_path = ui.find_index(vault)
        except SystemExit as e:
            print("  跳过索引更新：%s" % e)
            return
        print("\n--- 索引更新 ---")
        if not a.summary:
            print("  WARN: 没给 --summary，导航行只有 [[链接]] 没有一句话价值点。"
                  "agent 读完全文后应补上并重跑本参数。")
        ui.update_index(idx_path, tags, title, display=a.display, summary=a.summary,
                        section=a.section, subgroup=a.subgroup)


if __name__ == "__main__":
    main()
