# -*- coding: utf-8 -*-
"""重算《知识库索引》「一、标签体系」里的覆盖计数。

设计原则（与 update_index.py 的「不覆盖人工内容」一致）：

  * **只改数字**。标签名、顺序、判定标准、说明性文字一律原样保留。
    覆盖计数是「事实」，可以自动算；判定标准是「判断」，只能人写。
  * **不删除**。某个标签在库里暂时数不到（笔记被移走/改名），计数回落为 0
    并给出醒目提示，而不是把整项从表里抹掉 —— 抹掉是不可逆的信息损失。
    确实要清掉时用 `--prune-zero` 显式指定。
  * **幂等**。跑第二遍不会有任何改动；`--dry-run` 可先看差异。

同时同步三处「会随笔记增减而失真」的数字：
  1. 表头 `全库 **N 篇笔记**`
  2. `分布：` 那一行各目录的篇数
  3. 三个分面表里的计数

用法：
  python scripts/tag_stats.py --vault <vault>            # 干跑，只打印差异
  python scripts/tag_stats.py --vault <vault> --apply    # 落盘
"""
import argparse
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from tag_infer import parse_frontmatter_tags  # noqa: E402

SKIP_DIRS = {".obsidian", ".trash", ".git", ".smart-env"}
SEC_THEME = "### 1. 主题"
SEC_TYPE = "### 2. 类型"
SEC_SRC = "### 3. 来源"
SEC_MAINT = "### 4. 维护约定"

TOTAL_RE = re.compile(r"全库\s*\*\*(\d+)\s*篇笔记\*\*")
DIST_RE = re.compile(r"^(>\s*分布：)(.*)$")
ITEM_NUM_RE = re.compile(r"^(?P<label>.*?\S)\s+(?P<num>\d+)$")
TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|$")
POLIT_RE = re.compile(r"（(\d+)\s*篇）")


# --------------------------------------------------------------------------
# 采集
# --------------------------------------------------------------------------
def collect(vault):
    """扫全库 frontmatter，返回 (标签计数, 顶层目录计数, 总篇数, 根目录文件名)。"""
    vault = Path(vault)
    tag_counter = Counter()
    folder_counter = Counter()
    root_files = []
    total = 0
    for p in sorted(vault.rglob("*.md")):
        parts = p.relative_to(vault).parts
        # 点开头的目录一律不算（.obsidian/.trash，以及 .claudian 这类工具目录 ——
        # 它们会把「全库篇数」凭空加一，是实测踩到的）
        if any(seg in SKIP_DIRS or seg.startswith(".") for seg in parts):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        total += 1
        depth = len(parts)
        if depth == 1:
            folder_counter["根目录"] += 1
            root_files.append(p.stem)
        else:
            folder_counter[parts[0]] += 1
        for t in set(parse_frontmatter_tags(text)):
            tag_counter[t] += 1
    return tag_counter, folder_counter, total, root_files


def _lookup(counter, label, prefix):
    """把表里显示的名字映射成库里的完整标签并取数。

    表里有两套写法，都要认：
      * 主题表里写短名          `智能体`      → `主题/AI/智能体`
      * 「其他」行写半截路径    `行业/银行`   → `主题/行业/银行`（前缀被省掉了）

    所以依次尝试：完整路径 → 加一级前缀 → 加 `主题/` → 末段同名（唯一时）。
    末段同名要唯一才认，否则 `主题/AI/自动化` 与 `主题/运维/自动化` 会串。
    """
    label = label.strip().strip("`")
    if "/" in label:
        if label in counter:
            return counter[label]
        hit = counter.get("主题/" + label)
        if hit:
            return hit
    if prefix:
        hit = counter.get("%s/%s" % (prefix, label))
        if hit:
            return hit
    hit = counter.get("主题/" + label)
    if hit:
        return hit
    same = [k for k in counter if k.split("/")[-1] == label]
    if len(same) == 1:
        return counter[same[0]]
    return 0


