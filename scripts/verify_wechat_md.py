#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_wechat_md.py — 微信文章抓取产物「抓完即校验」Tier-1 确定性检查器

用途：
    抓完微信公众号文章、转成 Obsidian 风格 Markdown 后，对产物做一遍
    纯本地、零网络、零成本的结构性体检，抓出提取环节常见的机械性缺陷。
    这些缺陷不需要对照原文就能判定，因此可以每篇必跑。

覆盖的 8 类 Tier-1 结构缺陷：
    1. CODEBLOCK 占位符残留   __CODEBLOCK_i__ / 转义形式 \\_\\_CODEBLOCK\\_i\\_\\_
    2. 重复代码块             多个独立代码块内容完全相同（最典型的“灌错内容”信号）
    3. 空 / 截断代码块        代码块体为空或过短（<=1 有效行 / 极短字符）
    4. 代码围栏不闭合         ``` 数量为奇数
    5. 标题-正文粘连          ## 标题行里混入了整段正文句子
    6. 残留远程资源           http(s) 图片、javascript:;、substackcdn 等抓取瑕疵
    7. 图片嵌入数 ≠ 文件数    ![[…/images/x]] 引用数与 images/ 目录实际文件数不符
                             （相对写法与 vault 全路径写法都认）
    8. 三层标签齐全性         frontmatter 是否 主题/ + 类型/ + 来源/ 各至少一个（WARN）

退出码：
    0 = PASS（无问题，或仅有 WARN）
    2 = FAIL（存在需人工处理的结构缺陷）

用法：
    python verify_wechat_md.py "<obsidian.md 路径>"
    python verify_wechat_md.py "<obsidian.md 路径>" --images "<images 目录>"
    python verify_wechat_md.py "<obsidian.md 路径>" --strict   # 把 WARN 也视为 FAIL

    不传 --images 时，默认取 md 同级目录下的 images/。
"""

import argparse
import os
import re
import sys


def _fm_tags(text):
    """复用 tag_infer 的 frontmatter tags 解析（同一份正则，三处共用）。"""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        from tag_infer import parse_frontmatter_tags
        return parse_frontmatter_tags(text)
    except Exception:
        # 兜底：万一 tag_infer 被删/改名，校验器自身不能因此崩掉
        m = re.match(r"\A---\r?\n(.*?)\r?\n---", text, re.DOTALL)
        if not m:
            return []
        block = re.search(r"^tags:[ \t]*\n((?:[ \t]*-[^\n]*\n?)+)", m.group(1), re.MULTILINE)
        if not block:
            return []
        return [re.sub(r"^[ \t]*-[ \t]*", "", ln).strip()
                for ln in block.group(1).splitlines() if ln.strip()]

# ---------- 终端着色（Windows 下无 tty 时自动降级为无色） ----------
_USE_COLOR = sys.stdout.isatty()
def _c(txt, code):
    return f"\033[{code}m{txt}\033[0m" if _USE_COLOR else txt
def green(s):  return _c(s, "32")
def red(s):    return _c(s, "31")
def yellow(s): return _c(s, "33")
def bold(s):   return _c(s, "1")

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
_ICON = {PASS: green("[PASS]"), WARN: yellow("[WARN]"), FAIL: red("[FAIL]")}


class Report:
    """收集每项检查的结果。"""
    def __init__(self):
        self.items = []  # (name, status, detail_lines)

    def add(self, name, status, details=None):
        self.items.append((name, status, details or []))

    @property
    def worst(self):
        if any(s == FAIL for _, s, _ in self.items):
            return FAIL
        if any(s == WARN for _, s, _ in self.items):
            return WARN
        return PASS

    def render(self, title):
        out = []
        out.append(bold(f"\n═══ 抓完即校验 · Tier-1 结构体检 ═══"))
        out.append(f"目标：{title}\n")
        for name, status, details in self.items:
            out.append(f"{_ICON[status]} {name}")
            for d in details:
                out.append(f"        {d}")
        summary = {PASS: green("整体 PASS ✅"),
                   WARN: yellow("整体 WARN ⚠  （建议人工过目）"),
                   FAIL: red("整体 FAIL ❌ （需人工修复）")}[self.worst]
        out.append("")
        out.append(bold("─" * 40))
        out.append(bold(summary))
        return "\n".join(out)


# ---------- 代码块解析 ----------
def parse_code_blocks(text):
    """
    返回 [(lang, body, start_line), ...]。
    仅识别 ``` 围栏（不处理 ~~~，微信产物用不到）。
    """
    lines = text.splitlines()
    blocks = []
    in_block = False
    lang = ""
    body = []
    start = 0
    for i, ln in enumerate(lines, 1):
        stripped = ln.lstrip()
        if stripped.startswith("```"):
            if not in_block:
                in_block = True
                lang = stripped[3:].strip()
                body = []
                start = i
            else:
                blocks.append((lang, "\n".join(body), start))
                in_block = False
        elif in_block:
            body.append(ln)
    return blocks


def count_fences(text):
    return sum(1 for ln in text.splitlines() if ln.lstrip().startswith("```"))


# ---------- 各项检查 ----------
def check_codeblock_residue(text, rep):
    # 正常形式 + markdownify backslash 转义形式
    pats = [r"_{2}CODEBLOCK_\d+_{2}", r"\\_\\_CODEBLOCK\\_\d+\\_\\_"]
    hits = []
    for ln_no, ln in enumerate(text.splitlines(), 1):
        for p in pats:
            if re.search(p, ln):
                hits.append(f"第 {ln_no} 行：{ln.strip()[:80]}")
    if hits:
        rep.add("CODEBLOCK 占位符残留", FAIL, hits)
    else:
        rep.add("CODEBLOCK 占位符残留", PASS, ["未发现占位符残留"])


def check_duplicate_blocks(blocks, rep):
    seen = {}
    for lang, body, start in blocks:
        key = body.strip()
        if len(key) < 12:      # 过短的块交给“空/截断”检查，避免误报
            continue
        seen.setdefault(key, []).append(start)
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    if dups:
        details = []
        for k, starts in dups.items():
            preview = k.splitlines()[0][:60] if k.splitlines() else k[:60]
            details.append(f"内容重复 {len(starts)} 次（起始行 {starts}）：{preview}…")
        rep.add("重复代码块", FAIL, details)
    else:
        rep.add("重复代码块", PASS, [f"共 {len(blocks)} 个代码块，无内容重复"])


def check_empty_or_truncated_blocks(blocks, rep):
    bad = []
    for lang, body, start in blocks:
        stripped = body.strip()
        eff_lines = [l for l in body.splitlines() if l.strip()]
        if stripped == "":
            bad.append(f"第 {start} 行：空代码块（lang={lang or '无'}）")
        elif len(stripped) <= 2:
            bad.append(f"第 {start} 行：疑似截断（内容仅 '{stripped}'）")
    if bad:
        rep.add("空 / 截断代码块", FAIL, bad)
    else:
        rep.add("空 / 截断代码块", PASS, ["所有代码块均有实质内容"])


def check_fence_balance(text, rep):
    n = count_fences(text)
    if n % 2 != 0:
        rep.add("代码围栏闭合", FAIL, [f"``` 数量为奇数（{n} 个），存在未闭合围栏"])
    else:
        rep.add("代码围栏闭合", PASS, [f"``` 数量为偶数（{n} 个）"])


def check_heading_concat(text, rep):
    """
    标题-正文粘连启发式：标题行去掉 '#' 前缀后，若出现【中文句末标点
    （。！？）后面还接了非空内容】，则疑似把正文句子拼进了标题。

    只认中文句末标点，刻意避开 ASCII '.'——因为文件路径（.md/.hermes）、
    版本号、英文缩写里的点会导致大量误报（Hermes profile 路径标题即为例）。

    已知误报（WARN 级，人工确认即可，**刻意不收紧**）：
    标题**本身**就含中文句末标点的合法形态会命中 —— 设问式 / 感叹式标题，
    如 `## 为什么需要 RSI？当下大模型开发的三重现实困境`、
    `# 79页RSI综述！上交联合清华…`。判据只要求「句末标点后还有内容」，
    这类真标题同样满足。偏保守是有意的：宁可误报，也不漏掉真粘连。
    """
    suspects = []
    for ln_no, ln in enumerate(text.splitlines(), 1):
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if not m:
            continue
        title = m.group(2).strip()
        m2 = re.search(r"[。！？](.+)$", title)
        if m2 and m2.group(1).strip():
            suspects.append(f"第 {ln_no} 行：{title[:70]}…")
    if suspects:
        rep.add("标题-正文粘连", WARN, suspects + ["（启发式判断，请人工确认是否需拆分）"])
    else:
        rep.add("标题-正文粘连", PASS, ["未发现标题内混入正文"])


def check_remote_residue(text, rep):
    hits = []
    # 远程图片 markdown ![](http...) 或 <img src="http...">
    for ln_no, ln in enumerate(text.splitlines(), 1):
        if re.search(r"!\[[^\]]*\]\(https?://", ln):
            hits.append(f"第 {ln_no} 行：残留远程图片 {ln.strip()[:70]}")
        if re.search(r"<img[^>]+src=[\"']https?://", ln):
            hits.append(f"第 {ln_no} 行：残留 <img> 远程链接 {ln.strip()[:70]}")
        if "javascript:;" in ln:
            hits.append(f"第 {ln_no} 行：残留 javascript:;")
        if "substackcdn" in ln or "mmbiz.qpic.cn" in ln:
            hits.append(f"第 {ln_no} 行：残留 CDN 链接 {ln.strip()[:70]}")
    if hits:
        rep.add("残留远程资源", WARN, hits + ["（图片应已本地化为 ![[images/...]]）"])
    else:
        rep.add("残留远程资源", PASS, ["无残留远程图片 / CDN / javascript 链接"])


def check_image_count(text, images_dir, rep):
    # 两种嵌入形态都要认：转换产物是 `![[images/x.png]]`，落库后会被改写成
    # `![[公众号/标题/images/x.png]]`（vault 全路径）。只认前一种会漏检后者。
    embeds = re.findall(r"!\[\[(?:[^\]]*/)?images/([^\]]+)\]\]", text)
    n_embed = len(embeds)
    if not images_dir or not os.path.isdir(images_dir):
        rep.add("图片嵌入数 vs 文件数", WARN,
                [f"嵌入引用 {n_embed} 处；未找到 images 目录（{images_dir}），跳过文件比对"])
        return
    files = [f for f in os.listdir(images_dir)
             if os.path.isfile(os.path.join(images_dir, f))
             and not f.startswith(".")]
    n_file = len(files)
    # 嵌入引用去重（同图可能被引用多次是正常的）
    uniq_embed = set(embeds)
    missing = [e for e in uniq_embed if e not in files]
    unused = [f for f in files if f not in uniq_embed]
    details = [f"嵌入引用 {n_embed} 处（去重后 {len(uniq_embed)} 张）；images/ 实际 {n_file} 个文件"]
    status = PASS
    # 只有“引用了但文件不存在”才是真缺陷 → FAIL
    if missing:
        status = FAIL
        details.append(f"引用但缺失的文件：{missing[:10]}")
    # “存在但未引用”对微信抓取是常态（二维码/头像/装饰图/分隔线），仅作提示，不改判定
    if unused:
        details.append(f"（提示）{len(unused)} 个文件未被引用，多为二维码/装饰图，通常正常：{unused[:6]}")
    rep.add("图片嵌入数 vs 文件数", status, details)


def check_tag_facets(text, rep):
    """frontmatter 的三层分面标签是否齐全（主题 / 类型 / 来源）。

    只对**已经带 frontmatter tags** 的文件生效：
      * 抓取产物没有 YAML frontmatter（元信息在引用块里），不该被这条命中；
      * 判 WARN 而非 FAIL —— 标签是「质量项」不是「结构项」，缺了也能落库，
        只是图谱少一条边，人工过目补上即可。
    """
    m = re.match(r"\A---\r?\n(.*?)\r?\n---", text, re.DOTALL)
    if not m:
        rep.add("三层标签齐全性", PASS, ["无 frontmatter（抓取产物），跳过"])
        return
    fm = m.group(1)
    if not re.search(r"^tags:", fm, re.MULTILINE):
        rep.add("三层标签齐全性", WARN, ["frontmatter 里没有 tags 字段"])
        return
    # 缩进兼容（无缩进 / 2 空格缩进 / 行内 [a, b]）统一由 tag_infer 处理，
    # 三处调用方共用同一份解析，避免「一处认缩进、一处不认」。
    tags = _fm_tags(text)
    if not tags:
        rep.add("三层标签齐全性", WARN, ["tags 为空（转换时没给 --tags，自动推断也没结果）"])
        return

    facets = {"主题": [], "类型": [], "来源": []}
    other = []
    for t in tags:
        head = t.split("/")[0]
        if head in facets:
            facets[head].append(t)
        else:
            other.append(t)

    details = ["标签 %d 个：%s" % (len(tags), " ".join(tags))]
    missing = [k for k, v in facets.items() if not v]
    if other:
        details.append("非分面标签（自由词）：%s" % " ".join(other))
    if missing:
        details.append("缺分面：%s" % "、".join(missing))
        rep.add("三层标签齐全性", WARN, details + ["（建议补齐：主题/… 类型/… 来源/…）"])
    else:
        rep.add("三层标签齐全性", PASS, details)


def main():
    ap = argparse.ArgumentParser(description="微信文章抓取产物 Tier-1 结构校验")
    ap.add_argument("md", help="obsidian.md 文件路径")
    ap.add_argument("--images", help="images 目录（默认取 md 同级 images/）")
    ap.add_argument("--strict", action="store_true", help="把 WARN 也视为失败")
    args = ap.parse_args()

    md_path = args.md
    if not os.path.isfile(md_path):
        print(red(f"找不到文件：{md_path}"))
        sys.exit(2)

    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    images_dir = args.images
    if not images_dir:
        images_dir = os.path.join(os.path.dirname(os.path.abspath(md_path)), "images")

    blocks = parse_code_blocks(text)
    rep = Report()

    check_codeblock_residue(text, rep)
    check_duplicate_blocks(blocks, rep)
    check_empty_or_truncated_blocks(blocks, rep)
    check_fence_balance(text, rep)
    check_heading_concat(text, rep)
    check_remote_residue(text, rep)
    check_image_count(text, images_dir, rep)
    check_tag_facets(text, rep)

    print(rep.render(os.path.basename(md_path)))

    worst = rep.worst
    if worst == FAIL:
        sys.exit(2)
    if worst == WARN and args.strict:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
