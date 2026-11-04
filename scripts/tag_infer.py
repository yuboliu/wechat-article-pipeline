#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tag_infer.py — 从文章正文推断「三层分面」标签（确定性兜底引擎）

设计定位
--------
流水线正常情况下**由 agent 读完全文人工给标签**（质量最好）；本脚本是兜底：
agent 不在场、批量补标签、或想先看一组候选再决定时用它。它不联网、不调模型，
纯关键词加权，所以结果可复现、可测试、可解释（--explain 能看到每个标签怎么来的）。

判据（对应《【91】知识库索引.md》「一、标签体系」）
    * 主题：讲什么。三级路径 `主题/<一级>/<二级>`，二级打分不够时回退到一级。
    * 类型：什么体裁。八选一，取分数最高者。
    * 来源：固定 `来源/微信公众号`，不参与打分。

打分
----
    同一标签内按「**不同**关键词命中个数」累加，避免单个高频词垄断：
        标题命中 ×6   大纲（# 标题行）×3   正文命中 ×1（最多计 8 个）
    英文关键词按词边界匹配（`AI` 不会命中 `said`），中文按子串匹配。

用法
----
    python tag_infer.py "<文章.obsidian.md>"
    python tag_infer.py "<文章.obsidian.md>" --json
    python tag_infer.py "<文章.obsidian.md>" --explain     # 打印各标签得分
    python tag_infer.py "<文章.obsidian.md>" --max-theme 3
    python tag_infer.py --self-test                        # 词表自检

退出码：0 正常；2 输入不可用（文件不存在 / 无正文）。

⚠️ 词表在 `references/taxonomy.json`。**不要在代码里写死关键词** —— 加词只改 json，
   这样索引页与推断器才不会各说各话。
