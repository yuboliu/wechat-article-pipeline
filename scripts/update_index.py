#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""update_index.py — 把一篇笔记登记进《【91】知识库索引.md》的主题导航

它在做什么
----------
索引页「二、按主题导航」是手工维护的树：`### AI` / `### 网络` 这样的段落，
段内再用 `**DNS**` 这样的粗体小组细分。本脚本按笔记的三层标签，找到该落的
段落与小组，插一行：

    - [[笔记标题|显示名]] — 一句话价值点

并保证**幂等**：同一篇再跑一次是「更新那一行」而不是「再插一行」。

落位规则
--------
1. 段落：按笔记 `主题/` 标签的**先后顺序**，取第一个「一级大类在
   `index_layout.json` 的 sections 里、且不在 secondary_themes 里」的标签定段落。
   （`主题/行业/银行`、`主题/架构/高可用` 不参与定位 —— 「银行」既能是网络也能是
   金融，按它定位会把文章塞进无关段落。）
2. 小组：在该段落的 subgroups 里，找第一个命中笔记二级标签的小组。
3. 都不命中：段末新建 `**<二级标签末段>**` 小组；连段落都没有：落到
   `fallback_section`（默认「其他」，没有就新建）。

摘要（`— 后面的那句话`）
------------------------
正常情况下由 agent 读完全文后通过 `--summary` 传入（质量最好）。不传时退回
「取正文第一个有实质内容的句子」，只是占位，别指望它能当导读。

用法
----
    python update_index.py --vault "<vault 根>" --title "<笔记标题>" \
        --tags 主题/网络/DNS 类型/技术教程 来源/微信公众号 --summary "…" [--dry-run]

    # 也可直接吃转换产物：自动从 frontmatter 读 tags、从 H1 读标题
    python update_index.py --vault "<vault>" --from-md "<笔记.obsidian.md>"

    # 手动指定落位（覆盖自动判断）
    ... --section 网络 --subgroup DNS

退出码：0 成功／已是幂等状态；2 失败（找不到索引文件、段落歧义等）。

⚠️ 本脚本**只改「二、按主题导航」**。上方「一、标签体系」表的计数与新增二级标签
   仍由人工维护 —— 新增标签时脚本会打印提醒，但不会擅自重写那些表格。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import env_config  # noqa: E402

DEFAULT_LAYOUT = env_config.resolve_index_layout()

NAV_HEADING = "## 二、按主题导航"
ITEM_RE = re.compile(r"^\s*-\s+\[\[([^\]|]+)(?:\|([^\]]*))?\]\]\s*(?:—|--|-)?\s*(.*)$")
BOLD_GROUP_RE = re.compile(r"^\*\*(.+?)\*\*\s*$")


# --------------------------------------------------------------------------
# 定位索引文件
# --------------------------------------------------------------------------
def find_index(vault, pattern=None):
    """在 vault 根找索引页。目录名/文件名会随整理变化，所以用通配而非写死。

    通配模式来自 env_config（.env 的 WECHAT_INDEX_PATTERN），改索引名不用动代码。
    """
    vault = Path(vault)
    if not vault.is_dir():
        raise SystemExit("vault 不存在：%s" % vault)
    pat = env_config.resolve_index_pattern(pattern)
    hits = sorted(vault.glob(pat))
    if not hits:
        # 退一步：递归找一层
        hits = sorted(vault.glob("*/" + pat))
    if not hits:
        raise SystemExit("在 %s 下找不到匹配 %s 的索引文件；用 --index 显式指定" % (vault, pat))
    if len(hits) > 1:
        raise SystemExit("匹配到多个索引文件，请用 --index 指定其一：\n  " +
                         "\n  ".join(str(h) for h in hits))
    return hits[0]


