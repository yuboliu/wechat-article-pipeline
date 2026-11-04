# -*- coding: utf-8 -*-
r"""生成 .env —— 首次配置向导。

为什么要有这个脚本
------------------
`.env` 里装的是本机绝对路径（vault 在哪），**不能进版本库**；而 `.env.example`
只是占位符。新机器 clone 下来第一件事就是跑一次本向导，于是「仓库公开」与
「路径私有」两件事同时成立。

用法
----
    # 体检（只看当前解析结果，不写盘；输出不含完整路径，可安全粘贴）
    python scripts/setup_env.py --check

    # 交互向导（推荐；会列出现有 vault 的候选目录让你选）
    python scripts/setup_env.py

    # 非交互（agent / CI 用；值从命令行来）
    python scripts/setup_env.py --vault "D:/Vault" --subfolder-pattern "*公众号"

    # 覆盖已有 .env（默认拒绝覆盖）
    python scripts/setup_env.py --vault "D:/Vault" --force

安全约定
--------
* 写出的 .env 权限尽量收紧（POSIX 下 0600）；Windows 上靠目录权限，不再额外处理。
* 已存在的 .env 默认**不覆盖**，除非显式 --force（避免把用户手写的高级项冲掉）。
* 全程不打印、不落盘任何与 vault 无关的个人信息。
"""
import argparse
import os
import stat
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import env_config  # noqa: E402

HEADER = """\
# ============================================================================
# wechat-article-pipeline 本机配置
# ----------------------------------------------------------------------------
# 这个文件**不会**进版本库（见 .gitignore）。仓库里的公开模板是 .env.example。
# 换机器 / 换 vault 时只改这里，不要改动任何 .py 脚本。
# 由 scripts/setup_env.py 生成于 {when}
# ============================================================================

# 【必填】Obsidian vault 根目录 —— 那个里面有 .obsidian 文件夹的目录
WECHAT_VAULT={vault}

# 落库的一级目录。两种写法二选一：
#   写通配模式 → 目录改名/加编号前缀都不用再动配置（推荐）
#   写死名字   → 精确，但目录一改名就要改这里
WECHAT_SUBFOLDER_PATTERN={sub_pattern}{sub_literal}

# 索引页文件名通配（vault 根下）
WECHAT_INDEX_PATTERN={index_pattern}

# ---- 以下留空即用默认值，一般不用改 ----------------------------------------
# 抓取/转换产物根目录，默认 <当前工作目录>/output
# WECHAT_OUTPUT_BASE=

# 本机解释器（仅作备忘，脚本不读）
# WECHAT_PYTHON={python}
"""


def _now():
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm(p):
    """统一成当前平台的写法并展开 ~。写入 .env 时用绝对路径。"""
    return str(Path(os.path.expanduser(p)).resolve())


