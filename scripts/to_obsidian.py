# -*- coding: utf-8 -*-
"""wechat_to_md 产物 -> Obsidian 风格 Markdown。

用法:
  python to_obsidian.py "<文章目录名>" --tags t1 t2 ... [--date YYYY-MM-DD] [--base DIR]

输入: <BASE>/<文章目录名>/<文章目录名>.md   (wechat-article-to-markdown 的产物)
产出: <BASE>/<文章目录名>/<文章目录名>.obsidian.md

做的事:
  1. 剥掉原 frontmatter，重建为 Obsidian 风格（created + tags 列表）
  2. 顶部加 "> [!info] 文章信息" callout（标题/作者/发布日期/来源）
  3. 图片 ![](...) -> ![[...]]，并保证独占一行
  4. 截断文末公众号推广：优先取「最后一个分隔线 '---' 之后」（find_promo_sep）；
     若全文没有结尾分隔线，从三个候选取更靠前者 —— 文末标记（find_promo_tail：
     关注引导 / 二维码 / 推荐阅读列表，需过 33% 尾巴比例闸）、正文结束标记
     （find_promo_end：`**END**`）、历史文章导航区（find_promo_nav：≥8 条连续
     mp 链接 + `**XX系列：**` 小节，篇幅可超过正文，故不走比例闸、只看结构纯净度）。
  5. 截断文首引流块（find_promo_head：白皮书连载常见的「本章节节选自《X》+
     扫码 + 添加助手 + 即可免费获取」，常夹着未本地化的远程二维码图）。
  6. 删除引流语 / 投稿 / 点赞引导等残留（含单行的「后台 + 私信/对话框/留言/回复 +
     获取/领取/下载 + 名词」引导；三条件须同时成立，见 pitfalls #39、#41）
  7. 中文引号按行成对归一化为 “ ”
  8. 章节 ### -> ##（配合 H1 标题）

抓取产物有两种形态，脚本都吃：
  A. 自带 YAML frontmatter（title/tags/date/source…）——元信息取自 frontmatter
  B. 无 frontmatter，元信息在正文开头的 `> 公众号: x / > 发布时间: y / > 原文链接: z` 引用块里
     ——由 read_quote_meta() 兜底提取，并把该引用块与正文自带的一级标题剥掉
"""
import argparse
import datetime
import os
import re
import sys

# 2026-09-23：原写死的 `~\WorkBuddy\微信公总号知识库\output` 已不存在，
# 无 --base 时会静默把 output 重建到死路径（pitfalls #18）。改为跟随当前工作目录，
# 与抓取器 wechat_article_to_markdown.py 的 DEFAULT_OUTPUT_DIR（cwd/output）保持一致。
DEFAULT_BASE = os.path.join(os.getcwd(), "output")


def read_fm(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}, text
    raw = m.group(1)
    fm = {}
    for key in ("title", "author", "date", "source", "description"):
        mm = re.search(r'^%s:\s*"?([^"\n]*)"?\s*$' % key, raw, re.MULTILINE)
        if mm:
            fm[key] = mm.group(1).strip()
    return fm, text[m.end():]


# 抓取器把元信息写成中文键，这里映射到内部字段名
QUOTE_KEYS = {
    "公众号": "author",
    "作者": "author",
    "发布时间": "date",
    "发布日期": "date",
    "原文链接": "source",
    "来源": "source",
    "摘要": "description",
}


def read_quote_meta(text):
    """形态 B 的兜底：摘掉「正文自带的一级标题 + 后面的 `> key: value` 引用块」。

    返回 (meta, h1, rest)。引用块一行都没认出来时原样返回，避免误删正文引言。
    """
    lines = text.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    h1 = ""
    if i < len(lines) and re.match(r"^#\s+", lines[i]):
        h1 = lines[i].lstrip("#").strip()
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1

    meta, j = {}, i
    while j < len(lines) and lines[j].lstrip().startswith(">"):
        m = re.match(
            r"^>\s*(?:\*\*)?([^:：*\s]+)(?:\*\*)?\s*[:：]\s*(.+?)\s*$",
            lines[j].lstrip(),
        )
        if not m or m.group(1).strip() not in QUOTE_KEYS:
            break
        meta.setdefault(QUOTE_KEYS[m.group(1).strip()], m.group(2).strip())
        j += 1

    if not meta:
        return {}, h1, "\n".join(lines) if h1 else text
    return meta, h1, "\n".join(lines[j:])


def fence_map(lines):
    """每行是否位于 ``` 代码围栏内部。"""
    flags, inside = [], False
    for ln in lines:
        if ln.lstrip().startswith("```"):
            flags.append(inside)
            inside = not inside
        else:
            flags.append(inside)
    return flags


# 「文末推广」起手标记 —— 只在 find_promo_sep() 找不到 `---` 时用（见 find_promo_tail）。
# 前缀允许 `>` 与 `#`：推广块常被包在引用块里（如 twt 社区的 `> 原题：…点击阅读原文…`）。
PROMO_TAIL_RE = re.compile(
    r"^(?:#{1,6}\s*|>\s*)*\*{0,2}\s*"
    r"(?:关注\s*[^\n]{0,20}?(?:微信公众号|公众号)"
    r"|扫描(?:下方|上方)二维码"
    r"|长按(?:识别)?二维码"
    r"|(?:近期好文|相关阅读|推荐阅读|往期回顾|精彩回顾)\s*[:：]?"
    r"|[^\n]{0,12}推荐\s*[:：]\s*$"
    r"|添加\s*[^\n]{0,20}?(?:微信|助理|技术群|小安)"
    r"|欢迎关注[^\n]{0,24}"
    r"|或到应用商店"
    r"|下载\s*[^\n]{0,12}APP"
    r"|原题[：:][^\n]*"
    r"|点击(?:阅读原文|在看)"
    # ↓ 「标记不在行首 / 标记后还有一整句」形态（2026-10-14 新增）。
    #   上面所有写法的前提都是「行首就是标记，且标记后基本到行尾」；下面这几条
    #   各带一个 ≤16 字的行内前缀，并且用 `[^\n]*` 吃掉尾巴，因此能命中
    #   `> 欢迎点击文末阅读原文，可以直接看到…` / `…，请点赞、转发或点击"♡"` 这类行。
    #   背景：twt 社区 2026 版页脚**缺了 `原题：…` 那行**（原先全靠它命中），
    #   其余行一条都对不上，整段推广（含二维码图）留在了笔记里。
    r"|[^\n]{0,16}点击[^\n]{0,12}阅读原文[^\n]*"
    r"|[^\n]{0,16}长按[^\n]{0,6}二维码[^\n]*"
    r"|[^\n]{0,16}(?:关联|相关|往期|精彩)推荐\s*[:：][^\n]*"
    r"|[^\n]{0,16}本公众号[^\n]{0,8}(?:发布|所发)内容[^\n]*"
    r"|[^\n]{0,16}(?:请|欢迎)?点赞[、，,]\s*转发[^\n]*"
    r"|(?:作者|编辑|责编|校对|排版|审核|撰文|插图)\s*[:：][^\n]{0,20}$"
    r"|end)"
    r"\s*\*{0,2}\s*$",
    re.IGNORECASE,
)
MP_ARTICLE_RE = re.compile(r"\]\(https?://mp\.weixin\.qq\.com/s\?")
PROMO_TAIL_MAX_RATIO = 0.33

# 「正文结束」硬标记：`**END**` / `END` / `完` / `全文完` / `本文完`，
# 允许后面还挂一张结尾装饰图（`**END**![](images/img_013.gif)`）——
# 正因为挂着图，PROMO_TAIL_RE 的 `\s*\*{0,2}\s*$` 收尾匹配不到，得单独认。
# 这类标记比「关注公众号」之类可靠得多（它明确宣告正文到此为止），
# 所以不走 33% 比例闸，改用更宽的 60% 闸 + 尾部要有推广特征。
PROMO_END_RE = re.compile(
    r"^\*{0,2}\s*(?:END|完|全文完|本文完)\s*\*{0,2}\s*"
    r"(?:!\[[^\]]*\]\([^)]*\)\s*)*$",
    re.IGNORECASE,
)
PROMO_END_MAX_RATIO = 0.60

