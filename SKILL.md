---
name: wechat-article-pipeline
description: "微信公众号文章一体化流水线：抓取（mp.weixin.qq.com → 干净 Markdown）→ 转换（Obsidian 风格：三层分面标签 / callout 元信息 / ![[图片]] 嵌入 / 多级标题重建 / 文末推广与文首引流截断 / 引号归一化）→ 校验（Tier-1 八项结构体检，退出码可做门禁）→ 落库（vault 内每篇一个子文件夹，只复制正文引用的图片）→ 索引（登记进《知识库索引》的主题导航，供图谱聚类）。当用户给出 mp.weixin.qq.com 链接、说「抓取/保存这篇公众号文章」「同步微信文章到 obsidian / 知识库」「抓完即校验」「校验一下这篇」「微信文章入库」「打标签」「登记进知识库索引」，或需要单独跑其中某一步（抓取 / 转换 / 校验 / 落库 / 建索引）时使用。"
agent_created: true
---

# WeChat Article Pipeline（配置 → 抓取 → 转换 → 校验 → 落库 → 索引）

把公众号文章变成 Obsidian 里一篇**结构正确、标签规范、无推广残渣、图片可用、能在知识库里被找到**的笔记。
各环节在同一条流水线上，也可只用其中一步。

| 步骤 | 脚本 | 输入 → 输出 |
|------|------|-------------|
| 0 配置 | `scripts/setup_env.py` | 一次性：生成 `.env`（vault 路径等本机私有值） |
| 1 抓取 | `wechat_article_to_markdown.py` | URL → `<BASE>/<目录名>/<目录名>.md` + `images/` |
| 2 转换 | `scripts/to_obsidian.py` | 上一步的 `.md` → `<目录名>.obsidian.md`（含三层分面标签） |
| 3 校验 | `scripts/verify_wechat_md.py` | `.obsidian.md` → 报告 + 退出码（0=PASS / 2=FAIL） |
| 4 落库 | `scripts/sync_to_vault.py` | `.obsidian.md` → `vault/<公众号目录>/【NNN】<标题>/【NNN】<标题>.md` + 被引用的图 |
| 5 索引 | `scripts/update_index.py` | 笔记 → 《知识库索引》里对应主题段落的一行导航 |
| 5.5 计数 | `scripts/tag_stats.py` | 全库 frontmatter → 重算「一、标签体系」的覆盖计数（第 5 步写盘后自动跑） |

推荐顺序：**配置（仅首次）→ 抓取 → 转换 → 校验 → 落库 →（落库时顺手）索引**（高价值文章可在落库后再跑一次校验）。
校验失败**不要落库** —— 结构缺陷一旦进 vault，后面很难察觉。

> 🧭 **标签谁给**：正常情况下 **agent 读完全文后给**（`--tags`），质量最好。
> `scripts/tag_infer.py` 只是兜底：不给标签时按关键词词表推断，保证「不传也不空」。
> 兜底在 28 篇既有笔记上实测：类型命中 86%、主题至少中一个 89%（口径见 `tests/convert/test_tag_infer.py`）。
> 索引行末尾那句「— 一句话价值点」同样由 agent 读完全文后通过 `--summary` 给。

## 环境

脚本都在本 skill 目录下，用**自带的 `.venv`** 跑（已装齐依赖）：

```bash
cd ~/.workbuddy/skills/wechat-article-pipeline      # 或你 clone 的位置
PY=".venv/Scripts/python.exe"                        # Unix/macOS: .venv/bin/python
BASE="<输出根目录>"                                   # 不传 --base 时默认 cwd/output
D="<文章目录名>"                                      # output/ 下的子目录名，常与标题不同
```

依赖（见 `requirements.txt`）：`camoufox[geoip] markdownify beautifulsoup4 httpx requests pyyaml`。
其中 **只有落库脚本需要 pyyaml**，转换与校验脚本是纯标准库。

> ⚠️ **Windows / Git Bash 路径**：别把 `$HOME/...` 展开出来的路径（`/c/Users/...`，MSYS 风格）
> 当**参数**交给原生 Windows Python —— 会报 `can't open file 'c:\c\Users\...'`。
> 用上面的 `cd` + **相对路径**，或写成 `C:/Users/...`，或 `cygpath -w "$p"`。
> （`"$HOME/.../python.exe"` 作*命令*没问题，只有作*参数*才会炸。）