# --------------------------------------------------------------------------
# 解析索引结构
# --------------------------------------------------------------------------
def split_sections(lines, nav_heading=NAV_HEADING):
    """返回 (nav_start, nav_end, [(heading, start, end)] 针对 ### 段落)。"""
    nav_start = None
    for i, ln in enumerate(lines):
        if ln.strip() == nav_heading.strip():
            nav_start = i
            break
    if nav_start is None:
        return None, None, []

    # nav 区结束于下一个同级或更高级标题（## 开头且不是 ###）
    nav_end = len(lines)
    for i in range(nav_start + 1, len(lines)):
        s = lines[i].strip()
        if re.match(r"^##\s+", s) and not s.startswith("###"):
            nav_end = i
            break

    secs = []
    cur = None
    for i in range(nav_start + 1, nav_end):
        s = lines[i].strip()
        m = re.match(r"^###\s+(.+)$", s)
        if m:
            if cur:
                secs.append((cur[0], cur[1], i))
            cur = (m.group(1).strip(), i)
    if cur:
        secs.append((cur[0], cur[1], nav_end))
    return nav_start, nav_end, secs


def find_heading_line(lines, section, secs):
    for name, start, end in secs:
        if name == section:
            return start, end
    return None, None


def bold_groups(lines, start, end):
    """段落内的 `**小组**` 位置。"""
    out = []
    for i in range(start + 1, end):
        m = BOLD_GROUP_RE.match(lines[i].strip())
        if m:
            out.append((m.group(1).strip(), i))
    return out


RULE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")


def insert_pos(lines, sec_start, sec_end, group_line):
    """确定插入行号：小组内最后一条非空行之后；没有小组则段落末尾。

    两条边界要当心：
      * 段落末尾常有 `---` 分隔线和多余空行，插到分隔线**之后**会把条目
        写到 `## 三、索引维护` 上面去 —— 这里把分隔线当作硬边界。
    """
    if group_line is None:
        j = sec_end - 1
        while j > sec_start and not lines[j].strip():
            j -= 1
        # 遇到水平分隔线 → 插在分隔线之前
        if j > sec_start and RULE_RE.match(lines[j]):
            j -= 1
            while j > sec_start and not lines[j].strip():
                j -= 1
        return j + 1

    # 小组的结束边界：下一个 `**bold**` 或段落结束
    gs = bold_groups(lines, sec_start, sec_end)
    boundary = sec_end
    for name, ln in gs:
        if ln > group_line:
            boundary = ln
            break
    j = boundary - 1
    while j > group_line and not lines[j].strip():
        j -= 1
    if j > group_line and RULE_RE.match(lines[j]):
        j -= 1
        while j > group_line and not lines[j].strip():
            j -= 1
    return j + 1


# --------------------------------------------------------------------------
# 落位决策
# --------------------------------------------------------------------------
def decide_position(layout, tags, section=None, subgroup=None):
    """返回 (section, subgroup, 说明列表)。"""
    notes = []
    if section:
        return section, subgroup, ["段落由 --section 指定"]

    primary = None
    for t in tags:
        if not t.startswith("主题/"):
            continue
        if t in layout.get("secondary_themes", []):
            notes.append("%s 属补充语境标签，跳过定位" % t)
            continue
        parts = t.split("/")
        lvl1 = "/".join(parts[:2])
        for s in layout["sections"]:
            if lvl1 in s["themes"]:
                primary = s
                notes.append("按 %s 定到段落「%s」" % (t, s["heading"]))
                break
        if primary:
            break

    if not primary:
        fb = layout.get("fallback_section") or "其他"
        notes.append("没有任何主题标签能对应到已知段落，落到「%s」" % fb)
        return fb, subgroup, notes

    if subgroup:
        return primary["heading"], subgroup, notes + ["小组由 --subgroup 指定"]

    for t in tags:
        for g in primary.get("subgroups", []):
            if t in g["tags"]:
                notes.append("按 %s 落进小组「%s」" % (t, g["name"]))
                return primary["heading"], g["name"], notes

    lvl2 = None
    for t in tags:
        if t.startswith("主题/"):
            parts = t.split("/")
            if len(parts) >= 3 and "/".join(parts[:2]) in primary["themes"]:
                lvl2 = parts[2]
                break
    if lvl2:
        notes.append("段落内没有匹配小组，候选小组「%s」" % lvl2)
    else:
        notes.append("没有二级主题，直接追加到段落末尾")
    return primary["heading"], lvl2, notes


# --------------------------------------------------------------------------
# 渲染链接
# --------------------------------------------------------------------------
def wiki_link(title, display=None):
    d = (display or title).strip()
    t = title.strip().replace("|", "\\|")
    d = d.replace("|", "\\|")
    return "[[%s|%s]]" % (t, d)


