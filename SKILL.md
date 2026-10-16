---
name: wechat-article-pipeline
description: "微信公众号文章一体化流水线：抓取（mp.weixin.qq.com → 干净 Markdown）→ 转换（Obsidian 风味：callout 元信息 / ![[图片]] 嵌入 / 多级标题重建 / 文末推广与文首引流截断 / 引号归一化）→ 校验（Tier-1 七项结构体检，退出码可做门禁）→ 落库（vault 内每篇一个子文件夹，只复制正文引用的图片）。当用户给出 mp.weixin.qq.com 链接、说「抓取/保存这篇公众号文章」「同步微信文章到 obsidian / 知识库」「抓完即校验」「校验一下这篇」「微信文章入库」，或需要单独跑其中某一步（抓取 / 转换 / 校验 / 落库）时使用。"
agent_created: true
---

# WeChat Article Pipeline（抓取 → 转换 → 校验 → 落库）

把公众号文章变成 Obsidian 里一篇**结构正确、无推广残渣、图片可用**的笔记。
四个环节在同一条流水线上，也可只用其中一步。

| 步骤 | 脚本 | 输入 → 输出 |
|------|------|-------------|
| 1 抓取 | `wechat_article_to_markdown.py` | URL → `<BASE>/<目录名>/<目录名>.md` + `images/` |
| 2 转换 | `scripts/to_obsidian.py` | 上一步的 `.md` → `<目录名>.obsidian.md` |
| 3 校验 | `scripts/verify_wechat_md.py` | `.obsidian.md` → 报告 + 退出码（0=PASS / 2=FAIL） |
| 4 落库 | `scripts/sync_to_vault.py` | `.obsidian.md` → `vault/公众号/<标题>/<标题>.md` + 被引用的图 |

推荐顺序：**抓取 → 转换 → 校验 → 落库**（高价值文章可在落库后再跑一次校验）。
校验失败**不要落库** —— 结构缺陷一旦进 vault，后面很难察觉。

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

## 2. 转换（→ Obsidian 风味）

```bash
"$PY" scripts/to_obsidian.py "$D" --base "$BASE" --tags 标签1 标签2 --date 2026-09-23
```

`--tags` **必给**，否则 frontmatter 与文末标签静默为空。

它做的 18 件事（逐条见 `references/pitfalls.md`），核心是：

1. 重建 frontmatter（`created` + `tags`）+ 顶部 `> [!info] 文章信息` callout；
2. `![](images/x.png)` → `![[images/x.png]]` 且独占一行；
3. **截断文末推广**：`---` 分隔线 / 文末标记行（关注·二维码·推荐阅读·署名·`点击…阅读原文`·
   `**END**`…）/ **历史文章导航区**（≥8 条连续 mp 链接的结构判据），多候选取**更靠前者**；
4. **截断文首引流块**（白皮书连载的「节选自《X》+ 扫码 + 免费获取」）；
5. 删文首重复标题 banner（含尾巴上的 `***装饰行***`）、把「像段落的假标题」降回正文；
6. **正文标题层级基准归一**（最浅一级 → `##`，兼容 Word 粘贴型偏浅/偏深两个方向）；
7. **按编号重建多级标题**（`1`→`##`、`1.1`→`###`、`1.2.1`→`####`）+ 提升整段加粗的标题行；
8. 折叠「空章标题」；删除单行引流语（「后台+私信/回复…获取…资料/综述」）；
9. 加粗标记断裂合并、反斜杠残留还原、中文引号成对归一化、目录块重排、行尾清理。

每步命中都会在 stdout 打处理记录，便于复核。

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

- `--strict` 把 WARN 也当 FAIL；`--images` 指定自定义图片目录。
- ⚠️ 第 5 条的**已知误报**：标题**本身**含 `。！？`（设问式/感叹式标题，
  如 `## 为什么需要 RSI？…`）会被命中。规则**有意偏保守**，判成 WARN 人工过目即可，
  **不要为它收紧规则**。见 `references/verify_sop.md`。
- Tier-1 只证明「结构完整」，证明不了「内容对不对」。需要联网对照原文时（代码密集 /
  报出重复块 / 关键内容是截图 / 高价值文章）按 `references/verify_sop.md` 升级 Tier-2。

## 4. 落库

```bash
"$PY" scripts/sync_to_vault.py "$D" --base "$BASE"
```

- 落点 `vault/<subfolder>/<标题>/<标题>.md`，默认 `subfolder=公众号`（`--folder` 可覆盖）。
  **每篇必须是带标题的独立子文件夹**，否则同名 `img_000.png` 互相覆盖。