## 0. 配置（首次必做，且**必须先检查**）

本仓库会公开到 GitHub，所以**任何真实路径都不许写进脚本**。私有值只放仓库根的 `.env`
（已 gitignore），公开模板是 `.env.example`（占位符，入库）。

```bash
"$PY" scripts/setup_env.py --check     # 体检：已配好？vault 存在？目录匹配到什么？
"$PY" scripts/setup_env.py             # 未配置时：交互向导，生成 .env
```

**Agent 处理规则（重要）**：跑落库/索引之前先 `--check`。

| `--check` 结果 | 该做什么 |
|---|---|
| 退出码 0 | 直接用，不必再问 |
| 退出码 2（未配置） | **停下来问用户 vault 根在哪**，拿到路径后再跑 `setup_env.py --vault "<路径>"`。**不要猜、不要用 `~/iNote` 之类的默认值硬跑** —— 那会把笔记写进错误目录 |
| 退出码 1（路径失效/缺 `.obsidian`） | 告诉用户目录看起来不对，请其确认后再写 |

只有落库（步骤 4）与索引（步骤 5）需要配置；抓取/转换/校验不依赖 vault，未配置也能跑。

| 键 | 必填 | 说明 |
|---|---|---|
| `WECHAT_VAULT` | ✅ | vault 根（装有 `.obsidian` 的那个目录） |
| `WECHAT_SUBFOLDER_PATTERN` | | 落库一级目录通配，默认 `*公众号`（能匹配 `【15】公众号`） |
| `WECHAT_SUBFOLDER` | | 写死目录名时用，优先级高于通配 |
| `WECHAT_INDEX_PATTERN` | | 索引页通配，默认 `*知识库索引*.md` |
| `WECHAT_OUTPUT_BASE` | | 产物根目录，默认 `<cwd>/output` |
| `WECHAT_TAXONOMY` / `WECHAT_INDEX_LAYOUT` | | 词表与索引布局，默认仓库自带 |
| `WECHAT_ENV_FILE` | | 指定另一份 .env（多 vault 切换 / 测试用） |

解析优先级：**命令行 > 真实环境变量 > 仓库根 `.env` > 报错**。
（真实环境变量排在 `.env` 前面，所以 `WECHAT_VAULT=/tmp/x "$PY" …` 这种临时覆盖永远有效。）
实现见 `scripts/env_config.py`，不要再在脚本里写死路径或另起一套解析。

## 1. 抓取

`wechat_article_to_markdown.py` 在**仓库根**（与上游 jackwener 的布局一致）。
默认两级策略：先 `requests` 直取 HTML，只有拿到风控页/验证页时才自动升浏览器重抓。

```bash
"$PY" wechat_article_to_markdown.py "<URL>" -o "$BASE"
# 只想走最快的非浏览器模式（公众号正文是服务端渲染的，通常够用）
"$PY" wechat_article_to_markdown.py "<URL>" -o "$BASE" --mode requests
```

| 参数 | 说明 |
|---|---|
| `--mode auto`（默认）/ `requests` / `browser` | 两级 / 只用 requests（最快）/ 只用浏览器 |
| `--browser-engine camoufox\|chromium` | 浏览器兜底引擎（默认 camoufox） |
| `--browser-timeout` | 浏览器整体硬超时（默认 90s） |
| `--cookie "k=v; k2=v2"` / `--proxy URL` | 受限文章 / 走代理 |
| `--timeout` / `--retries` | requests 超时与重试（默认 30s / 3 次） |
| `--save-html raw.html` / `--html-file raw.html` | 存原始 HTML / 离线复跑，不发网络请求 |

- 两种模式**产物逐字节一致**，下游无需改动。
- 内容已失效（删除/违规/过期）报 `unavailable` 且**不升浏览器**（重试无意义）。
- 风控判定（`detect_page_problem()`）只认 HTTP 状态码、缺 `#js_content`/`#activity-name`、
  响应体异常小、风控特征串 —— **刻意不扫正文关键词**，否则讨论风控的文章会被误判。