# 「文末历史文章导航区」——券商研报 / 大号常把「XX系列：」+ 一长串自家历史文章链接
# 堆在正文之后，**篇幅可以超过正文本身**（实测「华创策略姚佩」那篇：正文 47 k，
# 导航区连法律声明一起 23 k，占比 33.9%，恰好把 PROMO_TAIL_RE 的 33% 比例闸顶掉）。
# 那条比例闸不能为了它放松 —— 它挡的是「白皮书开头扫码（占比 96%）把整篇腰斩」。
# 于是换一个**正交的判据**：不要求尾巴够小，而要求尾巴够纯净。
MP_LINK_RE = re.compile(r"https?://mp\.weixin\.qq\.com/s\?")
# 导航区里的小节标题（`**十五五系列：**` / `**再通胀牛市市场观点：**`）：
# ≤20 字、不含 `*`、以冒号收尾。单看它太弱（正文里「风险提示：」同形），
# 但它必须**紧邻 ≥8 条链接行**才会计入，因此不会误伤正文。
NAV_SECTION_RE = re.compile(r"^\*{0,2}[^\n*]{2,20}\s*[:：]\*{0,2}$")
PROMO_NAV_MIN_LINKS = 8

# 「文首引流块」标记 —— 位置在正文最前面（白皮书连载类文章常见），见 find_promo_head。
PROMO_HEAD_MARK_RE = re.compile(
    r"^(?:#{1,6}\s*)?\*{0,2}\s*"
    r"(?:扫描(?:下方|上方)二维码"
    r"|关注\s*[^\n]{0,20}?(?:微信公众号|公众号)"
    r"|添加\s*[^\n]{0,20}?(?:微信|助手|助理|小安|技术群|企业微信)"
    r"|(?:即可)?(?:免费)?\*{0,2}(?:获取|领取|下载|申请)\*{0,2}"
    r"[^\n]{0,24}?(?:白皮书|报告|资料|完整版|电子书|方案|指南)"
    r"|.{0,10}节选自《[^》]+》"
    r"|.{0,12}白皮书[^\n]{0,10}(?:获取|领取|下载)"
    r"|《[^》]{2,30}》)"
    r"\*{0,2}\s*[。.]?\s*$",
    re.IGNORECASE,
)
REMOTE_IMG_RE = re.compile(r"^!\[[^\]]*\]\(https?://|^<img[^>]+src=[\"']https?://")
# 水平分割线（元信息块后那条 `---` 也很常见）视为「透明行」，不阻断文首判定。
HR_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
# 块里必须出现「索取」诉求，只有一句「节选自《X》」不砍。
PROMO_HEAD_CLAIM_RE = re.compile(r"(?:获取|领取|下载|申请|加群|进群|私信|联系)")
PROMO_HEAD_MAX_RATIO = 0.25


def find_promo_head(text):
    """找「文首引流块」的**结束位置**（字符下标），找不到返回 -1。

    形态 D：正文最前面先是一段厂商引流（「本章节节选自《X 白皮书》。+ 扫描下方二维码
    + 添加助手 + 即可免费获取完整白皮书」），其后才接正文首图。其中的二维码/推广图
    抓取器**不会本地化**，留着既脏、又会在校验里报「残留远程资源」。

    判定是「从文首第一个引流行/远程图行起，一路吃空行 + 同质行」，一旦遇到正文行
    （本地图片嵌入 `![](images/…)`、标题、长文本）立刻停 —— 因此不会跨到正文里去砍。
    三道闸，缺一不可：
      1. 块起点必须在全文前 25% 以内（防正文中段的扫码块被当文首）；
      2. 块内 ≥2 个引流标记行（单个标记不算，防正文里偶然出现一行「扫描二维码」）；
      3. 块内必须有「获取/领取/下载」诉求（纯一句「节选自《X》」不砍）。

    返回截断起点，调用方取 `text[idx:]`。
    """
    lines = text.split("\n")
    flags = fence_map(lines)
    total = len(text)
    starts, offset = [], 0
    for ln in lines:
        starts.append(offset)
        offset += len(ln) + 1

    head_limit = PROMO_HEAD_MAX_RATIO * total
    i0 = None
    for i, ln in enumerate(lines):
        if starts[i] > head_limit:
            break
        if flags[i]:
            continue
        s = ln.strip()
        if not s or HR_RE.match(s):
            continue
        if PROMO_HEAD_MARK_RE.match(s) or REMOTE_IMG_RE.match(s):
            i0 = i
        # 文首第一个非空行就落在这里：是引流块就吃，是正文就放弃
        break
    if i0 is None:
        return -1

    end, marks = i0, 0
    for i in range(i0, len(lines)):
        s = lines[i].strip()
        if not s or flags[i] or HR_RE.match(s):
            continue
        if PROMO_HEAD_MARK_RE.match(s):
            marks += 1
        elif REMOTE_IMG_RE.match(s):
            pass
        else:
            break
        end = i

    block = "\n".join(lines[i0:end + 1])
    if marks < 2 or not PROMO_HEAD_CLAIM_RE.search(block):
        return -1
    return starts[end + 1]


def find_promo_tail(text):
    """找「文末关注引导 / 推荐阅读」段的起点（字符下标），找不到返回 -1。

    仅在 find_promo_sep() 没找到 `---` 分隔线时调用 —— 有些文章（如
    「F5 数字图书馆 | DNS over HTTPS (DOH)架构」）`---` 只在元信息块后出现过一次，
    文末直接接「关注公众号 + 二维码 + 推荐阅读列表」，没有结尾分隔线。

    两道闸缺一不可，因为这里的信号（一行文字）比 `---` 弱得多：
      1. 命中 PROMO_TAIL_RE 的行，**从它到文末不超过全文的 33%**。
         必要性：白皮书类文章常在**开头**放「扫描下方二维码」（本篇第 16 行的
         扫码获取白皮书，尾巴占比 96%），只认文字标记会把整篇腰斩。
      2. 尾巴里确有推广特征：≥1 个指向其它公众号文章的链接（推荐阅读列表），
         或 ≥2 个推广标记行。防的是正文里偶然出现的一行「end」。

    标记集合见 PROMO_TAIL_RE 的注释：除「关注/扫码」外，还覆盖
    「长按二维码」「资料/文章推荐：」「欢迎关注…」「下载…APP」「或到应用商店」
    「原题：」（twt 社区这类转载文的固定页脚）「点击阅读原文/在看」（pitfalls #23）、
    以及「作者：/编辑：」署名行（后面跟着作者简介 + 编辑简介 + 推荐阅读列表的
    页脚，pitfalls #27）。
    """
    lines = text.split("\n")
    flags = fence_map(lines)
    total = len(text)
    starts, offset = [], 0
    for ln in lines:
        starts.append(offset)
        offset += len(ln) + 1
    for i, ln in enumerate(lines):
        if flags[i] or not PROMO_TAIL_RE.match(ln.strip()):
            continue
        tail = text[starts[i]:]
        if len(tail) > PROMO_TAIL_MAX_RATIO * total:
            continue
        marker_hits = sum(1 for l in lines[i:] if PROMO_TAIL_RE.match(l.strip()))
        if MP_ARTICLE_RE.search(tail) or marker_hits >= 2:
            return starts[i]
    return -1


def find_promo_end(text):
    """找「正文结束」硬标记（`**END**` / `完`）的起点（字符下标），找不到返回 -1。

    比 find_promo_tail() 更早、更可靠：作者写了 END 就是正文到头了。实测
    「浅谈G行大模型上云部署方案」的 `**END**![](images/img_013.gif)` 后面跟着
    作者简介 + 编辑简介 + 往期推荐列表（占比 34%）；PROMO_TAIL_RE 因为收尾处挂着
    图片而认不出它，退到下一个标记（`**编辑：郜斌**`，占比 30%）才截，
    结果把作者署名与简介留在了笔记里。

    两道闸：
      1. 标记不能太靠前（≤ 全文 60%）—— 防正文中段的 `END`（如分段的「完」）；
      2. 尾巴里确有推广特征（同上：mp 推荐链接，或 ≥2 个推广标记行）。
    """
    lines = text.split("\n")
    flags = fence_map(lines)
    total = len(text)
    starts, offset = [], 0
    for ln in lines:
        starts.append(offset)
        offset += len(ln) + 1
    for i, ln in enumerate(lines):
        if flags[i] or not PROMO_END_RE.match(ln.strip()):
            continue
        tail = text[starts[i]:]
        if len(tail) > PROMO_END_MAX_RATIO * total:
            continue
        marker_hits = sum(1 for l in lines[i:] if PROMO_TAIL_RE.match(l.strip()))
        if MP_ARTICLE_RE.search(tail) or marker_hits >= 2:
            return starts[i]
    return -1