"""
import argparse
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import env_config  # noqa: E402

DEFAULT_TAXONOMY = env_config.resolve_taxonomy()

# 打分权重。改动会直接影响所有历史文章的重跑结果，改前先跑 --self-test 与回归。
W_TITLE = 6.0
W_HEAD = 3.0
W_BODY = 1.0
BODY_DISTINCT_CAP = 8

# 体裁（类型）单独一套权重：标题是体裁最强的信号，正文只是佐证。
# 2026-11-04 实测：正文权重 1.0 时，「如何/为什么」这类词把 3 篇教程判成观点随笔。
TYPE_WEIGHTS = (8.0, 3.0, 0.7, 4)

# 主题一级进入结果的最低分；二级低于此分则回退到一级
THEME_MIN = 4.0
SUBTAG_MIN = 4.0
# 候选纳入比例：一级得分低于最高分的这个比例就不再写（避免凑数）
THEME_RATIO = 0.45


# --------------------------------------------------------------------------
# 词表
# --------------------------------------------------------------------------
def load_taxonomy(path=None):
    # 路径解析交给 env_config：命令行 > 环境变量 WECHAT_TAXONOMY > .env > 仓库自带那份。
    path = env_config.resolve_taxonomy(path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_ascii(s):
    try:
        s.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


_ASCII_CACHE = {}


def _ascii_pattern(kw):
    p = _ASCII_CACHE.get(kw)
    if p is None:
        p = re.compile(r"(?<![A-Za-z0-9])" + re.escape(kw) + r"(?![A-Za-z0-9])", re.IGNORECASE)
        _ASCII_CACHE[kw] = p
    return p


def count_kw(kw, text):
    """关键词在 text 里出现几次。英文按词边界且忽略大小写，中文按子串。"""
    if not kw or not text:
        return 0
    if _is_ascii(kw):
        return len(_ascii_pattern(kw).findall(text))
    return text.count(kw)


def distinct_hits(keywords, text, cap=None):
    """命中了多少个**不同**关键词（不是总次数）。"""
    n = 0
    for kw in keywords:
        if count_kw(kw, text):
            n += 1
            if cap is not None and n >= cap:
                return n
    return n


def score_entry(entry, title, heads, body, weights=None):
    """单个标签的得分。返回 (score, 命中明细) 便于 --explain。

    `kw_title` 是只在标题里计分的强判据（体裁标记词），见 taxonomy.json 的 _notes。
    """
    wt, wh, wb, cap = weights or (W_TITLE, W_HEAD, W_BODY, BODY_DISTINCT_CAP)
    kws = entry.get("kw") or []
    kws_t = entry.get("kw_title") or []

    t = distinct_hits(kws, title) + distinct_hits(kws_t, title)
    h = distinct_hits(kws, heads)
    b = distinct_hits(kws, body, cap=cap)
    score = wt * t + wh * h + wb * b
    detail = {"title": t, "head": h, "body": b}
    return score, detail


# --------------------------------------------------------------------------
# 正文化
# --------------------------------------------------------------------------
_FM_RE = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)
_FM_TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
_CALLOUT_RE = re.compile(r"^>\s*\[!info\].*(?:\n>.*)*\n?", re.MULTILINE)
_TAIL_TAGS_RE = re.compile(r"^\s*(?:#[^\s#]+)(?:\s+#[^\s#]+)+\s*$", re.MULTILINE)
_H_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def parse_frontmatter_tags(text):
    """读出 frontmatter 里的 tags 列表。

    序列缩进有两种真实形态，必须都认：
      `tags:\\n- 主题/X`     ← yaml.dump() 默认输出（流水线刚写完时）
      `tags:\\n  - 主题/X`   ← Obsidian Linter 等插件重排后（库里的存量笔记）
    同时支持行内写法 `tags: [a, b]`。

    收敛在这里，是因为 verify / sync / update_index 三处都要读同一份 frontmatter ——
    各写一份正则就会出现「一处认缩进、一处不认」的隐蔽不一致。
    """
    m = _FM_RE.match(text)
    if not m:
        return []
    fm = re.sub(r"\A---\r?\n|\r?\n---\r?\n\Z", "", m.group(0))
    if not re.search(r"^tags:", fm, re.MULTILINE):
        return []

    mt = re.search(r"^tags:[ \t]*\[(.*?)\]", fm, re.MULTILINE)
    if mt:
        return [x.strip().strip("\"'") for x in mt.group(1).split(",") if x.strip()]

    block = re.search(r"^tags:[ \t]*\n((?:[ \t]*-[^\n]*\n?)+)", fm, re.MULTILINE)
    if not block:
        return []
    return [re.sub(r"^[ \t]*-[ \t]*", "", ln).strip()
            for ln in block.group(1).splitlines() if ln.strip()]


def split_md(text):
    """返回 (title, heads_text, body_text)。

    刻意剥掉三类「自己写的标签」：frontmatter、`> [!info]` 元信息 callout、
    文末裸 `#标签 #标签` 行 —— 否则推断器会读到上一次跑出来的标签并自我强化。

    标题优先取正文 H1；没有 H1 时退回 frontmatter 的 `title:`（手写/剪藏笔记常见）。
    """
    fm_title = ""
    fm = _FM_RE.match(text)
    if fm:
        m = _FM_TITLE_RE.search(fm.group(0))
        if m:
            fm_title = m.group(1).strip().strip("\"'")

    text = _FM_RE.sub("", text, count=1)
    text = _CALLOUT_RE.sub("", text)
    text = _TAIL_TAGS_RE.sub("", text)

    title = ""
    heads = []
    body = []
    for ln in text.splitlines():
        m = _H_RE.match(ln)
        if m:
            txt = m.group(2).strip()
            if not title and len(m.group(1)) == 1:
                title = txt
                continue
            heads.append(txt)
        else:
            body.append(ln)
    return (title or fm_title), "\n".join(heads), "\n".join(body)


# --------------------------------------------------------------------------
# 推断
# --------------------------------------------------------------------------
def split_path(path):
    return path.split("/")


def infer_theme(tax, title, heads, body, max_theme=3):
    """返回 [(path, score), ...]，按得分降序。

    一级得分 = 其下所有二级得分之和（同一大类里散落的多个二级命中，说明
    「这篇确实属于这个大类」，即使没有一个二级单独够分）。
    """
    entries = tax.get("theme") or []
    scored = []
    for e in entries:
        s, d = score_entry(e, title, heads, body)
        scored.append((e["path"], s, d))

    # 按一级聚合
    buckets = {}
    for path, s, d in scored:
        parts = split_path(path)
        lvl1 = "/".join(parts[:2]) if len(parts) >= 2 else path
        b = buckets.setdefault(lvl1, {"sum": 0.0, "subs": []})
        b["sum"] += s
        b["subs"].append((path, s, d))

    ranked = sorted(buckets.items(), key=lambda kv: -kv[1]["sum"])
    if not ranked:
        return [], []
    best_sum = ranked[0][1]["sum"]
    if best_sum <= 0:
        return [], []

    out = []
    trace = []
    for lvl1, b in ranked:
        if len(out) >= max_theme:
            break
        if b["sum"] < THEME_MIN or b["sum"] < best_sum * THEME_RATIO:
            continue
        subs = sorted(b["subs"], key=lambda x: -x[1])
        top_path, top_score, top_detail = subs[0]
        if top_score >= SUBTAG_MIN and len(split_path(top_path)) >= 3:
            out.append((top_path, top_score))
            trace.append("%s ← 二级 %.1f %s" % (top_path, top_score, top_detail))
        else:
            out.append((lvl1, b["sum"]))
            reason = "二级最高仅 %.1f < %.1f" % (top_score, SUBTAG_MIN) if subs else "无二级命中"
            trace.append("%s ← 一级 %.1f（%s，回退父级）" % (lvl1, b["sum"], reason))
    return out, trace


def infer_type(tax, title, heads, body):
    """判定体裁。返回 dict: path / score / via / hit_kw。

    两级：
      1. **标题级联** —— 按 types 数组顺序，第一个 `kw_title` 命中标题的就是结果。
         顺序本身是规则（教授 → 模板 → 速查 → 个股 → 研报 → 趋势 → 实践 → 教程 → 随笔）。
      2. **正文兜底** —— 一条标题规则都没命中时，才看正文；且必须「≥3 分且
         ≥2.5 倍于第二名」，否则回落 类型/技术教程。宽松兜底会把
         「正文里到处是『落地/如何』」的文章判错。
    """
    entries = tax.get("types") or []
    if not entries:
        return {"path": None, "score": 0.0, "via": "none", "hit_kw": None}

    for e in entries:
        kws_t = e.get("kw_title") or []
        for kw in kws_t:
            if count_kw(kw, title):
                return {"path": e["path"], "score": 1.0, "via": "title", "hit_kw": kw}

    scored = []
    for e in entries:
        s, _ = score_entry(e, title, heads, body, weights=TYPE_WEIGHTS)
        scored.append((s, e["path"]))
    scored.sort(reverse=True)
    best_score, best_path = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= 3.0 and best_score >= 2.5 * max(second, 1e-9):
        return {"path": best_path, "score": best_score, "via": "body", "hit_kw": None}

    return {"path": "类型/技术教程", "score": best_score, "via": "default", "hit_kw": None}


def infer(md_text, tax=None, max_theme=3):
    """主入口：给 md 全文，返回推断结果 dict。"""
    tax = tax or load_taxonomy()
    title, heads, body = split_md(md_text)
    themes, trace = infer_theme(tax, title, heads, body, max_theme=max_theme)
    tinfo = infer_type(tax, title, heads, body)

    tags = [p for p, _ in themes]
    if tinfo["path"]:
        tags.append(tinfo["path"])
    src = tax.get("source")
    if src:
        tags.append(src)

    return {
        "title": title,
        "tags": tags,
        "theme_scores": themes,
        "type": tinfo,
        "trace": trace,
        "warnings": _warnings(themes, tinfo),
    }


def _warnings(themes, tinfo):
    w = []
    if not themes:
        w.append("没命中任何主题：词表缺关键词，或这篇不属于现有任一领域 —— 建议补 taxonomy.json")
    if tinfo.get("via") == "default":
        w.append("类型未命中标题规则，回落 类型/技术教程（历史占比最高的体裁），请人工确认")
    return w


def finalize(result):
    """把推断结果收敛成可直接落库的标签列表（保证三层齐全）。"""
    tags = list(result["tags"])
    if not any(t.startswith("类型/") for t in tags):
        tags.append("类型/技术教程")
    if not any(t.startswith("来源/") for t in tags):
        tags.append("来源/微信公众号")
    if not any(t.startswith("主题/") for t in tags):
        # 宁可没有主题，也不瞎猜一个 —— 让调用方看见并补词表
        pass
    return tags


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _self_test(tax):
    """词表自检：结构完整性 + 每个二级至少 2 个关键词 + 父子关系可解析。"""
    problems = []
    seen = set()
    for e in tax.get("theme", []):
        p = e.get("path", "")
        if not p.startswith("主题/"):
            problems.append("主题路径前缀不对：%s" % p)
        if p in seen:
            problems.append("重复路径：%s" % p)
        seen.add(p)
        if len(e.get("kw") or []) < 2:
            problems.append("关键词少于 2 个：%s" % p)
    for e in tax.get("types", []):
        p = e.get("path", "")
        if not p.startswith("类型/"):
            problems.append("类型路径前缀不对：%s" % p)
        if p in seen:
            problems.append("重复路径：%s" % p)
        seen.add(p)
    if not str(tax.get("source", "")).startswith("来源/"):
        problems.append("source 不是 来源/ 开头")
    if problems:
        print("词表自检：%d 个问题" % len(problems))
        for p in problems:
            print("  -", p)
        return 2
    print("词表自检通过：主题 %d 条、类型 %d 条、来源 %s"
          % (len(tax.get("theme", [])), len(tax.get("types", [])), tax.get("source")))
    return 0


def main():
    ap = argparse.ArgumentParser(description="从正文推断三层分面标签（确定性兜底）")
    ap.add_argument("md", nargs="?", help="文章 md 路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--explain", action="store_true", help="打印打分明细")
    ap.add_argument("--max-theme", type=int, default=3, help="最多几个主题标签（默认 3）")
    ap.add_argument("--taxonomy", help="自定义词表路径")
    ap.add_argument("--self-test", action="store_true", help="只做词表自检")
    a = ap.parse_args()

    tax = load_taxonomy(a.taxonomy)
    if a.self_test:
        sys.exit(_self_test(tax))
    if not a.md:
        ap.error("缺少 md 路径")

    if not os.path.isfile(a.md):
        print("找不到文件：%s" % a.md, file=sys.stderr)
        sys.exit(2)
    with open(a.md, "r", encoding="utf-8") as f:
        text = f.read()

    res = infer(text, tax, max_theme=a.max_theme)
    res["tags"] = finalize(res)
    if not res["title"]:
        res["warnings"].append("没找到 H1 标题：请确认这是转换后的 obsidian.md")

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    print("标题：%s" % (res["title"] or "(未识别)"))
    print("标签：%s" % " ".join(res["tags"]))
    if a.explain:
        print("\n主题打分：")
        for p, s in res["theme_scores"]:
            print("  %-28s %.1f" % (p, s))
        print("类型打分：%s %.1f" % (res["type"]["path"], res["type"]["score"]))
        print("\n判定过程：")
        for t in res["trace"]:
            print("  -", t)
    for w in res["warnings"]:
        print("  WARN:", w)
    if not res["tags"] or len(res["tags"]) < 2:
        sys.exit(2)


if __name__ == "__main__":
    main()