def render_line(title, display, summary):
    line = "- %s" % wiki_link(title, display)
    s = (summary or "").strip()
    if s:
        line += " — " + s
    return line


def find_existing(lines, title):
    """找索引里已有的这篇（按 wikilink 目标匹配）。返回行号或 None。"""
    target = title.strip()
    for i, ln in enumerate(lines):
        m = ITEM_RE.match(ln)
        if m and m.group(1).strip() == target:
            return i
    return None


# --------------------------------------------------------------------------
# 标签体系统计（只提醒，不改表）
# --------------------------------------------------------------------------
def known_facet_tags(text):
    """取「一、标签体系」整块的原文。

    注意：表格里**一级**标签用反引号包裹（`` `主题/AI` ``），**二级**却是裸名
    （`智能体 13 · 大模型 5`）。所以不能只抓反引号 —— 那样每个二级标签都会被
    误报成「未登记」。这里返回整块文本，由调用方按「路径命中 or 末段命中」判断。
    """
    m = re.search(r"^##\s*一、标签体系(.*?)^##\s", text, re.S | re.M)
    return m.group(1) if m else ""


def unregistered_tags(text, tags):
    block = known_facet_tags(text)
    if not block:
        return []
    out = []
    for t in tags:
        if not re.match(r"^(主题|类型|来源)/", t):
            continue
        last = t.split("/")[-1]
        # 一级/二级都可能以「路径」或「末段裸名」出现，任一命中即视为已登记
        if t in block or last in block:
            continue
        out.append(t)
    return out


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def update_index(index_path, tags, title, display=None, summary=None,
                 section=None, subgroup=None, layout_path=None, dry_run=False):
    layout_path = env_config.resolve_index_layout(layout_path)
    with open(layout_path, "r", encoding="utf-8") as f:
        layout = json.load(f)

    index_path = Path(index_path)
    raw = index_path.read_text(encoding="utf-8")
    lines = raw.split("\n")

    sec, grp, notes = decide_position(layout, tags, section=section, subgroup=subgroup)
    line_new = render_line(title, display, summary)

    # 1) 已存在 → 原地更新
    idx = find_existing(lines, title)
    if idx is not None:
        old = lines[idx]
        mo = ITEM_RE.match(old)
        # 没显式给 display / summary 时，**保留库里已有人工版本**。
        # 否则重跑一次就会把手工缩写过的显示名（`[[长标题|短名]]`）和写好的
        # 一句话价值点都覆盖成默认值 —— 这是不可逆的信息损失。
        if display is None and mo and mo.group(2):
            display = mo.group(2).strip()
        if summary is None and mo and mo.group(3):
            summary = mo.group(3).strip()
        line_new = render_line(title, display, summary)
        if old.strip() == line_new.strip():
            print("索引已是最新，无需改动：%s" % index_path)
            return 0
        lines[idx] = line_new
        action = "更新已有条目（第 %d 行）" % (idx + 1)
        print("%s：\n  - 旧：%s\n  - 新：%s" % (action, old.strip(), line_new))
    else:
        nav_start, nav_end, secs = split_sections(lines)
        if nav_start is None:
            lines.extend(["", NAV_HEADING, ""])
            nav_start, nav_end, secs = split_sections(lines)

        start, end = find_heading_line(lines, sec, secs)
        if start is None:
            # 段落不存在 → 在导航区末尾新建
            insert_at = nav_end
            while insert_at > nav_start and not lines[insert_at - 1].strip():
                insert_at -= 1
            block = ["", "### %s" % sec, ""]
            if grp:
                block += ["**%s**" % grp, ""]
            block.append(line_new)
            lines[insert_at:insert_at] = block
            print("新建段落「%s」并写入条目" % sec)
        else:
            gline = None
            sec_groups = bold_groups(lines, start, end)
            if grp:
                for name, ln in sec_groups:
                    if name == grp:
                        gline = ln
                        break

            if grp and gline is None and not sec_groups:
                # 这个段落本来是平铺列表（如「安全」「运维」），不要为一个新二级
                # 单独开小组 —— 那会在图谱里造出孤岛叶节点。直接追加到段末。
                notes.append("段落「%s」为平铺列表，未新建小组，条目直接追加" % sec)
                pos = insert_pos(lines, start, end, None)
                lines.insert(pos, line_new)
                print("写入「%s」段末（平铺列表，不新建小组）" % sec)
            elif grp and gline is None:
                # 段落有分组结构，但没有这个小组 → 段末新建小组
                pos = insert_pos(lines, start, end, None)
                lines[pos:pos] = ["", "**%s**" % grp, "", line_new]
                print("在「%s」段末新建小组「%s」并写入" % (sec, grp))
            else:
                pos = insert_pos(lines, start, end, gline)
                # 紧跟粗体小组标题时补一个空行，与既有版式一致
                if pos - 1 >= 0 and BOLD_GROUP_RE.match(lines[pos - 1].strip()):
                    lines[pos:pos] = ["", line_new]
                else:
                    lines.insert(pos, line_new)
                print("写入「%s」%s" % (sec, ("／小组「%s」" % grp) if grp else ""))

    out = "\n".join(lines)
    if not out.endswith("\n"):
        out += "\n"

    if dry_run:
        print("\n--dry-run，未写盘。改动如下：")
        import difflib
        for d in difflib.unified_diff(raw.split("\n"), out.split("\n"),
                                      "before", "after", lineterm="", n=2):
            print(d)
    else:
        index_path.write_text(out, encoding="utf-8", newline="\n")
        print("INDEX:", index_path)

    for n in notes:
        print("  ·", n)
    miss = unregistered_tags(out, tags)
    if miss:
        print("  WARN: 这些标签尚未登记在「一、标签体系」表里，建议手工补一行：%s" % "、".join(miss))
    return 0