def _nav_link_only(s):
    """整行是否「几乎只由文章链接构成」——允许被 `**` 包住（导航列表常整行加粗）。"""
    if not MP_LINK_RE.search(s):
        return False
    residue = re.sub(r"!?\[[^\]]*\]\([^)]*\)", "", s)  # 去掉全部链接
    return len(residue.replace("*", "").strip()) <= 8


def find_promo_nav(text):
    """找「文末历史文章导航区」的起点（字符下标），找不到返回 -1。

    形态：「华创策略姚佩」这类券商/大号研报，正文末尾接一块
      `**再通胀牛市市场观点：**` + 200 来条 `[标题](mp链接)`，
      再按主题分小节（`**反内卷系列：**` / `**十五五系列：**`…），最后是
      `**法律声明**` + 「欢迎长按二维码关注」+ 二维码图。

    与 find_promo_tail() 的分工：后者靠**一行标记文字**起手，因此必须加 33% 比例闸
    （防白皮书开头的扫码块把整篇腰斩）；而导航区动辄超过全文 1/3，过不了那道闸。
    这里的判据是**结构**而不是比例 —— 从最后一条链接行向上回溯，只吃
    「空行 / 短小节标题 / 链接行」，撞到正文（长句、图片、署名）立刻停；
    整块含 ≥8 条 mp 链接才认。正文里不可能连续出现 8 行「只有链接」的行。

    返回截断起点，调用方取 `text[:idx]`。
    """
    lines = text.split("\n")
    flags = fence_map(lines)
    starts, offset = [], 0
    for ln in lines:
        starts.append(offset)
        offset += len(ln) + 1

    last = None
    for i, ln in enumerate(lines):
        if not flags[i] and _nav_link_only(ln.strip()):
            last = i
    if last is None:
        return -1

    i = last
    while i >= 0:
        s = lines[i].strip()
        if flags[i]:
            break
        if not s or NAV_SECTION_RE.match(s) or _nav_link_only(s):
            i -= 1
            continue
        break
    start = i + 1
    if len(MP_LINK_RE.findall("\n".join(lines[start:last + 1]))) < PROMO_NAV_MIN_LINKS:
        return -1
    return starts[start]


def find_promo_sep(text):
    """从后往前找「文末推广分隔线」，返回截断点（字符下标），找不到返回 -1。

    两个坑：
      1. 代码块里常有 `---`（DOT 图、表格分隔），旧版 `text.rfind("\\n---\\n")` 会
         把它当成推广分隔线，把正文从中间腰斩 —— 故跳过围栏内的 `---`。
      2. 形态 B 的抓取产物在正文最前面就有一条 `---`（元信息引用块之后的分隔线），
         它后面还跟着整篇正文 —— 真正推广尾巴不会占正文的一大半，故按「尾巴比例」过滤。
    """
    lines = text.split("\n")
    flags = fence_map(lines)
    total = len(text)
    offset = 0
    starts = []
    for ln in lines:
        starts.append(offset)
        offset += len(ln) + 1
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() != "---" or flags[i]:
            continue
        tail = total - starts[i]
        if tail <= 0.40 * total:
            return starts[i]
    return -1


# 「文首重复标题」banner 的识别（见 strip_dup_title_head）。
IMG_INLINE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
BOLD_RUNS_ALL_RE = re.compile(r"^(?:\*\*[^*\n]+\*\*)+$")


def _banner_bold(s):
    """一行若为「图片 + 独占加粗」或「纯加粗」，返回其加粗文字；否则 None。"""
    body = IMG_INLINE_RE.sub("", s).strip()
    if not body or not BOLD_RUNS_ALL_RE.match(body):
        return None
    return body.replace("**", "").strip()


# banner 尾巴上的「纯装饰强调行」：`***DeepSeek***`（粗 + 斜体）。
# ⚠️ 只认**三颗星**。微信作者用三颗星写副标题/口号，而正文小标题一律是 `**纯粗**`
# （`**引言**`）—— 放宽成两颗星会把首屏的 `**引言**` 一起删掉（实测踩过）。
DUP_TITLE_DECO_RE = re.compile(r"^\*{3}([^*\n]+)\*{3}$")


def _banner_deco(s):
    """这一行是不是 banner 里的「纯装饰强调行」（可删）。"""
    m = DUP_TITLE_DECO_RE.match(s)
    if not m:
        return False
    body = m.group(1)
    return len(body) <= 20 and not re.search(r"[。！？；：,.;:!?]", body)


def strip_dup_title_head(text, title):
    """删掉文首「重复标题」banner，返回处理后的文本。

    公众号正文最前面常放一块题图 banner，把标题文字又写一遍（还常按断行拆成两行）：

        ![](images/img_001.png)**网络原来如此之**
        **G行数据中心分布式域名解析系统设计**
        ![](images/img_002.png)![](images/img_003.png)![](images/img_004.png)

    这些加粗行会流到 `rebuild_headings()` 被当成「无编号加粗小标题」提升，
    于是大纲里冒出 `## 网络原来如此之` / `### G行…` 两个**假标题**，首屏也被顶下去。

    判据只有一条：从文首起连续若干行（空行 / `---` / 纯图片行都算 banner 的一部分）
    里的加粗文字**拼起来恰好等于 H1 标题**。只要中间出现一行正文
    （例如容器云那篇的 `**【导读】**本文…`），立刻放弃，一个字都不动。
    """
    lines = text.split("\n")
    i0 = 0
    while i0 < len(lines) and not lines[i0].strip():
        i0 += 1
    if i0 >= len(lines):
        return text

    want = re.sub(r"\s+", "", title)
    if len(want) < 4:
        return text

    collected, last, j = [], -1, i0
    while j < len(lines):
        s = lines[j].strip()
        if not s or not IMG_INLINE_RE.sub("", s).strip():
            # 空行 / 纯图片行：算 banner 的一部分。已经认出 banner 后，尾部的装饰图
            # （题图、插画、图标）也一并吃掉 —— 不然它们会孤零零留在笔记首屏。
            if collected:
                last = j
            j += 1
            continue
        if HR_RE.match(s):
            j += 1
            continue
        b = _banner_bold(s)
        if b is None:
            break           # 遇到正文，收工
        collected.append(b)
        last = j
        j += 1

    if not collected or last < 0:
        return text
    if re.sub(r"\s+", "", "".join(collected)) != want:
        return text
    # banner 尾巴上的「纯装饰」行（`***DeepSeek***` 这种粗+斜体口号）+ 空行 + 装饰图，
    # 一并吃掉。不然它会孤零零留在笔记首屏，还会被 rebuild_headings() 提成
    # `## *DeepSeek*` 这种假标题（实测「浅谈G行大模型上云部署方案」一篇）。
    k = last + 1
    while k < len(lines):
        s = lines[k].strip()
        body = IMG_INLINE_RE.sub("", s).strip()
        if not body or HR_RE.match(s) or _banner_deco(body):
            last, k = k, k + 1
            continue
        break
    return "\n".join(lines[:i0] + lines[last + 1:])


HEAD_LINE_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BOLD_ONLY_RE = re.compile(r"^\*\*(.+?)\*\*$")
# 1.2.1 / 1.2 —— 编号后必须跟分隔符（或直接接汉字），避免把「802.1Q标准」这类
# 正文当标题（它后面跟的是拉丁字母 Q）。
HEAD_DOT_RE = re.compile(
    r"^(\d+(?:\.\d+)+)(?:[\s、.．:：]\s*|(?=[\u4e00-\u9fa5]))(\S.*)$")