# --------------------------------------------------------------------------
# 表格工具
# --------------------------------------------------------------------------
def _disp(s):
    """终端/编辑器里的显示宽度：CJK 与全角符号按 2 计。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _split_row(line):
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip() for c in body.split("|")]


def _join_row(cells, widths):
    out = "|"
    for c, w in zip(cells, widths):
        out += " " + c + " " * max(0, w - _disp(c)) + " |"
    return out


def _join_sep(widths):
    return "|" + "".join(" " + "-" * max(3, w) + " |" for w in widths)


def repad(table):
    """把一张（含表头与分隔行的）表格重新对齐。分隔行按新宽度重画。"""
    if not table:
        return table
    rows = [_split_row(x) for x in table]
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    sep_idx = [i for i, r in enumerate(table) if TABLE_SEP_RE.match(r.strip())]
    data = [r for i, r in enumerate(rows) if i not in sep_idx]
    widths = [max(_disp(r[j]) for r in data) for j in range(ncol)]
    out = []
    for i, r in enumerate(rows):
        out.append(_join_sep(widths) if i in sep_idx else _join_row(r, widths))
    return out


def _table_blocks(lines, start, end):
    """返回 [start, end) 区间内每张表的 (首行行号, 末行行号)，闭区间。"""
    blocks, i = [], start
    while i < end:
        if lines[i].lstrip().startswith("|"):
            j = i
            while j + 1 < end and lines[j + 1].lstrip().startswith("|"):
                j += 1
            blocks.append((i, j))
            i = j + 1
        else:
            i += 1
    return blocks


# --------------------------------------------------------------------------
# 各段重算
# --------------------------------------------------------------------------
def _update_theme_table(table, counter, prune_zero, changes):
    head, sep, body = table[0], table[1], table[2:]
    new_body = []
    for row in body:
        cells = _split_row(row)
        if len(cells) < 2:
            new_body.append(row)
            continue
        prefix = cells[0].strip().strip("`")

        items = [x.strip() for x in cells[1].split(" · ") if x.strip()]
        parsed, raw = [], []
        for it in items:
            m = ITEM_NUM_RE.match(it)
            parsed.append(m.group("label") if m else None)
            raw.append(it)

        # 解析不出「名字 + 数字」的，是说明性格子（如 `主题/政治` 那行）：
        # 只尝试替换其中唯一的「（N 篇）」，其余文字一律不动。
        if not items or any(p is None for p in parsed):
            m = POLIT_RE.search(cells[1])
            if m and cells[0].strip().startswith("`"):
                n = counter.get(prefix, 0)
                if int(m.group(1)) != n:
                    cells[1] = POLIT_RE.sub("（%d 篇）" % n, cells[1], count=1)
                    changes.append("%s 一级覆盖：%s → %d 篇" % (prefix, m.group(1), n))
                    new_body.append(_join_row(cells, [0] * len(cells)))
                    continue
            new_body.append(row)
            continue

        is_misc = not prefix.startswith("主题/")
        pairs, seen = [], set()
        for label, it in zip(parsed, raw):
            name = label.strip().strip("`")
            n = _lookup(counter, name, None if is_misc else prefix)
            seen.add(name)
            if n == 0 and prune_zero:
                changes.append("%s：库里已无笔记，删除该项" % name)
                continue
            old_num = it.rsplit(" ", 1)[-1]
            if old_num != str(n):
                changes.append("%s：%s → %d" % (name, old_num, n))
                if n == 0:
                    changes.append("  ↑ 库里已数不到 %s，请确认是笔记被移走还是改名" % name)
            pairs.append((label, n))

        if not is_misc:
            # 补上库里新出现、表里还没有的二级标签
            style = next((p for p in parsed if p.startswith("`")), None)
            for key, n in counter.items():
                if not key.startswith(prefix + "/"):
                    continue
                short = key[len(prefix) + 1:]
                if "/" in short or short in seen:
                    continue
                label = "`%s`" % short if style else short
                pairs.append((label, n))
                changes.append("%s：新增二级标签「%s」（%d 篇）" % (prefix, short, n))
                seen.add(short)

        pairs.sort(key=lambda x: -x[1])
        cells[1] = " · ".join("%s %d" % (lb, n) for lb, n in pairs)
        new_body.append(_join_row(cells, [0] * len(cells)))

    rows = [head, sep] + new_body
    return repad(rows)


def _update_type_table(table, counter, changes):
    head, sep, body = table[0], table[1], table[2:]
    seen, new_body = set(), []
    for row in body:
        cells = _split_row(row)
        if len(cells) < 2:
            new_body.append(row)
            continue
        tag = cells[0].strip().strip("`")
        n = counter.get(tag, 0)
        seen.add(tag)
        if cells[1].strip() != str(n):
            changes.append("%s：%s → %d" % (tag, cells[1].strip(), n))
            cells[1] = str(n)
        new_body.append(_join_row(cells, [0] * len(cells)))

    extra = [k for k in counter if k.startswith("类型/") and k not in seen]
    for tag in sorted(extra):
        changes.append("%s：表里没有这一项，已追加（判定标准待人工补）" % tag)
        new_body.append(_join_row([ "`%s`" % tag, str(counter[tag]), "（待补判定标准）"], [0, 0, 0]))

    return repad([head, sep] + new_body)


def _update_source_line(line, counter, changes):
    m = re.match(r"^(`?[^`]*?)`?\s+(\d+)(.*)$", line.strip())
    if not m:
        return line
    segs = [x.strip() for x in line.split(" · ")]
    out = []
    seen = set()
    for seg in segs:
        mm = ITEM_NUM_RE.match(seg)
        if not mm:
            out.append(seg)
            continue
        name = mm.group("label").strip().strip("`")
        n = counter.get(name, 0)
        seen.add(name)
        if mm.group("num") != str(n):
            changes.append("%s：%s → %d" % (name, mm.group("num"), n))
        out.append("%s %d" % (mm.group("label"), n))
    for key, n in sorted(counter.items()):
        if key.startswith("来源/") and key not in seen:
            out.append("`%s` %d" % (key, n))
            changes.append("%s：新增来源（%d 篇）" % (key, n))
    return " · ".join(out)


def _update_distribution(line, folder_counter, total, changes):
    m = DIST_RE.match(line)
    if not m:
        return line
    prefix, rest = m.group(1), m.group(2)
    segs = [x.strip() for x in rest.split(" · ") if x.strip()]
    out, seen = [], set()
    for seg in segs:
        mm = re.match(r"^(?P<label>`[^`]+`|[^ ]+)\s+(?P<num>\d+)(?P<tail>.*)$", seg)
        if not mm:
            out.append(seg)
            continue
        name = mm.group("label").strip("`")
        n = folder_counter.get(name, 0)
        seen.add(name)
        if mm.group("num") != str(n):
            changes.append("分布 %s：%s → %d" % (name, mm.group("num"), n))
        out.append("%s %d%s" % (mm.group("label"), n, mm.group("tail")))
    for name, n in folder_counter.items():
        if name not in seen:
            out.append("`%s` %d" % (name, n))
            changes.append("分布：新增目录 %s（%d 篇）" % (name, n))
    return "%s%s" % (prefix, " · ".join(out))


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------
def refresh(index_path, vault, apply=False, prune_zero=False, quiet=False):
    index_path = Path(index_path)
    vault = Path(vault)
    counter, folders, total, root_files = collect(vault)

    text = index_path.read_text(encoding="utf-8", newline="")
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(eol)

    changes = []

    # 1) 总量
    for i, ln in enumerate(lines):
        m = TOTAL_RE.search(ln)
        if m and int(m.group(1)) != total:
            changes.append("全库篇数：%s → %d" % (m.group(1), total))
            lines[i] = TOTAL_RE.sub("全库 **%d 篇笔记**" % total, ln, count=1)
            break

    # 2) 分布
    for i, ln in enumerate(lines):
        if DIST_RE.match(ln):
            new = _update_distribution(ln, folders, total, changes)
            if new != ln:
                lines[i] = new
            break

    # 3) 三个分面
    def bounds(start_pat, end_pat):
        s = next((i for i, x in enumerate(lines) if x.startswith(start_pat)), None)
        if s is None:
            return None, None
        e = next((i for i in range(s + 1, len(lines)) if lines[i].startswith(end_pat)), len(lines))
        return s, e

    for start_pat, end_pat, kind in (
        (SEC_THEME, SEC_TYPE, "theme"),
        (SEC_TYPE, SEC_SRC, "type"),
        (SEC_SRC, SEC_MAINT, "source"),
    ):
        s, e = bounds(start_pat, end_pat)
        if s is None:
            continue
        if kind == "source":
            for i in range(s, e):
                if lines[i].strip().startswith("`来源/"):
                    lines[i] = _update_source_line(lines[i], counter, changes)
                    break
            continue
        for bi, bj in _table_blocks(lines, s, e):
            table = lines[bi:bj + 1]
            if len(table) < 3:
                continue
            new = (_update_theme_table(table, counter, prune_zero, changes)
                   if kind == "theme" else _update_type_table(table, counter, changes))
            lines[bi:bj + 1] = new

    new_text = eol.join(lines)
    if not quiet:
        if changes:
            print("标签体系计数需更新 %d 处：" % len(changes))
            for c in changes:
                print("  - %s" % c)
        else:
            print("标签体系计数已是最新，无需改动。")

    if apply and new_text != text:
        index_path.write_text(new_text, encoding="utf-8", newline="")
    return len(changes)


def main():
    ap = argparse.ArgumentParser(description="重算《知识库索引》一、标签体系的覆盖计数")
    ap.add_argument("--vault", help="vault 根（含 .obsidian）；默认走 env_config 解析")
    ap.add_argument("--index", help="索引文件路径；默认按 WECHAT_INDEX_PATTERN 通配")
    ap.add_argument("--apply", action="store_true", help="写入（默认干跑）")
    ap.add_argument("--prune-zero", action="store_true",
                    help="把库里已数不到的二级标签从表里删除（默认保留并置 0）")
    a = ap.parse_args()

    import env_config
    import update_index

    vault = a.vault or env_config.resolve_vault()
    index_path = a.index or update_index.find_index(vault)
    n = refresh(index_path, vault, apply=a.apply, prune_zero=a.prune_zero)
    if not a.apply and n:
        print("\n[干跑] 未写入。确认后加 --apply。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