- 只复制正文**真正引用**的图片；推广图/二维码留在 output 不落库。
- vault 路径解析优先级：环境变量 `WECHAT_VAULT` → `scripts/local_config.py` 的 `DEFAULT_VAULT`
  → 中性默认 `~/iNote`。**换 vault 只改 `local_config.py`**（已 gitignore），
  不要把绝对路径写回脚本 —— 那会让 `git pull` 冲突，push 还会公开本机路径。

> ⚠️ 落库是 `open(..., "w")` **覆盖写**。目标已存在同名笔记时（公众号常把旧文**再发版**，
> 落库路径相同就会直接覆盖），**先停下来问用户**，不要自动跑。判重方法：比对 vault 里同名
> 笔记的「来源 URL / 发布日期 / 作者」，再用 difflib 归一化正文算相似度。

## 目录结构

```text
wechat-article-pipeline/
├── wechat_article_to_markdown.py    # 抓取（留在根目录，与上游路径对齐）
├── conftest.py                      # 让两套测试都能 import 到被测模块
├── scripts/
│   ├── to_obsidian.py               # 转换（纯标准库）
│   ├── sync_to_vault.py             # 落库（需 pyyaml）
│   ├── verify_wechat_md.py          # Tier-1 校验（纯标准库）
│   └── local_config.py              # ★本机专用，已 gitignore（vault 根）
├── references/
│   ├── pitfalls.md                  # 41 条踩坑记录（动手改脚本前必读）
│   ├── verify_sop.md                # 校验 SOP：两层设计 / Tier-2 升级判据
│   ├── fetch-notes.md               # 抓取器本机注意（camoufox 结论等）
│   ├── CHANGELOG-local.md           # 转换脚本的历史改动留档
│   ├── to_obsidian.local.diff       # 同上，逐条 diff
│   └── LOCAL-NOTES.md               # ★本机专用，已 gitignore
├── tests/
│   ├── test_core.py test_fetch.py       # 抓取器（pytest）
│   ├── test_e2e_live.py                 # 联网 e2e（默认跳过）
│   └── convert/                         # 转换器（unittest 风格）
└── .github/workflows/ci.yml
```

## 测试与回归

```bash
"$PY" -m pytest tests/ -q -m "not e2e"        # 全部 166 项（抓取 58 + 转换 108），无需网络
"$PY" -m pytest tests/ -q -m e2e              # 联网 e2e（需浏览器运行时）
"$PY" -m unittest discover -s tests/convert -v # 只跑转换器那 108 项（原命令习惯）
```

- 抓取器那套是 **pytest**，转换器那套是 **unittest**；`conftest.py` 已把仓库根与 `scripts/`
  插进 `sys.path`，所以 pytest 一条命令能同时收集两套。
- ⭐ **改动标题 / 推广规则的硬性回归**：除单测外，还要拿 vault 里**全部已落库成品**跑一遍，
  确认新规则零命中（假阳性回归）。更严格的做法是
  `git show HEAD:<旧脚本>` 导出旧版、新旧各跑同一批文章、两两 diff —— 这样才能把
  「本次改动的影响」与「上一批规则留下的差异」分开。只跟 vault 现存成品比是分不清的。

## 硬性约定

- 改 skill / 覆盖文件前先备份到项目内 `.workbuddy/archive/<日期>-<主题>/`。
- 本机绝对路径（vault、解释器）一律不进受版本管理的文件，只放 `local_config.py` /
  `references/LOCAL-NOTES.md`（都已 gitignore）。
- 判断两个副本有没有差异前**先排除行尾**（`diff --strip-trailing-cr`、`git ls-files --eol`）——
  本机 `core.autocrlf=true`，仓库带 `.gitattributes`（`* text=auto eol=lf`），工作区是 LF。
- 风格规则以本 skill 的脚本为准；Obsidian 语法含义查 `obsidian-markdown`。

## 出处

- **抓取器**：fork 自 [jackwener/wechat-article-to-markdown](https://github.com/jackwener/wechat-article-to-markdown)，
  本仓库在其基础上做了两级抓取重构、样式块字号分级、标题内图片解包等改造（`upstream` 仍指向它）。
- **转换 / 落库 / 校验**：自研，演化自 2026-07 起在本地项目「微信公众号知识库」中迭代的脚本。
- `scripts/sync_to_vault.py` 的 `format_frontmatter()` / `create_note()` 两个函数内联自
  skillhub.cn 的 `obsidian-direct`（作者 ruslanlanket），行为保持等价 —— 详见 `README.md`。