# `1. 小节名` —— 单数字 + 点号。
# 默认按「点号数 + 2」定为层级 3（`1. SSL 卸载` 是节）。
# 为什么要点号：「容器云」的章节写 `1 容器平台网络模型`（无点，顶级 ##），
# 「F5」的小节写 `1. SSL 卸载`（有点，###）。同一篇文章里两种写法并存时，
# 点号是唯一能区分「章 / 节」的信号。
# 限定 [1-9] 开头 + 点后必须有空格：`01.` / `1.协议栈` 这类少见写法交给原规则，
# 免得抢走「01 安全问题」这种两位编号（那是「跟着上一级」的小节，口径不同）。
# ⚠️ 但**同一套写法在别的文章里含义相反**（见 classify_head_number 的 multi_dot）：
# 「知识图谱RAG」把章写成 `1. 引言` / `2. RAG 知识库`，节写成 `2.1. 知识库概述`。
HEAD_DOT1_RE = re.compile(r"^([1-9]\d*)\.\s+(\S.*)$")
HEAD_INT_RE = re.compile(r"^(\d+)[\s、.．:：](?!\d)\s*(\S.*)$")
# 两位编号且**不带**分隔符：`01安全问题`（公众号常见的「小节」写法）
HEAD_TWO_RE = re.compile(r"^(\d{2})\s*(\D.*)$")
HEAD_MAX_LEN = 40
HEAD_STOP_PUNCT = "。！？；：,.;!?;"
HEAD_SKIP_PREFIX = ("图", "表", "注：", "注:")
# 目录块：「**目录**」下面那一大行（markdownify 把 <section> 压平的结果）
TOC_HEAD_RE = re.compile(r"^(?:#{1,6}\s*)?\*{0,2}\s*目\s*录\s*\*{0,2}\s*$")
# 目录条目的起点：编号 + 分隔符。⚠️ 必须用 finditer 定位，不能用 re.split——
# 零宽前瞻的 split 会在匹配点后跳过一个字符，于是「1.1 xxx」会被二次切成「1.」+「1 xxx」。
TOC_MARK_RE = re.compile(r"\d+(?:\.\d+)*[\s、.．]")
TOC_ITEM_RE = re.compile(r"^(\d+(?:\.\d+)*)\s*[\s、.．:：]?\s*(.*)$")


def rebuild_toc(text, notes):
    """把「**目录** + 挤成一行的目录内容」重排成按编号缩进的嵌套列表。

    微信的目录是一串并列的 `<section>`，而 markdownify 不认识 `<section>`，会把它们
    **连成同一行**、加粗标记也变成裸 `**`：
      `**1 容器平台网络模型**1.1 容器网络概述1.2 容器网络分类介绍…`
    这一行在 Obsidian 里既占满屏宽又没法读，且完全没有结构。

    判定很严（四条全中才动），因为「一行里塞满编号」也可能是正常正文：
      1. 上一行（允许隔空行）是「目录」标题；
      2. 该行长度 ≥ 100 字；
      3. 按「编号 + 分隔符」切分后 ≥ 4 段；
      4. 每一段都能解析成「编号 + 文字」，否则**整块不碰**（宁可不动，不能改错）。
    ⚠️ 已知局限：目录条目文字里若含「数字 + 空格」（如 `支持 IPv6 双栈`），会被多切一段。
    本项目已遇到的目录都没这种写法；真遇到时只是列表多一项，不会丢内容。
    """
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if not TOC_HEAD_RE.match(ln.strip()):
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines):
            continue
        cand = lines[j].replace("*", "").strip()
        if len(cand) < 100:
            continue
        marks = list(TOC_MARK_RE.finditer(cand))
        if len(marks) < 4 or marks[0].start() != 0:
            continue
        bounds = [mm.start() for mm in marks] + [len(cand)]
        parts = [cand[bounds[k]:bounds[k + 1]].strip() for k in range(len(marks))]
        items = []
        for p in parts:
            m = TOC_ITEM_RE.match(p)
            if not m or not m.group(2).strip():
                items = []
                break
            items.append((m.group(1), m.group(2).strip()))
        if not items:
            continue
        lines[j] = "\n".join(
            "%s- %s %s" % ("  " * num.count("."), num, txt) for num, txt in items
        )
        notes.append("重排目录块为 %d 条嵌套列表" % len(items))
    return "\n".join(lines)


def classify_head_number(txt, multi_dot=False):
    """按标题文本里的编号判断 (kind, 绝对层级)。kind ∈ dot/int/dot1/two/plain。

    `multi_dot=True` 表示**全文存在两级点号标题**（`1.1` / `2.3.`）。此时 `1.` 这种
    单级点号是**章**（层级 2），而不是 `###` —— 否则「`1. 引言`」会和它的子节
    「`2.1. 知识库概述`」撞在同一级，整篇大纲塌掉。
    判据由 `rebuild_headings()` 的第一遍扫描给出（见那里的 `has_multi_dot`）。
    """
    m = HEAD_DOT_RE.match(txt)
    if m:
        return "dot", min(2 + m.group(1).count("."), 6)
    m = HEAD_DOT1_RE.match(txt)
    if m:
        return "dot1", (2 if multi_dot else 3)
    m = HEAD_INT_RE.match(txt)
    if m:
        num = m.group(1)
        # `01 安全问题` 与 `01安全问题` 视作同一类（都是「小节」，跟着上一级）
        return ("two", None) if num.startswith("0") else ("int", 2)
    if HEAD_TWO_RE.match(txt):
        return "two", None
    return "plain", None


def bold_can_be_head(txt):
    """独占一行的加粗文本，够不够格当标题。防的是「加粗的强调句」。

    长度 ≤ 40 字、不含句号、结尾不是句末标点（尤其 `：` —— 「应重点考虑以下技术建议：」
    这类引导句就是被它挡下来的）、不以「图/表/注」开头（图注）。
    """
    if not txt or len(txt) > HEAD_MAX_LEN:
        return False
    if "。" in txt or txt[-1] in HEAD_STOP_PUNCT:
        return False
    return not txt.startswith(HEAD_SKIP_PREFIX)


DIGITS_ONLY_RE = re.compile(r"^\d+$")
BOLD_RUN_RE = re.compile(r"\*\*([^*\n]+)\*\*")
BOLD_RUNS_HEAD_RE = re.compile(r"^\s*((?:\*\*[^*\n]+\*\*)+)\s*(\S.*)?$")
# 「够格被拆成小节标题」的加粗前缀：两位编号（`01`，跟着上一级）或 `1.` 这种带点编号。
# 刻意**不含** `1 标题`（无点）—— 「容器云的目录行」`**1 容器平台网络模型**1.1 …`
# 正是那个形态，拆了就把目录拆坏了。
SPLIT_HEAD_RE = re.compile(r"^(?:\d{2}(?!\d)|[1-9]\d*\.\s)")
TRAIL_PUNCT_RE = re.compile(r"[。.；;]\s*$")
# 段落里的编号列表项被作者顺手加粗 → **不是标题**。两种写法：
#   ① 「编号 + 点号 + **紧跟**非空白」（`3.可视化展示`）。依据是本项目的标题一律在
#      点号后留空格（`1. SSL 卸载`，见 HEAD_DOT1）；多位编号（`1.2.1`）也不受影响
#      —— `(?!\d)` 把「点号后仍是数字」的情形放行。
#   ② 「括号编号」（`（1）朴素 RAG- Native RAG 阶段` / `(1) xxx`）。括号编号**从来不是**
#      本项目的标题编号（标题只用 `1` / `1.1` / `01` 三种），所以一律当列表项。
# 实测：① 只命中「云原生可观测」那篇的 `**3.可视化展示**`；
#       ② 只命中「知识图谱RAG」那篇 `2.2` 下面并列的三条 RAG 阶段
#       （`**（1）朴素 RAG…**` / `**（2）进阶RAG…**` / `**（3）模块化 RAG…**`），
#       它们曾被提升成 `##`，把 `2.3` 挤成了三段的「子节」。
BOLD_LIST_ITEM_RE = re.compile(r"^(?:\d+[.．](?!\d)\S|[（(]\d{1,2}[）)])")