def parse_md(md_path):
    """从转换产物里读标题与 tags（避免再让调用方重复传一遍）。"""
    text = Path(md_path).read_text(encoding="utf-8")
    try:
        sys.path.insert(0, HERE)
        from tag_infer import parse_frontmatter_tags
        tags = parse_frontmatter_tags(text)
    except Exception:
        tags = []
    h = re.search(r"^#\s+(.+)$", text, re.M)
    title = h.group(1).strip() if h else ""
    return title, tags


def main():
    ap = argparse.ArgumentParser(description="把笔记登记进《知识库索引》的主题导航")
    ap.add_argument("--vault", default=None,
                    help="vault 根（含 .obsidian）；默认按 环境变量 WECHAT_VAULT > "
                         "仓库根 .env 解析，未配置时提示跑 scripts/setup_env.py")
    ap.add_argument("--index", help="索引文件路径（默认在 vault 下按 *知识库索引*.md 匹配）")
    ap.add_argument("--from-md", help="从转换产物读取标题与 tags")
    ap.add_argument("--title", help="笔记标题（= 笔记文件名/H1）")
    ap.add_argument("--tags", nargs="*", default=[], help="三层标签")
    ap.add_argument("--display", help="索引里显示的短名（默认与标题相同）")
    ap.add_argument("--summary", help="破折号后的一句话价值点")
    ap.add_argument("--section", help="强制指定段落（如 网络）")
    ap.add_argument("--subgroup", help="强制指定小组（如 DNS）")
    ap.add_argument("--layout", help="index_layout.json 路径")
    ap.add_argument("--dry-run", action="store_true", help="只打印 diff，不写盘")
    a = ap.parse_args()

    title, tags = a.title, list(a.tags)
    if a.from_md:
        t2, tags2 = parse_md(a.from_md)
        title = title or t2
        if not tags:
            tags = tags2
    if not title:
        ap.error("缺 --title（或给 --from-md 让它自己读）")
    if not tags:
        ap.error("缺 --tags（或给 --from-md）")

    index_path = a.index
    if not index_path:
        vault = env_config.resolve_vault(a.vault, required=False)
        if not vault:
            ap.error("缺 --vault，且未在 .env 里配置 WECHAT_VAULT\n"
                     "先跑：python scripts/setup_env.py")
        index_path = find_index(vault)

    sys.exit(update_index(index_path, tags, title, display=a.display, summary=a.summary,
                          section=a.section, subgroup=a.subgroup,
                          layout_path=a.layout, dry_run=a.dry_run))


if __name__ == "__main__":
    main()