- 标题里的章节标题提升：`<section>` 样式块（`font-weight:bold` + `font-size>=16px`）→ 标题，
  同篇 **17px / 16px 两档并存**时按字号分 `##`/`###`，单字号则一律 `##`；
  「整段加粗 + 编号」的 `<p>`（`1` / `1.1` / `1.2.1`）→ `##`/`###`/`####`。
- 本机 camoufox 二进制无法被自动化驱动（**已完整验证与版本无关，勿再试"换稳定版"**），
  需要浏览器兜底时加 `--browser-engine chromium`。见 `references/fetch-notes.md`。

## 2. 转换（→ Obsidian 风格）

```bash
"$PY" scripts/to_obsidian.py "$D" --base "$BASE" --tags 主题/网络/DNS 类型/技术教程 来源/微信公众号 --date 2026-09-23
```

**标签怎么写**（三层分面，每篇至少各一个 —— 这套词表在 `references/taxonomy.json`，
与库里的《知识库索引》「一、标签体系」是同一份东西）：

| 分面 | 形态 | 例子 | 说明 |
|---|---|---|---|
| 主题 | `主题/<一级>/<二级>` | `主题/网络/DNS` | 讲什么。一篇 2–3 个，按重要性排序，**第一个决定索引落位** |
| 类型 | `类型/<体裁>` | `类型/技术教程` | 八选一：技术教程 / 方案实践 / 工具速查 / 趋势解读 / 深度研报 / 个股研究 / 观点随笔 / 模板 |
| 来源 | `来源/微信公众号` | — | 固定值 |

- 优先用**已有二级标签**（`taxonomy.json` 里那 40 条），避免造同义词（「运维」与「运维监控」并存）。
- 内容明确属于新领域时可以新开二级（如 `主题/网络/Kubernetes网络`），但**要同时在索引页
  「一、标签体系」表里补一行** —— `update_index.py` 会提醒你哪些标签还没登记。
- 只零星提到一次的词**不要**打成标签。宁可少打，也不要噪声把图谱搅浑。
- 文末**不再**写裸 `#标签` 行（2026-11-04 起）：标签只放 frontmatter，避免同一份信息两处维护。
- 不给 `--tags` 时会用 `tag_infer.py` 兜底推断并打印结果；加 `--no-auto-tags` 可关掉留空。

它做的这些事（逐条见 `references/pitfalls.md`），核心是：

1. 重建 frontmatter（`created` + `tags`）+ 顶部 `> [!info] 文章信息` callout；
2. `![](images/x.png)` → `![[images/x.png]]` 且独占一行；
3. **截断文末推广**：`---` 分隔线 / 文末标记行（关注·二维码·推荐阅读·署名·`点击…阅读原文`·
   `**END**`…）/ **历史文章导航区**（≥8 条连续 mp 链接的结构判据）/ **标题式页脚**
   （`**关注我们**`、`### 免责声明` 这类「整行就是一个标题」的页脚 —— 要求同一块里既有
   法务文字又有推广痕迹，只有法务文字的正文小节不碰），多候选取**更靠前者**；
4. **截断文首引流块**（白皮书连载的「节选自《X》+ 扫码 + 免费获取」）；
5. 删文首重复标题 banner（含被**换行拆成两段**的加粗标题、尾巴上的 `***装饰行***`）、
   把「像段落的假标题」降回正文；
6. **加粗标记归一**：`****甲****` / `****甲********：****乙` 这类 ≥4 颗星号的粘连 → `**`；
7. **正文标题层级基准归一**（最浅一级 → `##`，兼容 Word 粘贴型偏浅/偏深两个方向）；
8. **按编号重建多级标题**（`1`→`##`、`1.1`→`###`、`1.2.1`→`####`）+ 提升整段加粗的标题行；
   `1. 甲` 与 `1.甲` **同等对待**；中文序号 `四、…` 掉成段落时补回标题（全篇一个中文序号
   标题都没有时，≥3 条连续序号可整组认）；章写 `一、`、节写 `1、2、` 时，节挂章下一级；
   `（1）xxx` 括号编号小节（≥3 连续、短行无句号）也补成标题；
9. 折叠「空章标题」；删除单行引流语（「后台+私信/回复…获取…资料/综述」）；
   「构成式」加粗行（`A + B + C`）不当标题，行尾标点被单独加粗（`**。**`）去壳；