def unwrap_bold_head(txt):
    """标题文字**整行被加粗**（`## **1. 引言**`）→ 去掉外层 `**`，其余原样返回。

    作者在 Word 里把标题文字整体加粗，粘进公众号后 HTML 是「标题标签 + 内层
    `font-weight:bold`」，markdownify 于是给出 `## **1. 引言**`。危害不止是样式：
    **加粗会让编号彻底认不出来** —— `classify_head_number()` 看到首字符是 `*` 就判
    `plain`，于是整篇的层级重建（`1.` → `##`、`2.1.` → `###`）全部失效，只能靠
    `shift_body_headings()` 平移，`## 3. 知识图谱技术`（那条恰好没加粗）就掉到了 `###`。
    拆掉后与其余笔记的标题风格也一致。
    """
    m = BOLD_ONLY_RE.match(txt)
    return m.group(1).strip() if m else txt


# 「一位数章号」判定：本文若用 `**1**` / `**1 名称**` 这类**一位数**编号当章，
# 那两位数就是「跟着上一级」的小节 —— 合并 `**NN**` + `**名称**` 时要**保留编号**并定为 `###`。
# 反之（「G行 DNS」那种 `**01**`+`**架构设计**` 直接当章）维持 `## 名称`、编号丢掉。
# 二者语法完全相同，唯一的区分信号就是「全文有没有一位数章号」。
SINGLE_CHAP_RE = re.compile(r"^\*\*\s*[1-9](?:\*\*|\s*[^\d\s])", re.MULTILINE)
# `**01**` 与下一行的 `**章节名**`（中间常夹空行）。
TWO_DIGIT_NAME_RE = re.compile(
    r"^\*\*(\d{2})\*\*[ \t]*\n(?:[ \t]*\n)*[ \t]*\*\*([^*\n]+?)\*\*[ \t]*$",
    re.MULTILINE)


def _bold_runs(s):
    return BOLD_RUN_RE.findall(s)


def _join_digit_runs(runs):
    """把被微信切开、且相邻的纯数字加粗块拼回去（`**0****1**` -> `01`）。"""
    out = []
    for r in runs:
        if DIGITS_ONLY_RE.match(r) and out and DIGITS_ONLY_RE.match(out[-1]):
            out[-1] += r
        else:
            out.append(r)
    return out


def _pair_number_title(runs):
    """整理被切开的加粗块：

      * `['策略设计', '01', '智能解析机制']` -> `['策略设计', '01 智能解析机制']`
        （章标题 + 小节编号 + 小节名，编号在**中间**）
      * `['3', '大', '模型上云成果']` -> `['3 大模型上云成果']`
        （`**3****大****模型上云成果**`：编号在**开头**，后面的碎片按顺序拼回去）
    """
    # 形态二：编号是第一个加粗块，后面全是文字碎片 → 拼成一个「编号 + 标题」
    if runs and re.match(r"^\d{1,2}$", runs[0].strip()) and len(runs) > 1 \
            and not any(DIGITS_ONLY_RE.match(r.strip()) for r in runs[1:]):
        return ["%s %s" % (runs[0].strip(),
                           "".join(r.strip() for r in runs[1:]))]
    items, i = [], 0
    while i < len(runs):
        r = runs[i].strip()
        if re.match(r"^\d{2}$", r) and i + 1 < len(runs) \
                and not DIGITS_ONLY_RE.match(runs[i + 1]):
            items.append("%s %s" % (r, runs[i + 1].strip()))
            i += 2
        else:
            items.append(r)
            i += 1
    return items


def normalize_bold_headings(text):
    """归一化「加粗小标题」被微信切碎的三种形态（pitfalls #28）。

    ⚠️ **必须跑在通用「加粗分裂合并」之前** —— 那一步会把
    `**策略设计****01****智能解析机制**` 揉成一整块，结构边界就丢了。

      1. `**0****1****动静区分**` -> `**01 动静区分**`
         （编号被切成两块，标题还被 span/strong 重复了一遍）
      2. `**策略设计****01****智能解析机制**` -> `**策略设计**` + `**01 智能解析机制**`
         （章标题和小节标题被塞进同一行，「G行」那篇的 03/04 章就是这样）
      3. `**03****域名解析时延**正文…` -> `**03 域名解析时延**` + 空行 + 正文
         （小节标题与正文挤在同一行）
      4. `**4**总结` / `**1******大模型上云技术挑战****` -> `**4 总结**`
         （章号独占一个加粗块、标题跟在块**外面**同一行；块后面的星号是微信的残留，
         一并清掉）—— 实测「浅谈G行大模型上云部署方案」的 1/4 章。

    只在「一行以加粗块开头、且块里出现编号标题」时才动手；其余行原样放行。
    章节编号（独占一行的 `**01**`）不在这里配对，交给 convert() 里的
    「`**01**` + 章节名」合并规则。
    """
    lines = text.split("\n")
    flags = fence_map(lines)
    out, changed = [], False
    for i, ln in enumerate(lines):
        if flags[i]:
            out.append(ln)
            continue
        m = BOLD_RUNS_HEAD_RE.match(ln)
        if not m:
            out.append(ln)
            continue
        runs = _join_digit_runs(_bold_runs(m.group(1)))
        items = [x for x in _pair_number_title(runs) if x]
        rest = (m.group(2) or "").strip()
        if rest:
            # 形态 4：章号独占加粗块，标题跟在**块外**同一行（`**4**总结`）。
            # 块后面的 `*` 是微信挤压出来的残留（`**1******大模型…****`），先剥掉。
            if len(items) == 1 and DIGITS_ONLY_RE.match(items[0]) \
                    and len(items[0]) <= 2:
                clean = rest.strip("* \t")
                if clean and bold_can_be_head(clean):
                    out.append("**%s %s**" % (items[0], clean))
                    changed = True
                    continue
            # 形态 3：小节标题与正文挤在同一行（正文常从标题那句的下一句开始）
            head_txt = TRAIL_PUNCT_RE.sub("", items[0]).strip() if len(items) == 1 else ""
            if not head_txt or not SPLIT_HEAD_RE.match(head_txt) \
                    or not bold_can_be_head(head_txt) or len(rest) < 12:
                out.append(ln)
                continue
            out.extend(["**%s**" % head_txt, "", rest])
            changed = True
            continue
        if not any(re.match(r"^\d{1,2}$", r) for r in runs):
            out.append(ln)
            continue
        if len(items) == 1:
            new = "**%s**" % items[0]
            if new != ln:
                changed = True
            out.append(new)
            continue
        out.append("")
        for x in items:
            out.extend(["**%s**" % x, ""])
        changed = True
    if not changed:
        return text, []
    return "\n".join(out), ["归一化加粗小标题（编号/标题配对）"]


def merge_numbered_names(text):
    """把「独占一行的编号 + 下一行的加粗名字」合并成一条标题。

    ⚠️ 同一套语法在两种文章里含义相反，靠「全文有没有一位数章号」区分
    （`SINGLE_CHAP_RE`，见其注释）：

      * `**1**` + `**大模型上云部署方案**` → 章 → `## 1 大模型上云部署方案`
      * 有章号时，`**03**` + `**AI算力硬件感知调度…**` → 节 → `### 03 AI算力…`（**保留**编号）
      * 没章号时，`**01**` + `**架构设计**`（「G行 DNS」）→ 章 → `## 架构设计`（丢掉编号）

    编号行与名字行之间常夹空行，都要吃。
    """
    notes = []
    single_chap = bool(SINGLE_CHAP_RE.search(text))
    merged = re.sub(
        r"^\*\*([1-9])\*\*[ \t]*\n(?:[ \t]*\n)*[ \t]*\*\*([^*\n]+?)\*\*[ \t]*$",
        lambda m: "## %s %s" % (m.group(1), m.group(2)), text, flags=re.MULTILINE)
    if merged != text:
        notes.append("合并『**1**+章节名』为二级标题")
        text = merged
    merged = TWO_DIGIT_NAME_RE.sub(
        (lambda m: "### %s %s" % (m.group(1), m.group(2))) if single_chap
        else (lambda m: "## %s" % m.group(2)), text)
    if merged != text:
        notes.append("合并『**01**+章节名』为%s标题" % ("三级" if single_chap else "二级"))
        text = merged
    return text, notes


# 假标题的判据：空标题、markdownify 对「标题里裹图片」的产物（`### 图片`）、
# 超过 40 字的、含句号的、以句末标点收尾的 —— 真标题几乎不可能满足其中任何一条。
FAKE_HEAD_TAIL_PUNCT = "。！？；："