def _detect_subfolders(vault: Path):
    """在 vault 下找可能是「公众号」的目录，供交互选择。"""
    hits = []
    if not vault.is_dir():
        return hits
    for child in sorted(vault.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if "公众号" in child.name:
            hits.append(child.name)
    return hits


def _prompt(default="", tip=""):
    suffix = " [%s]" % default if default else ""
    if tip:
        print("  %s" % tip)
    try:
        raw = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit("已取消，未写入任何文件。")
    return raw or default


def interactive_wizard(existing: dict):
    """交互式收集配置。返回 dict。"""
    print("=" * 70)
    print("wechat-article-pipeline 配置向导")
    print("=" * 70)

    cur = existing.get("WECHAT_VAULT") or ""
    print("\n[1/3] vault 根目录（那个里面有 .obsidian 的目录）")
    if cur:
        print("  当前配置：%s" % cur)
    vault_raw = _prompt(cur, "直接回车沿用当前值；输入新路径则替换")
    if not vault_raw:
        raise SystemExit("vault 是必填项，已取消。")
    vault = Path(os.path.expanduser(vault_raw))
    if not vault.is_dir():
        raise SystemExit("目录不存在：%s" % vault)
    if not (vault / ".obsidian").is_dir():
        print("  ! 该目录下没有 .obsidian —— 可能不是 vault 根，仍继续。")

    print("\n[2/3] 落库的一级目录")
    cands = _detect_subfolders(vault)
    if cands:
        print("  vault 下检测到这些候选：")
        for i, name in enumerate(cands, 1):
            print("    %d) %s" % (i, name))
        print("  直接回车 = 用通配 *公众号（目录改名也不用改配置，推荐）")
        ans = _prompt("")
        if ans.isdigit() and 1 <= int(ans) <= len(cands):
            sub_literal = cands[int(ans) - 1]
            sub_pattern = env_config.DEFAULT_SUBFOLDER_PATTERN
        else:
            sub_literal = ""
            sub_pattern = env_config.DEFAULT_SUBFOLDER_PATTERN
    else:
        print("  没检测到含「公众号」的目录，将使用通配 *公众号（找不到时回落「公众号」）。")
        sub_literal = ""
        sub_pattern = env_config.DEFAULT_SUBFOLDER_PATTERN

    print("\n[3/3] 索引页（vault 根下的「知识库索引」）")
    ipat = existing.get("WECHAT_INDEX_PATTERN") or env_config.DEFAULT_INDEX_PATTERN
    hits = sorted(p.name for p in vault.glob(ipat))
    if hits:
        print("  匹配到：%s" % ", ".join(hits))
    else:
        print("  没匹配到 %s（不影响落库，只是不会自动登记索引）" % ipat)
    print("  直接回车沿用 %s" % ipat)
    ans = _prompt("")
    if ans:
        ipat = ans

    return {
        "WECHAT_VAULT": _norm(vault),
        "WECHAT_SUBFOLDER_PATTERN": sub_pattern,
        "WECHAT_SUBFOLDER": sub_literal,
        "WECHAT_INDEX_PATTERN": ipat,
    }


def render(cfg: dict) -> str:
    sub_literal = cfg.get("WECHAT_SUBFOLDER") or ""
    sub_literal_line = ""
    if sub_literal:
        # 写死名字时，把通配那行注释掉，避免配置里两个键互相打架
        sub_literal_line = "\n# 目录写死名字（优先级高于上面的通配）\nWECHAT_SUBFOLDER=%s" % sub_literal
    body = HEADER.format(
        when=_now(),
        vault=cfg["WECHAT_VAULT"],
        sub_pattern=cfg.get("WECHAT_SUBFOLDER_PATTERN") or env_config.DEFAULT_SUBFOLDER_PATTERN,
        sub_literal=sub_literal_line,
        index_pattern=cfg.get("WECHAT_INDEX_PATTERN") or env_config.DEFAULT_INDEX_PATTERN,
        python=sys.executable,
    )
    return body


def write_env(target: Path, cfg: dict, force=False, dry_run=False) -> int:
    if target.exists() and not force:
        print("已存在：%s" % target)
        print("不覆盖（避免冲掉你手写的其他项）。确实要重写请加 --force。")
        return 1
    text = render(cfg)
    if dry_run:
        print("--- 将要写入 %s ---" % target)
        print(text)
        return 0
    target.write_text(text, encoding="utf-8", newline="\n")
    if os.name != "nt":
        try:
            os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass
    print("已写入：%s" % target)
    print("（该文件已在 .gitignore 中，不会被提交）")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="生成 .env（本机配置）；不传参数则进入交互向导")
    ap.add_argument("--vault", help="vault 根目录（含 .obsidian 的目录）")
    ap.add_argument("--subfolder", help="落库一级目录名（写死名字）")
    ap.add_argument("--subfolder-pattern", help="落库一级目录通配，默认 *公众号")
    ap.add_argument("--index-pattern", help="索引页文件名通配，默认 *知识库索引*.md")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的 .env")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要写入的内容")
    ap.add_argument("--check", action="store_true", help="只体检当前配置，不写盘")
    a = ap.parse_args()

    if a.check:
        raise SystemExit(env_config.doctor())

    target = env_config.env_file_path()
    existing = {}
    if target.is_file():
        existing = env_config.parse_env_text(target.read_text(encoding="utf-8-sig"))

    if a.vault:
        # 非交互：值全部来自命令行
        vault = Path(os.path.expanduser(a.vault))
        if not vault.is_dir():
            raise SystemExit("vault 目录不存在：%s" % vault)
        if not (vault / ".obsidian").is_dir():
            print("WARN: %s 下没有 .obsidian，确认这是 vault 根？" % vault, file=sys.stderr)
        cfg = {
            "WECHAT_VAULT": _norm(vault),
            "WECHAT_SUBFOLDER": a.subfolder or "",
            "WECHAT_SUBFOLDER_PATTERN": a.subfolder_pattern
            or existing.get("WECHAT_SUBFOLDER_PATTERN")
            or env_config.DEFAULT_SUBFOLDER_PATTERN,
            "WECHAT_INDEX_PATTERN": a.index_pattern
            or existing.get("WECHAT_INDEX_PATTERN")
            or env_config.DEFAULT_INDEX_PATTERN,
        }
    else:
        interactive = sys.stdin is not None and sys.stdin.isatty()
        if not interactive:
            raise SystemExit(
                "非交互环境缺少参数。请用 --vault 指定，或加 --check 只体检。\n"
                "示例：python scripts/setup_env.py --vault \"D:/MyVault\"")
        cfg = interactive_wizard(existing)

    code = write_env(target, cfg, force=a.force, dry_run=a.dry_run)
    if code == 0 and not a.dry_run:
        print()
        env_config.load_env(path=target, override=True)
        print("--- 体检 ---")
        env_config.doctor()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