10. 标题行去加粗、补空行、`1.xxx` → `1. xxx`；加粗标记断裂合并、反斜杠残留还原、
    中文引号成对归一化、目录块重排、**空表头补齐**（表头被写在 `<tbody>` 首行）、行尾清理。

每步命中都会在 stdout 打处理记录，便于复核。

> ⚠️ **无编号长文的标题层级只能人工重建**。原文靠字号/加粗表达层级时（券商研报最常见），
> 转换器只能按「最浅一级 → `##`」归并，结果是摘要小节与正文小节撞名（导航面板出现两个
> 「股市展望」）、父子节被压平（「转债条款 > 提前赎回 / 到期赎回 / 下修条款」全成同级），
> 偶尔还有加粗标题漏成段落。这类文章**落库前请通读一遍标题树再修** —— 脚本没有可比对的
> 层级信号（没有编号），硬编码规则一定会误伤别的文章。<br>
> 判据：**打开大纲面板，若有同名项或明显该缩进而没缩进的节，就是要修**。

> ⚠️ **尾部有两类东西脚本故意不管，落库前扫一眼**：
> ① **文中 CTA** —— 「了解更多信息，请您扫码查看下方博客和资源」+ 二维码，如果它夹在
> 正文和附录（「研究方法」「数据说明」）**之间**，文末推广规则会把附录一起砍掉，只能人工
> 切中间那一段；② **「关于XX」厂商标尾** —— 公司介绍 + 商标声明 + 视频号 + 往期推荐，
> 短语表里没有 `关于<公司名>`，且这类块的「法务特征」常常只有「商标」二字，四道闸过不了。
> 详见 `references/pitfalls.md` #72。

## 3. 校验（落库门禁）

```bash
"$PY" scripts/verify_wechat_md.py "$BASE/$D/$D.obsidian.md"
```

纯本地、零网络、零第三方依赖。退出码 `0` = PASS（或仅有 WARN），`2` = FAIL。

| # | 检查 | 级别 |
|---|---|---|
| 1 | CODEBLOCK 占位符残留 | FAIL |
| 2 | 重复代码块（多个块内容完全相同） | FAIL |
| 3 | 空 / 截断代码块 | FAIL |
| 4 | 代码围栏闭合（``` 数量为奇数） | FAIL |
| 5 | 标题-正文粘连 | WARN |
| 6 | 残留远程资源（http 图 / `javascript:;`） | WARN |
| 7 | 图片嵌入 vs 文件（缺失=FAIL，多出=提示） | FAIL / 提示 |
| 8 | 三层标签齐全性（主题/类型/来源 各至少一个） | WARN |

- `--strict` 把 WARN 也当 FAIL；`--images` 指定自定义图片目录。
- 第 7 条同时认两种嵌入写法：`![[images/x.png]]`（转换产物）与 `![[公众号/标题/images/x.png]]`
  （落库并改写后的 vault 全路径）。只认前者会让落库后的成品「看起来零引用」。
- 第 8 条只对**已带 frontmatter** 的文件生效（抓取产物没有 YAML 头，会自动跳过）。
  标签是质量项不是结构项，所以判 WARN 不拦落库。序列缩进两种形态（无缩进 / 2 空格）都认 ——
  `yaml.dump()` 写的是前者，Obsidian Linter 会重排成后者。
- ⚠️ 第 5 条的**已知误报**：标题**本身**含 `。！？`（设问式/感叹式标题，
  如 `## 为什么需要 RSI？…`）会被命中。规则**有意偏保守**，判成 WARN 人工过目即可，
  **不要为它收紧规则**。见 `references/verify_sop.md`。
- Tier-1 只证明「结构完整」，证明不了「内容对不对」。需要联网对照原文时（代码密集 /
  报出重复块 / 关键内容是截图 / 高价值文章）按 `references/verify_sop.md` 升级 Tier-2。

## 4. 落库

```bash
"$PY" scripts/sync_to_vault.py "$D" --base "$BASE"
# 落库同时登记索引（推荐）：
"$PY" scripts/sync_to_vault.py "$D" --base "$BASE" --update-index \
      --summary "从词袋检索到图推理的框架演进与选型" --display "从 RAGFlow 到 GraphRAG"
```

- 落点 `vault/<subfolder>/【NNN】<标题>/【NNN】<标题>.md`；`--subfolder` 改中间那级，
  `--folder` 直接指定最终子目录。