def head_looks_like_paragraph(txt):
    """这一行「标题」看起来其实是正文段落（作者把段落误用了 `<hN>` 标签）。"""
    if not txt or txt == "图片":
        return True
    if len(txt) > HEAD_MAX_LEN or "。" in txt:
        return True
    return txt[-1] in FAKE_HEAD_TAIL_PUNCT


def demote_fake_headings(text, notes):
    """把「其实是段落」的 `<hN>` 标题降回普通段落（pitfalls #35）。

    有的作者在 Word / 网页里把摘要、导语也套上了标题样式，粘进公众号后 HTML 里就是
    货真价实的 `<h3>`，markdownify 照实输出 —— 于是「本文从…」这种摘要变成假标题，
    还会连带影响 `fold_empty_heads()` 的作用域（它只看「标题间有没有正文行」）。
    判据见 `head_looks_like_paragraph()`；只动正文标题（`##` 及更深），不碰 H1 标题行。
    """
    lines = text.split("\n")
    flags = fence_map(lines)
    out, hit = [], 0
    for i, ln in enumerate(lines):
        m = None if flags[i] else HEAD_LINE_RE.match(ln)
        if m and len(m.group(1)) >= 2 and head_looks_like_paragraph(m.group(2).strip()):
            out.append(m.group(2).strip())
            hit += 1
        else:
            out.append(ln)
    if hit:
        notes.append("降级假标题（段落被误用标题标签）%d 处" % hit)
    return "\n".join(out)


def shift_body_headings(text, title, notes):
    """把正文标题的**最浅层级**归一到 `##`（pitfalls #30、#35）。

    公众号正文的标题层级有三种来源，深浅各不相同：
      * 抓取器把「字号样式块」提升的 `<h2>` → `##`（本项目的主口径）；
      * 作者把 Word / 文档的 `<h1>`/`<h2>` 直接粘进正文 → `#`/`##`：正文章节与文章标题
        同级（`# 一、引言`），小节 `## 2.1 …` 反而比它深一级，大纲塌掉；
      * 作者粘的是 `<h3>`/`<h4>`（`一、还是从网站开始` / `2.1、服务发现`）→ `###`/`####`：
        整篇比约定深一级。

    统一判据：**正文里最浅的标题必须是 `##`**（`#` 只留给文章标题，`##` 是顶层章）。
    算出 `shift = 2 - 最浅层级`，把正文所有标题平移这么多级（结果夹在 2~6）。

    只统计正文标题：脚本自己的标题 H1 已被 `read_quote_meta` 摘掉，文末推广里的 `#`
    链接也已随截断去掉，与文章标题**同名**的 H1 行按「重复标题 banner」丢弃且**不计入**
    （否则一篇正常文章会因为文首复读了一遍标题而被整体误移一级）。

    **编号标题不受影响** —— 它们的绝对层级随后由 `rebuild_headings()` 按编号重算
    （`2.1` 照旧是 `###`）；真正靠这一步纠正的是**无编号**标题
    （章节 `一、`… → `##`，小节 `实践一：…` → `###`）。
    """
    lines = text.split("\n")
    flags = fence_map(lines)
    want = re.sub(r"\s+", "", title or "")
    dup_h1, levels = set(), []
    for i, ln in enumerate(lines):
        if flags[i]:
            continue
        m = HEAD_LINE_RE.match(ln)
        if not m:
            continue
        if len(m.group(1)) == 1 and want \
                and re.sub(r"\s+", "", m.group(2).strip()) == want:
            dup_h1.add(i)          # 正文里复读了一遍标题 —— 归 banner，不算证据
            continue
        levels.append(len(m.group(1)))
    if not levels and not dup_h1:
        return text

    shift = (2 - min(levels)) if levels else 0
    out, moved, dropped = [], False, False
    for i, ln in enumerate(lines):
        if i in dup_h1:
            dropped = True
            continue
        m = None if flags[i] else HEAD_LINE_RE.match(ln)
        new = ln
        if m and shift:
            new = "%s %s" % ("#" * max(2, min(6, len(m.group(1)) + shift)), m.group(2))
            if new != ln:
                moved = True
        out.append(new)
    if moved:
        notes.append("正文标题层级整体%s %d 级（Word 粘贴型标题）"
                     % ("下移" if shift > 0 else "上移", abs(shift)))
    if dropped:
        notes.append("删除正文里重复的文章标题行")
    return "\n".join(out)


def rebuild_headings(text):
    """按标题里的**编号**重建多级层级，并把够格的加粗行提成标题（pitfalls #24）。

    微信小标题经抓取后有三种形态，这里统一处理：
      * 已是 `##`/`###`（抓取器的字号规则提升的）—— 重新按编号定级；
      * 独占一行的加粗（`**1.1 容器网络概述**`、`**需求分析**`）—— 提升为标题；
      * 其它 —— 原样保留。

    定级规则：
      `1` → `##`、`1.1` → `###`、`1.2.1` → `####`（点号层数 + 2，封顶 6）；
      `01安全问题` 这类两位编号、以及 `Underlay网络` 这类无编号加粗行，按「上一级 + 1」
      挂到当前数字小节下；回到顶层（`## 总结` 这类无编号的原生标题）则归 2。
    `1.` 这种单级点号的归属**取决于全文有没有两级点号**（见 `has_multi_dot`）：
      * 「F5」：没有 `1.1` ⇒ `1.` 是「跟着无编号大章」的**节** → `###`；
      * 「知识图谱RAG」：有 `2.1.` ⇒ `1.` 就是**章** → `##`。
    标题行**整行被加粗**（`## **1. 引言**`）的先拆掉 `**` 再判编号 —— 否则编号认不出来。
    代码围栏内、以及 H1 标题行不动。
    """
    lines = text.split("\n")
    flags = fence_map(lines)

    # 第一遍：全文有没有「两级点号」标题（`1.1` / `2.3.`）？
    # 只扫「可能当标题的行」（`#` 标题行 + 独占一行的加粗行），避免正文里的
    # `802.1Q标准` 这类数字被误当成标题编号。
    has_multi_dot = False
    for i, ln in enumerate(lines):
        if flags[i]:
            continue
        m = HEAD_LINE_RE.match(ln)
        if m:
            t = m.group(2).strip()
        else:
            b = BOLD_ONLY_RE.match(ln)
            if not b:
                continue
            t = b.group(1).strip()
        if classify_head_number(unwrap_bold_head(t))[0] == "dot":
            has_multi_dot = True
            break

    out, notes = [], []
    last, last_kind, num_depth, changed = 0, None, 0, False

    for i, ln in enumerate(lines):
        head = bold = None
        if not flags[i]:
            m = HEAD_LINE_RE.match(ln)
            if m and len(m.group(1)) == 1:
                out.append(ln)  # H1 标题（正文里不该有，出现则不碰）
                continue
            if m:
                raw = m.group(2).strip()
                head = (unwrap_bold_head(raw), len(m.group(1)), raw)
            else:
                b = BOLD_ONLY_RE.match(ln)
                if b and bold_can_be_head(b.group(1).strip()):
                    bold = b.group(1).strip()
        if head is None and bold is None:
            out.append(ln)
            continue

        if head is not None:
            txt, cur, raw = head
            if BOLD_LIST_ITEM_RE.match(txt):
                # HTML 已把它标成标题，但内容是「编号列表项」—— 保层级、去掉加粗
                out.append("%s %s" % ("#" * cur, txt) if txt != raw else ln)
                continue
            kind, lvl = classify_head_number(txt, has_multi_dot)
            if kind == "plain":
                # 抓取器已定级的无编号标题（如 `## 总结`）：保持原级，并回到顶层
                if cur == 2:
                    num_depth = 0
                last, last_kind = cur, "plain"
                out.append("%s %s" % ("#" * cur, txt) if txt != raw else ln)
                continue
        else:
            txt, cur = bold, None
            if BOLD_LIST_ITEM_RE.match(txt):
                # 编号列表项（`3.可视化展示` / `（1）朴素 RAG…`），作者只是顺手加粗 —— 不是标题
                out.append(ln)
                continue
            kind, lvl = classify_head_number(txt, has_multi_dot)

        if kind in ("dot", "int"):
            level = lvl
            num_depth = level
        elif kind == "dot1":
            # `1. 小节名`：默认层级 3（F5 口径），且**不更新 num_depth**。
            # num_depth 的用途是「包住后面那些无编号子标题」（如容器云的
            # `1.2.1 协议栈` 下的 `Underlay网络`）。而 `1.` 级小节的兄弟往往就是
            # 无编号的**章**标题 —— F5 那篇里 `1.–7.` 之后紧跟着 `架构分析`／`技术建议`，
            # 一旦让 dot1 抬高 num_depth，这两个章标题会被误压到 ####（pitfalls #28）。
            # 但全文有 `1.1` 时 dot1 就是章（层级 2），按 `int` 一样更新 num_depth。
            level = lvl
            if has_multi_dot:
                num_depth = level
        elif kind == "two":
            level = last if last_kind == "two" else ((last + 1) if last else 3)
        else:  # plain 加粗行
            if num_depth >= 3:
                level = num_depth + 1
            else:
                level = 2
                num_depth = 0
        level = max(2, min(level, 6))
        new = "%s %s" % ("#" * level, txt)
        if new != ln:
            changed = True
        out.append(new)
        last, last_kind = level, kind

    if changed:
        notes.append("按编号重建章节层级（多级标题）")
    return "\n".join(out), notes


