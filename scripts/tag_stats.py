# -*- coding: utf-8 -*-
"""重算《知识库索引》「一、标签体系」里的覆盖计数。

**索引里的每个数字都由库推导，没有一处是手写的。** 这是索引，不是笔记：
读者会拿它当「库里到底有什么、各有多少篇」的唯一入口，数字错一位就是错的。

设计原则（与 update_index.py 的「不覆盖人工内容」一致）：

  * **只改数字与条目**。标签名、行顺序、判定标准、说明性文字一律原样保留。
    覆盖计数是「事实」，必须自动算；判定标准是「判断」，只能人写。
  * **不漏项**。库里存在、表里没有的二级标签会追加；一级标签（`主题/XX`）
    整行缺失时也会追加整行 —— 否则那部分笔记永远不会被计入任何数字，
    索引看起来完整，实际少算了。
  * **不猜**。表里的写法若在库里对应多个标签（同名不同路径），直接报错要求
    写成完整路径，绝不静默取 0 或随便挑一个。
  * **0 篇不列**。索引列的是「库里有什么」，数到 0 的二级项已被移除，
    留在表里只会误导。要保留定义时用 `--keep-zero`。
  * **幂等**。跑第二遍不会有任何改动。

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
# 一级标签被笔记直接使用（没有二级）时，格子里写的片段
DIRECT_RE = re.compile(r"^一级直挂（(\d+)\s*篇）$")


class AmbiguousTag(Exception):
    """表里的写法在库里对应多个标签，无法精准归属。"""


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


def resolve(counter, label, prefix):
    """把表里显示的名字映射成库里的完整标签键。

    返回 (完整标签键, 歧义候选列表)。键为 None 且候选为空 = 库里没有这一项。

    表里有三种写法：
      * 短名          `智能体`      → `主题/AI/智能体`（补当前行的一级前缀）
      * 半截路径      `行业/银行`   → `主题/行业/银行`（前缀 `主题/` 被省掉了）
      * 完整路径      `主题/AI/RAG` → 原样

    按「越具体越优先」的顺序试，一旦命中就不再看后面的规则；只有当精确规则
    全部落空时，才用「全库末段同名」兜底，且**必须唯一** —— `主题/AI/自动化`
    与 `主题/运维/自动化` 同时存在时抛 AmbiguousTag，绝不随便挑一个。
    """
    label = label.strip().strip("`")
    cands = []

    def _add(key):
        if key in counter and key not in cands:
            cands.append(key)

    _add(label)                              # 完整路径
    _add("主题/" + label)                    # 省掉 `主题/` 的半截路径
    if prefix:
        _add("%s/%s" % (prefix, label))      # 短名 + 当前行的一级前缀
    if len(cands) == 1:
        return cands[0], []
    if len(cands) > 1:
        return None, cands

    same = sorted(k for k in counter if k.split("/")[-1] == label)
    if len(same) == 1:
        return same[0], []
    return None, same


def _lookup(counter, label, prefix):
    """只要数字的便捷包装；歧义时抛错，数不到时返回 0。"""
    key, cands = resolve(counter, label, prefix)
    if cands:
        raise AmbiguousTag("%s 在库里对应多个标签：%s" % (label, "、".join(cands)))
    return counter[key] if key else 0


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
def _l1_groups(counter):
    """把 `主题/...` 的键归到一级：`主题/AI/智能体` → 一级 `主题/AI`、叶 `智能体`。

    `主题/管理` 这种「一级被笔记直接使用」的，记进 direct，不算叶。
    """
    groups = {}
    for key, n in counter.items():
        if not key.startswith("主题/"):
            continue
        seg = key.split("/")
        l1 = "/".join(seg[:2])
        info = groups.setdefault(l1, {"direct": 0, "leaves": {}})
        if len(seg) == 2:
            info["direct"] += n
        else:
            info["leaves"]["/".join(seg[2:])] = n
    return groups


def _update_theme_table(table, counter, keep_zero, changes):
    head, sep, body = table[0], table[1], table[2:]
    new_body = []
    seen_l1 = set()

    for row in body:
        cells = _split_row(row)
        if len(cells) < 2:
            new_body.append(row)
            continue
        prefix = cells[0].strip().strip("`")
        with_prefix = prefix.startswith("主题/")
        if with_prefix:
            seen_l1.add(prefix)

        items = [x.strip() for x in cells[1].split(" · ") if x.strip()]
        parsed, raw, has_direct = [], [], False
        for it in items:
            if DIRECT_RE.match(it):
                has_direct = True
                parsed.append("__direct__")
                raw.append(it)
                continue
            m = ITEM_NUM_RE.match(it)
            parsed.append(m.group("label") if m else None)
            raw.append(it)

        # 解析不出「名字 + 数字」的格子是说明文字（如 `主题/政治` 那行）：
        # 只替换其中唯一的「（N 篇）」，其余文字一律不动。
        if not items or any(p is None for p in parsed):
            if with_prefix:
                m = POLIT_RE.search(cells[1])
                if m:
                    n = counter.get(prefix, 0)
                    if n == 0:
                        changes.append("%s：库里已数不到该一级标签，整行删除" % prefix)
                        continue
                    if int(m.group(1)) != n:
                        cells[1] = POLIT_RE.sub("（%d 篇）" % n, cells[1], count=1)
                        changes.append("%s 一级直挂：%s → %d 篇" % (prefix, m.group(1), n))
                        new_body.append(_join_row(cells, [0] * len(cells)))
                        continue
            new_body.append(row)
            continue

        pairs, seen, direct_n = [], set(), None
        for label, it in zip(parsed, raw):
            if label == "__direct__":
                direct_n = counter.get(prefix, 0)
                continue
            name = label.strip().strip("`")
            n = _lookup(counter, name, prefix if with_prefix else None)
            seen.add(name)
            if n == 0 and not keep_zero:
                changes.append("%s：库里已无笔记，删除该项" % name)
                continue
            old_num = it.rsplit(" ", 1)[-1]
            if old_num != str(n):
                changes.append("%s：%s → %d" % (name, old_num, n))
                if n == 0:
                    changes.append("  ↑ 库里已数不到 %s，请确认是笔记被移走还是改名" % name)
            pairs.append((label, n))

        if with_prefix:
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

        # 稳定排序：同篇数的项保持表里原有的先后（人工编排的顺序不要被搅动）
        parts = ["%s %d" % (lb, n) for lb, n in sorted(pairs, key=lambda x: -x[1])]
        if direct_n is not None:
            parts.append("一级直挂（%d 篇）" % direct_n)

        if not parts:
            changes.append("%s：库里已数不到任何笔记，整行删除" % prefix)
            continue

        cells[1] = " · ".join(parts)
        new_body.append(_join_row(cells, [0] * len(cells)))

    # 库里有、表里整行缺失的一级标签：补上整行。
    # 少了这一行，该一级下的笔记就不会出现在任何数字里，索引会「看起来完整但少算」。
    groups = _l1_groups(counter)
    missing = [k for k in groups if k not in seen_l1]
    total_of = lambda k: sum(groups[k]["leaves"].values()) + groups[k]["direct"]
    for l1 in sorted(missing, key=lambda k: (-total_of(k), k)):
        info = groups[l1]
        leaves = sorted(info["leaves"].items(), key=lambda x: (-x[1], x[0]))
        cell = " · ".join("%s %d" % (k, v) for k, v in leaves)
        if not cell:
            cell = "一级直挂（%d 篇）——暂无二级" % info["direct"]
        elif info["direct"]:
            cell += " · 一级直挂（%d 篇）" % info["direct"]
        new_body.append(_join_row(["`%s`" % l1, cell], [0, 0]))
        changes.append("%s：表里没有这个一级标签，已追加整行（%d 篇）" % (l1, total_of(l1)))

    return repad([head, sep] + new_body)


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
def refresh(index_path, vault, apply=False, keep_zero=False, quiet=False):
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
            new = (_update_theme_table(table, counter, keep_zero, changes)
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
    ap.add_argument("--keep-zero", action="store_true",
                    help="保留库里已数不到的二级项并置 0（默认删除，索引只列真实存在的）")
    a = ap.parse_args()

    import env_config
    import update_index

    vault = a.vault or env_config.resolve_vault()
    index_path = a.index or update_index.find_index(vault)
    try:
        n = refresh(index_path, vault, apply=a.apply, keep_zero=a.keep_zero)
    except AmbiguousTag as exc:
        print("索引里有写法无法精准归属，已中止（未写入）：%s" % exc, file=sys.stderr)
        print("请在索引里写成完整路径（如 `主题/AI/自动化`）后重跑。", file=sys.stderr)
        return 2
    if not a.apply and n:
        print("\n[干跑] 未写入。确认后加 --apply。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