- **编号约定**：`【001】` 起、三位、**目录内**按创建时间递增。重跑同一篇会认出
  `【NNN】<标题>` 并复用它（不会新建未编号的孪生目录）；新笔记取目录内最大号 +1。
  想让某篇换号（如补录的老文章要插到前面），只能重排并同步改链接 —— 见 pitfalls #68。
- **行尾跟随 vault**：写盘前用 `detect_vault_eol()` 扫已有 `.md` 取主流行尾（按行数投票，
  点目录不计），再整体翻译。**不要写死 LF** —— 本机实测 63 篇 CRLF / 8 篇 LF（Obsidian
  在 Windows 上存的是 CRLF，被 `update_index` 反复重写的索引页才是 LF），写死会让新笔记
  与全库不一致，`git diff` 整篇都算改动（pitfalls #69）。
  **每篇必须是带标题的独立子文件夹**，否则同名 `img_000.png` 互相覆盖。
- **`--subfolder` 默认走通配解析**，不写死目录名：`.env` 里的 `WECHAT_SUBFOLDER_PATTERN=*公众号`
  会在运行期 glob 唯一候选 —— 因为 vault 目录会加编号前缀、会整体搬家
  （`公众号` → `【15】公众号` 就发生过，且就发生在一次会话进行中）。
  多个候选时**报错而不是猜**。
- **图片嵌入会改写成 vault 全路径**（`![[公众号/标题/images/x.png]]`）。
  vault 开了 `alwaysUpdateLinks`，Obsidian 一打开笔记就会这么改；与其等它改，
  不如落库时就写对 —— 多篇的 `img_001.png` 同名，相对写法在笔记未打开前是歧义的。
  想保留相对写法加 `--relative-links`（标题含 `[ ] | # ^` 时会自动跳过改写）。
- 只复制正文**真正引用**的图片；推广图/二维码留在 output 不落库。
- vault 路径解析优先级：命令行 `--vault` > 环境变量 `WECHAT_VAULT` > 仓库根 `.env` > 报错。
  **换 vault 只改 `.env`**（跑 `scripts/setup_env.py`），不要改脚本 ——
  这个仓库是公开的，写死路径等于把本机目录结构连同用户名一起推上去。

> ⚠️ 落库是 `open(..., "w")` **覆盖写**。目标已存在同名笔记时（公众号常把旧文**再发版**，
> 落库路径相同就会直接覆盖），**先停下来问用户**，不要自动跑。判重方法：比对 vault 里同名
> 笔记的「来源 URL / 发布日期 / 作者」，再用 difflib 归一化正文算相似度。

## 5. 索引登记

```bash
"$PY" scripts/update_index.py --vault "<vault>" --title "<标题>" \
      --tags 主题/网络/DNS 类型/技术教程 来源/微信公众号 \
      --summary "一句话价值点" [--display 短名] [--section 网络 --subgroup DNS] [--dry-run]

# 也可直接吃转换产物（自动读标签与标题）
"$PY" scripts/update_index.py --vault "<vault>" --from-md "<.obsidian.md>" --summary "…"
```

往 vault 根那份《知识库索引》（`*知识库索引*.md`，通配解析）的「二、按主题导航」插一行：

```
- [[笔记标题|显示名]] — 一句话价值点
```

**落位规则**（配置在 `references/index_layout.json`）：

1. **段落**：按笔记 `主题/` 标签的先后顺序，取第一个能对应到大类的定段落。
   `主题/行业/银行`、`主题/架构/高可用` 属于**补充语境**，不参与定位 ——
   「银行」既能是网络也能是金融，按它定位会把文章塞进无关段落。
2. **小组**：段落内找命中的 `**DNS**` 这类粗体小组；段落本身是平铺列表时
   **直接追加，不为单篇新开小组**（否则图谱里多一个只有一篇的孤岛叶节点）。
3. 段落不存在才新建 `### <段落>`；大类都认不出时落到 `其他`。

- **幂等**：同一篇重跑是「更新那一行」，不会变成两行。
- **不会覆盖你的人工成果**：重跑时若没给 `--display` / `--summary`，会**沿用库里已有的值**，
  不会把手工缩写过的显示名冲掉。
- 只改「二、按主题导航」；写盘后会自动跑一次第 5.5 步重算「一、标签体系」的计数
  （不想要时加 `--no-stats`）。