IMG_LINE_RE = re.compile(r"^\s*!\[")
FIGCAP_LINE_RE = re.compile(r"^图\s*\d")


def _is_body_line(ln):
    """这一行算不算「正文内容」（用来判断一个标题是不是「空章标题」）。

    空行、图片、图注（`图1 xxx`）、分隔线都不算 —— 公众号的大节标题下面
    常常只放一张配图就进子节。
    """
    s = ln.strip()
    if not s or s in ("---", "***", "___"):
        return False
    return not (IMG_LINE_RE.match(s) or FIGCAP_LINE_RE.match(s))


def fold_empty_heads(text):
    """把「空章标题」下的同级标题降一级（pitfalls #26）。

    公众号常见排版：大节标题后面**一个字都不写**，直接进子节：

        **SDN VBC控制平面**
        **GoBGP消息同步机制**
        **01GoBGP speaker和RS-Node**

    前两行在 HTML 里字号完全一样（都是 16px 加粗、都没有编号），
    `rebuild_headings` 只能按「无编号 → 顶层」处理，于是两行都成了 `##`，
    大节退化成一个空标题。

    判据只有一个：**标题 A 与紧随其后的标题 B 之间没有任何正文行**
    （空行 / 图片 / 图注 / 分隔线都不算正文）→ A 是「章标题」，
    B 及其同级兄弟都该挂到 A 下面。

    作用域在这两种情况下关闭：
      1. 遇到比 A 更浅的标题；
      2. 遇到一个「自己就要开编号子节组」的无编号标题（它后面紧跟 `01`
         这类两位编号）—— 那是新的章，不该继续吃上一章的缩进。
    """
    lines = text.split("\n")
    flags = fence_map(lines)

    heads = []
    for i, ln in enumerate(lines):
        if flags[i]:
            continue
        m = HEAD_LINE_RE.match(ln)
        if not m or len(m.group(1)) < 2:
            continue
        txt = m.group(2).strip()
        heads.append({
            "i": i,
            "level": len(m.group(1)),
            "txt": txt,
            "kind": classify_head_number(txt)[0],
        })
    if len(heads) < 2:
        return text, []

    for k in range(len(heads) - 1):
        seg = lines[heads[k]["i"] + 1: heads[k + 1]["i"]]
        heads[k]["empty"] = not any(_is_body_line(x) for x in seg)

    scope, armed, delta, changed = None, False, 0, False
    for k, h in enumerate(heads):
        if scope is not None:
            close = h["level"] < scope
            if not close and h["kind"] == "plain" and not armed:
                nxt = heads[k + 1] if k + 1 < len(heads) else None
                if nxt and nxt["kind"] == "two" and nxt["level"] >= h["level"]:
                    close = True
            if close:
                scope, armed, delta = None, False, 0
            else:
                if delta:
                    h["level"], changed = h["level"] + delta, True
                armed = False
        if scope is None and h["kind"] == "plain" and h.get("empty"):
            nxt = heads[k + 1] if k + 1 < len(heads) else None
            # 后面紧跟的若是**带编号**的小节（`01 …`），说明层级已由编号定好，
            # 不该再折。否则「## 域名安全设计 + ### 01 …」会被多降一级，而且作用域
            # 会一直开着，把后面同级的 `## 总结` 也吞进去（「G行」那篇就是这样）。
            if nxt is None or nxt["kind"] == "plain":
                scope, armed = h["level"], True
                # 折叠量按**差值**算，不是无条件 +1：空章标题的子节应当「恰深一级」。
                # 子节若本来就比它深（`## 四、总结` + `### 何谓微服务`，后者的 `###`
                # 来自 Word 的 `<h4>`），再 +1 会跳级成 `####`；而「SDN」那篇里
                # `## SDN VBC控制平面` 的子节们全塌到了 `##`，需要整组 +1
                # （含其后代 `01/02/03` —— 差值会一致地传下去）。
                delta = max(0, scope + 1 - (nxt["level"] if nxt else scope))

    if not changed:
        return text, []
    for h in heads:
        lines[h["i"]] = "%s %s" % ("#" * h["level"], h["txt"])
    return "\n".join(lines), ["按「空章标题」折叠子节层级"]


QUOTES = "“”"


def normalize_quotes(line):
    out, toggle = [], 0
    for ch in line:
        if ch in QUOTES:
            out.append("“" if toggle == 0 else "”")
            toggle ^= 1
        else:
            out.append(ch)
    return "".join(out)


GLUE_RE = re.compile(r"[\u4e00-\u9fa5]\s+[A-Za-z]")
IMG_ALT_RE = re.compile(r"^Image(?=\S)")


def fix_heading_lines(lines):
    """修标题行，两件事：

    1. 去掉抓取器残留的 `Image` alt 前缀（`## Image结论：…` -> `## 结论：…`）。
       `!\\[Image\\](url)` 的方括号与链接被剥掉后只剩这个词，会让标题带上脏前缀。
    2. 拆分「标题里塞进了正文句子」的行 —— 断点取「汉字 + 空格 + 拉丁字母」
       （正文常以英文术语开头），但切出来的正文必须是完整句子（含 `。`）。
       没有这道闸门，`范围 vs 精度：…？`、`徐文辉    S068…` 这类正常标题会被误拆。

    代码围栏内的 `# 创建 Skill` 是文章里的示例代码，必须原样保留。
    """
    out, inside = [], False
    for ln in lines:
        if ln.lstrip().startswith("```"):
            inside = not inside
            out.append(ln)
            continue
        m = None if inside else re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            text = IMG_ALT_RE.sub("", m.group(2))
            hit = GLUE_RE.search(text)
            if hit and "。" in text[hit.end():]:
                cut = hit.start() + 1
                head, body = text[:cut].rstrip(), text[cut:].strip()
                if head and body:
                    out.extend(["%s %s" % (m.group(1), head), "", body])
                    continue
            if text != m.group(2):
                out.append("%s %s" % (m.group(1), text))
                continue
        out.append(ln)
    return out


def convert(dir_name, base, tags, date_override=None):
    art_dir = os.path.join(base, dir_name)
    src = os.path.join(art_dir, dir_name + ".md")
    dst = os.path.join(art_dir, dir_name + ".obsidian.md")
    notes = []

    with open(src, encoding="utf-8") as f:
        text = f.read()

    fm, text = read_fm(text)
    quote_meta, raw_h1, text = read_quote_meta(text)
    if quote_meta:
        notes.append("从正文引用块兜底提取元信息：" + "、".join(sorted(quote_meta)))

    title = fm.get("title") or raw_h1 or dir_name
    title = IMG_ALT_RE.sub("", re.sub(r"!\[[^\]]*\]\([^)]*\)", "", title)).strip() or dir_name
    author = fm.get("author") or quote_meta.get("author", "")
    pubdate = date_override or fm.get("date") or quote_meta.get("date") or ""
    source = fm.get("source") or quote_meta.get("source", "")

    # 尾部推广截断（围栏感知 + 尾巴比例过滤）
    idx = find_promo_sep(text)
    if idx != -1:
        notes.append("截断尾部推广 %d 字符" % (len(text) - idx))
    else:
        # 形态 C：没有结尾分隔线。三个候选**取更靠前的那个** —— 这一步不能省：
        # F5 那篇的 `end` 夹在推广块**内部**（「关注 F5社区」在它前面），若让 END
        # 优先反而会把整个关注引导留下。导航区（find_promo_nav）也是候选之一。
        cands = []
        t = find_promo_tail(text)
        if t != -1:
            cands.append((t, "无分隔线形态"))
        e = find_promo_end(text)
        if e != -1:
            cands.append((e, "正文结束标记"))
        n = find_promo_nav(text)
        if n != -1:
            cands.append((n, "历史文章导航区"))
        if cands:
            idx, why = min(cands, key=lambda c: c[0])
            notes.append("截断尾部推广（%s） %d 字符" % (why, len(text) - idx))
    if idx != -1:
        text = text[:idx]

    # 文首引流块（形态 D：白皮书连载的「节选自《X》+ 扫码 + 添加助手 + 免费获取」）
    hidx = find_promo_head(text)
    if hidx != -1:
        notes.append("截断文首引流块 %d 字符" % hidx)
        text = text[hidx:]

    # 文首「重复标题」banner（= H1 的加粗复读 + 题图）——删掉，免得在大纲里变成假标题
    deduped = strip_dup_title_head(text, title)
    if deduped != text:
        notes.append("删除文首重复标题 banner")
        text = deduped

    # 「假标题」：作者把摘要/导语也套了标题样式，HTML 里就是真 <h3> —— 降回段落。
    # 必须跑在 shift_body_headings() 之前：层级归一要看「正文最浅标题」，假标题会带偏。
    text = demote_fake_headings(text, notes)

    # 正文标题的层级基准：把最浅的一级归到 `##`（Word 粘贴型可能偏深或偏浅）
    text = shift_body_headings(text, title, notes)

    # 引流语 / 残留段落
    kill = [
        (r"^★\s*点击名片，关注我们不迷路\s*★\s*$", "引流语『点击名片关注』"),
        (r"^投稿邮箱：.*$", "投稿邮箱"),
        (r'^“?[\w\u4e00-\u9fa5]+”?公众号诚邀.*$', "投稿邀请"),
        (r"^(近期好文|相关阅读|推荐阅读)：\s*$", "推荐阅读"),
        (r"^!\[[^\]]*\]\(images/[^)]*\)“?点赞.*$", "点赞引导"),
        # 「后台 + 私信/对话框/留言/回复 + 获取/领取/下载 + 名词」整行删除。
        # 三个条件必须同时成立才删，正文句子几乎不可能同现（已补反向用例）。
        # 名词表历次补充：原文/报告/文件/资料/PDF（初版）→ 白皮书/文档/全文（#39）
        # → 综述/论文/PPT/课件/方案（第 14 篇「后台回复260923获取完整综述」）。
        # 触发动词同理：私信（#39 前）→ 对话框/回复（#39 / 第 14 篇）。
        (r"^.*后台[^\n]{0,10}(?:私信|对话框|留言|回复).*(?:获取|领取|下载).*"
         r"(?:原文|报告|文件|资料|PDF|白皮书|文档|全文|综述|论文|PPT|课件|方案).*$",
         "『后台获取资料』引导"),
        (r"^#{1,6}\s*[^\n]*拓展阅读[^\n]*$", "『拓展阅读』导航条"),
    ]
    for pat, label in kill:
        if re.search(pat, text, flags=re.MULTILINE):
            text = re.sub(pat, "", text, flags=re.MULTILINE)
            notes.append("删除残留：" + label)

    # 图片 -> Obsidian embed，独占一行
    # 注意 (?:\s+"[^"]*")? 用于吃掉微信偶尔附带的 title 属性，
    # 形如 ![](images/img_0.png "undefined")；漏掉它会把 "undefined" 当成文件名的一部分。
    text = re.sub(
        r'!\[[^\]]*\]\(images/([^)\s]+)(?:\s+"[^"]*")?\)',
        lambda m: "\n![[images/%s]]\n" % m.group(1),
        text,
    )

    # 机构文的 PART 标记：**PART**01** / **PART****02** / **PART02**
    # 必须先于「加粗分裂合并」执行：否则 **PART****02** 会先被合并成 **PART02** 而漏掉。
    if re.search(r"\*\*PART\*{0,4}\s*\d+\*{0,4}", text):
        text = re.sub(r"\*\*PART\*{0,4}\s*\d+\*{0,4}[ \t]*\n?", "", text)
        notes.append("清理 PART 标记")

    # 加粗小标题的切碎形态：编号/标题配对。
    # ⚠️ 必须在「加粗分裂合并」之前跑（合并会把结构边界抹平，见 pitfalls #28）。
    text, norm_notes = normalize_bold_headings(text)
    notes.extend(norm_notes)

    # 加粗分裂合并：微信常把一段加粗按 token 切成 **A****B****C**
    # 只在行内合并（前后都是非空白），以免误伤独占一行的 ****（Markdown 水平分割线）。
    merged = re.sub(r"(?<=\S)\*\*\*\*(?=\S)", "", text)
    if merged != text:
        notes.append("合并微信分裂的加粗标记")
        text = merged

    # 编号与下一行的「**名称**」合并（章 / 节的口径见 merge_numbered_names）
    text, num_notes = merge_numbered_names(text)
    notes.extend(num_notes)

    # 反斜杠残留：只处理「转义标点/下划线」与独占一行的 \，
    # 不动 C:\Users 这类后跟字母的合法反斜杠。
    text = re.sub(r"\\([_*\[\]()#!`>+\-.])", r"\1", text)
    text = re.sub(r"^\\[ \t]*$", "", text, flags=re.MULTILINE)

    # 空引用行
    text = re.sub(r"^>[ \t]*$", "", text, flags=re.MULTILINE)

    # 中文引号按行成对归一化（跳过代码围栏）
    lines, in_fence, changed = [], False, False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            lines.append(line)
            continue
        new = line if in_fence else normalize_quotes(line)
        if new != line:
            changed = True
        lines.append(new)
    text = "\n".join(lines)
    if changed:
        notes.append("归一化中文引号（按行成对）")

    # 目录块重排（必须在标题重建之前：「目录」那一行此刻还是加粗形态）
    text = rebuild_toc(text, notes)

    # 章节层级：按编号重建多级标题（旧版是一律把 ### 压成 ##，没有层级）
    text, head_notes = rebuild_headings(text)
    notes.extend(head_notes)

    # 「大节标题后直接进子节」的折叠（大节在 HTML 里与小节字号相同，只能靠
    # 「其后无正文」这一条判据）
    text, fold_notes = fold_empty_heads(text)
    notes.extend(fold_notes)

    # 标题-正文粘连拆分
    fixed = fix_heading_lines(text.split("\n"))
    if fixed != text.split("\n"):
        notes.append("拆分粘连的标题-正文")
        text = "\n".join(fixed)

    # 全文清理
    text = text.replace("\u200b", "")
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    created = datetime.datetime.now().isoformat()
    fm_out = "---\ncreated: '%s'\ntags:\n%s---\n\n" % (
        created,
        "".join("- %s\n" % t for t in tags),
    )
    callout = "> [!info] 文章信息\n> **标题**：%s\n" % title
    if author:
        callout += "> **作者**：%s\n" % author
    if pubdate:
        callout += "> **发布日期**：%s\n" % pubdate
    if source:
        callout += "> **来源**：[微信原文](%s)\n" % source
    tail = " ".join("#" + t for t in tags)

    out = "%s# %s\n\n%s\n%s\n\n%s\n" % (fm_out, title, callout, text, tail)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)

    print("WROTE:", dst)
    for n in notes:
        print("  *", n)
    print("  图片引用:", ", ".join(re.findall(r"!\[\[([^\]]+)\]\]", out)) or "无")
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir_name", help="文章目录名（output 下的子目录）")
    ap.add_argument("--base", default=DEFAULT_BASE, help="output 根目录")
    ap.add_argument("--tags", nargs="*", default=[], help="标签")
    ap.add_argument("--date", help="覆盖发布日期 (YYYY-MM-DD)")
    a = ap.parse_args()
    convert(a.dir_name, a.base, a.tags, a.date)


if __name__ == "__main__":
    main()