- `--dry-run` 打印 unified diff 不写盘；`--section/--subgroup` 可强制指定落位。

## 5.5 标签体系计数（写盘后自动，也可单独跑）

```bash
"$PY" scripts/tag_stats.py --vault "<vault>"            # 干跑：只打印差异
"$PY" scripts/tag_stats.py --vault "<vault>" --apply    # 落盘
```

从**全库 frontmatter** 重算「一、标签体系」里那些会随笔记增减而失真的数字：
表头「全库 **N 篇笔记**」、`分布：` 行各目录篇数、三个分面的覆盖计数。
索引里**没有一个数字是手写的**，全部由库推导；手工维护计数必然滞后，一滞后就不再是索引。

四条红线（改动前先读 `references/pitfalls.md` #65、#67）：

1. **只改数字与条目**。标签名、行顺序、判定标准、说明文字全部原样保留 ——
   覆盖数是事实（能算），判定标准是判断（只能人写）。
2. **不漏项**。库里有一级标签（`主题/XX`）而表里没这一行时，补整行；
   否则那一级下的笔记不出现在任何数字里，索引「看着完整、实际少算」。
3. **不猜**。表里的写法若对应库里多个同名标签（`主题/AI/自动化` 与
   `主题/运维/自动化`），直接报错（退出码 2）要求写成完整路径，绝不静默取 0。
4. **0 篇不列**。数到 0 的二级项默认移除（索引只该列真实存在的）；
   要保留定义加 `--keep-zero`。

三种写法都认：短名 `智能体`（→ `主题/AI/智能体`）、半截路径 `` `行业/银行` ``
（→ `主题/行业/银行`）、完整路径 `主题/AI/RAG`。一级标签被笔记直接使用时，
表里写 `一级直挂（N 篇）——暂无二级`，脚本只改括号里的数。

段落里没有的新二级 / 新类型会**追加**并提示补判定标准；点开头的目录（`.claudian` 等）
不计入篇数。表格重排按**显示宽度**（CJK 按 2 计），否则中文列会错位。
同篇数的并列项保持表里原有先后，不重排。

## 目录结构

```text
wechat-article-pipeline/
├── wechat_article_to_markdown.py    # 抓取（留在根目录，与上游路径对齐）
├── .env.example                     # ★配置模板（占位符，入库）
├── .env                             # ★本机真实配置，已 gitignore（绝不入库）
├── conftest.py                      # 让两套测试都能 import 到被测模块
├── scripts/
│   ├── env_config.py                # ★配置解析中心（.env 读取 + 优先级 + 体检）
│   ├── setup_env.py                 # ★配置向导（生成 .env）
│   ├── to_obsidian.py               # 转换（纯标准库）
│   ├── tag_infer.py                 # 标签推断兜底 + frontmatter tags 统一解析（纯标准库）
│   ├── sync_to_vault.py             # 落库（需 pyyaml）
│   ├── update_index.py              # 索引登记（纯标准库）
│   ├── tag_stats.py                 # 标签体系计数重算（纯标准库）
│   ├── verify_wechat_md.py          # Tier-1 校验（纯标准库）
│   └── local_config.py              # 【已弃用】兼容层，已 gitignore（无真实路径）
├── references/
│   ├── taxonomy.json                # ★三层标签词表（与索引页「一、标签体系」同步）
│   ├── index_layout.json            # ★标签 → 索引段落/小组 的映射
│   ├── pitfalls.md                  # 72 条踩坑记录（动手改脚本前必读）
│   ├── verify_sop.md                # 校验 SOP：两层设计 / Tier-2 升级判据
│   ├── fetch-notes.md               # 抓取器本机注意（camoufox 结论等）
│   ├── CHANGELOG-local.md           # 转换脚本的历史改动留档
│   ├── to_obsidian.local.diff       # 同上，逐条 diff
│   └── LOCAL-NOTES.md               # ★本机专用，已 gitignore
├── tests/
│   ├── test_core.py test_fetch.py       # 抓取器（pytest）
│   ├── test_e2e_live.py                 # 联网 e2e（默认跳过）
│   └── convert/                         # 转换器 / 标签 / 索引 / 配置（unittest 风格）
└── .github/workflows/ci.yml
```

## 测试与回归

```bash
"$PY" -m pytest tests/ -q -m "not e2e"        # 全部 331 项（330 通过 + 1 跳过），无需网络
"$PY" -m pytest tests/ -q -m e2e              # 联网 e2e（需浏览器运行时）
"$PY" -m unittest discover -s tests/convert -v # 只跑转换器/标签/索引/配置那 244 项
"$PY" scripts/tag_infer.py --self-test         # 词表自检（结构 + 每个二级≥2 关键词）
"$PY" scripts/setup_env.py --check             # 配置体检（不含完整路径，可安全粘贴）
"$PY" scripts/tag_stats.py --vault "<vault>"   # 标签体系计数干跑（有差异才需要 --apply）
```

- 抓取器那套是 **pytest**，转换器那套是 **unittest**；`conftest.py` 已把仓库根与 `scripts/`
  插进 `sys.path`，所以 pytest 一条命令能同时收集两套。
- ⭐ **改动标题 / 推广规则的硬性回归**：除单测外，还要拿 vault 里**全部已落库成品**跑一遍，
  确认新规则零命中（假阳性回归）。更严格的做法是
  `git show HEAD:<旧脚本>` 导出旧版、新旧各跑同一批文章、两两 diff —— 这样才能把
  「本次改动的影响」与「上一批规则留下的差异」分开。只跟 vault 现存成品比是分不清的。
- ⭐ **改动标签词表 / 索引落位**的回归另有一套：拿库里已有人工标签的笔记当标准答案，
  比对 `tag_infer` 的推断结果（准确率口径见测试文件头）。当前基线：
  **类型命中 86%、主题至少中一个 89%、主题 F1 67%**（28 篇样本）。改词表后这个数不该变差。

## 硬性约定

- 改 skill / 覆盖文件前先备份到项目内 `.workbuddy/archive/<日期>-<主题>/`。
- **本仓库是公开的**：本机绝对路径（vault、解释器、用户名）一律不进受版本管理的文件。
  私有值只放 `.env`（gitignore），公开模板只放 `.env.example` 的占位符。
  新增配置项要同时改三处：`env_config.KEYS`、`.env.example`、本文档第 0 节。
- 判断「有没有泄漏」不能只看工作区：`git grep` 查当前树、
  `git log --all -p | grep <用户名>` 查历史、`git ls-files` 确认忽略文件没被跟踪。
  `.gitignore` 对已跟踪文件无效，这是最容易漏的一环。
- **本机目录会变**：vault 曾从 `iNote` 改到 `笔记库/公众号`、又拍平并加编号前缀成
  `【15】公众号`（就发生在一次会话里）。所以 `--subfolder` 与索引文件名一律走**通配解析**，
  别在任何脚本里写死目录名。
- **标签词表只有一份真源**：`references/taxonomy.json`。新增/改名二级标签要同步改它
  **和** vault 里的《知识库索引》「一、标签体系」表，否则推断器与索引页各说各话。
- 判断两个副本有没有差异前**先排除行尾**（`diff --strip-trailing-cr`、`git ls-files --eol`）——
  本机 `core.autocrlf=true`，仓库带 `.gitattributes`（`* text=auto eol=lf`），工作区是 LF。
- **别把带中文的 Python 代码用 `python -c` 传给原生 Windows Python** —— Git Bash 的代码页会
  把 CJK 路径弄坏，报 `FileNotFoundError`，看起来像「目录不存在」，实际是编码。写成 `.py` 文件再跑。
- 风格规则以本 skill 的脚本为准；Obsidian 语法含义查 `obsidian-markdown`，库内标签约定查
  vault 里的《知识库索引》。

## 出处

- **抓取器**：fork 自 [jackwener/wechat-article-to-markdown](https://github.com/jackwener/wechat-article-to-markdown)，
  本仓库在其基础上做了两级抓取重构、样式块字号分级、标题内图片解包等改造（`upstream` 仍指向它）。
- **转换 / 落库 / 校验**：自研，演化自 2026-07 起在本地项目「微信公众号知识库」中迭代的脚本。
- `scripts/sync_to_vault.py` 的 `format_frontmatter()` / `create_note()` 两个函数内联自
  skillhub.cn 的 `obsidian-direct`（作者 ruslanlanket），行为保持等价 —— 详见 `README.md`。
