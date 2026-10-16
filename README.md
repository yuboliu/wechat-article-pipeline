# wechat-article-pipeline

微信公众号文章 **抓取 → 转换 → 校验 → 落库** 的一体化流水线。
把一篇 `mp.weixin.qq.com` 文章变成 Obsidian 里一篇结构正确、无推广残渣、图片可用的笔记。

> 这是一个 [WorkBuddy](https://www.workbuddy.cn/) / Claude Code 等 Agent 可用 Skill
> （带 `SKILL.md`），也可以当普通 Python 脚本直接用。

本仓库由三个独立 skill 合并而来：抓取（`wechat-article-to-markdown`）、
转换 + 落库（`wechat-to-obsidian-sync`）、校验（`wechat-md-verify`）。
抓取部分 fork 自 [jackwener/wechat-article-to-markdown](https://github.com/jackwener/wechat-article-to-markdown)，
`upstream` 仍指向它。

## 它解决什么问题

微信文章的原始抓取产物有一堆固定瑕疵，逐篇手工修不现实：

- 元信息两种形态（YAML frontmatter / 正文开头的 `> 公众号: …` 引用块）；
- 文末一大段公众号推广、投稿邮箱、点赞引导、拓展阅读导航条，
  以及单行的「后台 + 私信/对话框/留言/回复 + 获取/领取/下载 + 名词」引导；
- 文首引流块（白皮书连载的「本章节节选自《X》+ 扫码 + 添加助手 + 免费获取」）；
- 章节标题在 HTML 里根本不是 `<h1-6>`，而是样式块 / 整段加粗的 `<p>`，
  层级丢失、章与节塌成同级；
- 图片语法是 `![](...)` 且常被粘在段落末尾，Obsidian 里渲染不出来；
- 标题被微信按 token 切开（`**A****B**`），加粗标记断裂；
- 中文引号半角全角混用，`\_` `\*` 反斜杠残留；
- 多篇文章的 `img_000.png` 同名，落到同一个 `images/` 会互相覆盖。

本仓库用脚本把这些**确定性**处理掉，保证同一篇重跑产出逐字节一致。

## 流水线

| 步骤 | 脚本 | 输入 → 输出 |
|------|------|-------------|
| 1 抓取 | `wechat_article_to_markdown.py` | URL → `<BASE>/<目录名>/<目录名>.md` + `images/` |
| 2 转换 | `scripts/to_obsidian.py` | `.md` → `<目录名>.obsidian.md` |
| 3 校验 | `scripts/verify_wechat_md.py` | 报告 + 退出码（`0`=PASS / `2`=FAIL），可做落库门禁 |
| 4 落库 | `scripts/sync_to_vault.py` | `vault/公众号/<标题>/<标题>.md` + 只复制被引用的图 |

推荐顺序：**抓取 → 转换 → 校验 → 落库**（高价值文章可在落库后再校验一次成品）。

## 安装

```bash
git clone https://github.com/yuboliu/wechat-article-pipeline.git \
  ~/.workbuddy/skills/wechat-article-pipeline
```

### 依赖

`requirements.txt`：

```
camoufox[geoip]      # 浏览器兜底（反检测 Firefox）
markdownify
beautifulsoup4
httpx
requests
pyyaml               # 只有落库脚本需要
```

分工：

| 脚本 | 依赖 |
|---|---|
| `wechat_article_to_markdown.py` | `httpx` `markdownify` `beautifulsoup4` `requests` `camoufox` |
| `scripts/to_obsidian.py` | **纯标准库** |
| `scripts/verify_wechat_md.py` | **纯标准库** |
| `scripts/sync_to_vault.py` | `pyyaml` |

建议用仓库自带的 venv：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv/Scripts/pip install -r requirements.txt
```

> 用系统裸 `python3` 跑**落库**那步会 `ModuleNotFoundError: No module named 'yaml'`
> （多数发行版没装 pyyaml）。转换与校验两步用任何 python3 都能跑。

### Python 版本

`>= 3.9`（CI 覆盖 3.9 与 3.12）。

## 使用

设 `BASE` 为输出根目录，`D` 为文章目录名（`output/` 下的子目录名，
**常与文章标题不同**，且可能带空格，命令里务必加引号）。

```bash
cd ~/.workbuddy/skills/wechat-article-pipeline     # 进仓库目录，用「相对路径」调用：跨平台最稳
PY=".venv/Scripts/python.exe"                      # Unix/macOS: .venv/bin/python
BASE="<输出根目录>"

# 1) 抓取（默认两级：requests 直取，命中风控才自动升浏览器）
"$PY" wechat_article_to_markdown.py "<URL>" -o "$BASE"
#    只想走最快的非浏览器模式
"$PY" wechat_article_to_markdown.py "<URL>" -o "$BASE" --mode requests

# 2) 转换（--tags 必给，否则 frontmatter 与文末标签为空）
D="<文章目录名>"
"$PY" scripts/to_obsidian.py "$D" --base "$BASE" --tags 标签1 标签2 --date 2026-09-23

# 3) 校验（FAIL 就别落库）
"$PY" scripts/verify_wechat_md.py "$BASE/$D/$D.obsidian.md"

# 4) 落库
"$PY" scripts/sync_to_vault.py "$D" --base "$BASE"
#    落点 vault/<subfolder>/<标题>/<标题>.md：
#    --subfolder 改中间那级（默认「公众号」）、--folder 直接指定最终子目录
```

### 抓取参数

| 参数 | 说明 |
|---|---|
| `--mode auto`（默认）/ `requests` / `browser` | 两级 / 只用 requests（最快、省内存）/ 只用浏览器 |
| `--browser-engine camoufox\|chromium` | 浏览器兜底引擎（默认 camoufox） |
| `--browser-timeout` | 浏览器模式整体硬超时（默认 90s），防引擎卡死时无限等待 |
| `--cookie "k=v; k2=v2"` / `--proxy URL` | 受限文章 / 走代理 |
| `--timeout` / `--retries` | requests 超时与重试（默认 30s / 3 次） |
| `--save-html raw.html` | 存下原始 HTML，便于离线复跑 / 排查风控 |
| `--html-file raw.html` | 直接解析本地 HTML，完全不发网络请求 |

两种模式的 Markdown **逐字节一致**，下游零改动。

### 配置 vault 路径

vault 根 = 装有 `.obsidian` 的目录。你自己的 vault 路径不该进版本库，按优先级取：

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | 环境变量 `WECHAT_VAULT` | 临时切换 / CI |
| 2 | `scripts/local_config.py` | **推荐**，本机专用，已 gitignore |
| 3 | `~/iNote` | 中性默认 |

```python
# scripts/local_config.py —— 本机专用，不要提交
DEFAULT_VAULT = r"D:\MyVault"
```

改 vault 时**只改这个文件**，不要把绝对路径写回 `sync_to_vault.py`
（否则 `git pull` 次次冲突，push 还会把本机路径公开出去）。

## 测试

```bash
python -m pytest tests/ -q -m "not e2e"          # 166 项（抓取 58 + 转换 108），无需网络
python -m pytest tests/ -q -m e2e                # 联网 e2e（需浏览器运行时）
python -m unittest discover -s tests/convert -v  # 只跑转换器那 108 项
```

抓取器那套是 pytest，转换器那套是 unittest；根目录的 `conftest.py` 已把仓库根与
`scripts/` 插进 `sys.path`，所以 pytest 一条命令能同时收集两套。

CI（`.github/workflows/ci.yml`）在 Python 3.9 / 3.12 上跑 `-m "not e2e"` 的全部用例。

## 做了哪些优化

### 抓取器（相对上游 jackwener 版）

1. **两级抓取 + 自动降级**：默认先用 `requests` 直取 HTML（公众号正文是服务端渲染的，
   这条路拿得到完整内容，比开浏览器快一个数量级、不吃内存），只有响应不是正常文章页时
   才升浏览器。上游是「一律开浏览器」。
2. **风控判定刻意不扫正文关键词**：只看 HTTP 状态码、缺 `#js_content`/`#activity-name`、
   响应体异常小、风控特征串。否则一篇**讨论**「环境异常」的文章会被误判成风控页。
3. **失效文章不升浏览器**：删除 / 违规 / 过期直接报错，省一次无意义的浏览器启动。
4. **样式块标题按字号分级**：作者用 17px（章）/ 16px（节）两级时按字号给出 `##` / `###`；
   单字号文章照旧全 `##`。旧版把两级一律压成 `##`，会把章与它下面的子节塌成同级。
5. **「整段加粗 + 编号」的 `<p>` 识别为标题**（`1` / `1.1` / `1.2.1` → `##`/`###`/`####`）。
   上游只认 `<section>` 样式块，这类文章整篇只有 H1、一个 `##` 都没有。
6. **标题里裹着图片时拆成段落**：markdownify 的 `<hN>` 转换只保留图片 alt 文字，
   `<h3><img/></h3>` 会变成 `### 图片` —— 图**丢了**还多一个假标题。图片不可能是标题内容，
   转换前先拆成 `<p>`。
7. **段落行首缩进去除**：作者用一串 `&nbsp;` 做中文首行缩进，清洗后会变成 4 空格开头，
   Markdown 判成**缩进代码块**（Obsidian 里渲染成灰底等宽块）。只对普通正文行去缩进，
   列表续行 / 引用 / 表格 / 围栏内代码不受影响。
8. **`--save-html` / `--html-file` 离线复跑**：抓一次存原始 HTML，之后完全不出网也能重跑，
   便于排查风控页与对比规则改动的影响。

### 转换（`scripts/to_obsidian.py`）

9. **文末推广截断有五条正交规则**，取命中位置**更靠前**的那个：
   末尾 `---` 分隔线；文末标记行（关注公众号 / 扫描·长按二维码 / 推荐阅读 / 添加微信 /
   下载 APP / 原题：/ 作者·编辑署名 / 点击…阅读原文 / 本公众号所发布内容 / 点赞、转发 …）；
   `**END**` 结束标记（可挂结尾装饰图）；**历史文章导航区**（研报类文章末尾
   `**XX系列：**` + 200 条自家链接，篇幅可超过正文，靠「≥8 条连续 mp 链接」的**结构判据**
   识别而非比例阈值）。
   ⚠️ 比例闸（尾巴 ≤33% / 60%）**故意保留**：白皮书类文章**开头**的「扫描下方二维码」
   占比可达 96%，去掉比例闸会把整篇腰斩。
10. **文首引流块截断**（白皮书连载的「节选自《X》+ 扫码 + 添加助手 + 免费获取」），
    三个闸：起点在全文前 25% 内、块内 ≥2 个引流标记行、块内必须有索取诉求。
11. **文首重复标题 banner 删除**（题图 + 与 H1 等价的加粗标题，微信常拆成两行），
    否则会被提成 `## 网络原来如此之` 这种假标题；banner 尾巴上的纯装饰强调行
    （`***DeepSeek***`）也一并吃掉 —— 它留下的假标题会把后续小标题整体压深一级。
12. **假标题降级**：作者把摘要/导语也套了标题样式（HTML 里就是真 `<h3>`、内层 15px 没加粗）
    时，「像段落的标题」（空 / 是 `图片` / > 40 字 / 含 `。` / 以句末标点收尾）降回段落。
13. **正文标题层级基准归一**：把正文里最浅的一级拉成 `##`（`#` 只留给文章标题）——
    作者粘 Word 的 `<h1>/<h2>` 会偏浅、粘 `<h3>/<h4>` 会偏深，同一条规则两个方向都覆盖。
14. **按编号重建多级标题**（`1`→`##`、`1.1`→`###`、`1.2.1`→`####`，幂等），并处理这些坑：
    - 「编号 + 点号 + 紧跟非空白」的加粗行（`**3.可视化展示**`）和**括号编号**
      （`**（1）朴素 RAG…**`）都是**列表项**，不提升为标题；
    - 标题行**整行被加粗**（`## **1. 引言**`）时先拆掉 `**` 再判编号，否则编号认不出来、
      整篇层级重建**静默失效**；
    - `1.` 这种单级点号是章还是节，看**全文有没有两级点号**（`1.1`）：有 ⇒ 章（`##`），
      没有 ⇒ 跟着无编号大章的节（`###`）；
    - **一位数章号体系**：`**01**`+`**名称**` 在一篇里是章、在另一篇里是节，
      由「全文有没有一位数章号（`**1**`）」决定。
15. **折叠「空章标题」**：大节标题后面一个字不写、直接进子节时，把子节整体降一级
    （判据是「该标题与下一个标题之间没有任何正文行」）；后面紧跟**带编号**小节则不折。
    折叠量按**差值**算而非无条件 +1。
16. **中文引号按行成对交替归一化**为 `“ ”`；`\_` `\**` 反斜杠还原但**不动** `C:\Users`
    这类合法路径；加粗标记断裂合并（`**A****B**` → `**AB**`）；目录块从被挤成的一行
    重排为按编号缩进的嵌套列表。

### 落库（`scripts/sync_to_vault.py`）

17. **每篇一个带标题的子文件夹**，否则多篇的 `img_000.png` 会互相覆盖。
18. **只复制正文真正引用的图片**（推广图 / 二维码留在 `output/` 不落库），
    并在开跑前校验 vault 存在且其下有 `.obsidian`。
19. **本机路径与代码彻底分离**：vault 根走「环境变量 → `local_config.py` → 中性默认」
    三级解析，受版本管理的文件里没有任何本机绝对路径 —— 于是**一台机器只需要一份副本**。

### 校验（`scripts/verify_wechat_md.py`）

20. **Tier-1 七项确定性体检**（占位符残留 / 重复代码块 / 空块 / 围栏闭合 / 标题-正文粘连 /
    残留远程资源 / 图片嵌入与文件对账），纯本地、零网络、零第三方依赖，**退出码可做门禁**
    （`0`=PASS、`2`=FAIL，FAIL 时禁止落库）。
21. Tier-1 只证明「结构完整」；需要证明「内容对不对」时按 `references/verify_sop.md`
    升级 Tier-2（联网拉原文逐项 diff）。

### 工程

22. **166 项单测**（抓取 58 + 转换 108），全部离线可跑；CI 覆盖 Python 3.9 / 3.12。
23. **假阳性回归方法论**：改标题 / 推广规则后，除单测外还要拿 vault 里**全部已落库成品**
    跑一遍确认零命中；更严格的做法是用 `git show HEAD:<旧脚本>` 导出旧版，
    新旧各跑同一批文章两两 diff，把「本次改动的影响」与「上一批规则留下的差异」彻底分开。
    （`references/pitfalls.md` 的 41 条记录大多就是这么发现并定位的。）

## 目录结构

```text
wechat-article-pipeline/
├── SKILL.md                         # Agent 用的 skill 定义（工作流 + 触发词）
├── README.md
├── wechat_article_to_markdown.py    # 抓取（留在根目录，与上游路径对齐）
├── conftest.py                      # 统一两套测试的 import 路径
├── pyproject.toml / requirements.txt
├── scripts/
│   ├── to_obsidian.py               # 转换（纯标准库）
│   ├── sync_to_vault.py             # 落库（需 pyyaml）
│   ├── verify_wechat_md.py          # Tier-1 校验（纯标准库）
│   └── local_config.py              # ★本机专用，已 gitignore
├── references/
│   ├── pitfalls.md                  # 41 条踩坑记录（改脚本前必读）
│   ├── verify_sop.md                # 校验 SOP：两层设计 / Tier-2 升级判据
│   ├── fetch-notes.md               # 抓取器：上游关系 / 本机 camoufox 结论
│   ├── CHANGELOG-local.md           # 转换脚本的历史改动留档
│   ├── to_obsidian.local.diff
│   └── LOCAL-NOTES.md               # ★本机专用，已 gitignore
├── tests/
│   ├── test_core.py test_fetch.py   # 抓取器（pytest，58 项）
│   ├── test_e2e_live.py             # 联网 e2e（默认跳过）
│   └── convert/                     # 转换器（unittest，108 项）
└── .github/workflows/ci.yml
```

## 作为 Agent Skill 使用

仓库自带 `SKILL.md`，支持 `.agents/skills/` 约定或各 Agent 的 skills 目录
（如 WorkBuddy 的 `~/.workbuddy/skills/`、Claude Code 的 `~/.claude/skills/`）：
把本仓库 clone 成一个 skill 目录即可，Agent 会按 `SKILL.md` 里的流水线调用脚本。

## 出处与致谢

- **抓取器**：fork 自 [jackwener/wechat-article-to-markdown](https://github.com/jackwener/wechat-article-to-markdown)
  （MIT），保留 `upstream` 关系以便继续跟上游更新。
- **转换 / 落库 / 校验**：自研，演化自 2026-07 起在本地项目「微信公众号知识库」中迭代的脚本，
  2026-09-23 固化为 skill，2026-10-16 三合一。
- **唯一的外部内联代码**：`scripts/sync_to_vault.py` 的 `format_frontmatter()` 与
  `create_note()` 两个函数内联自 [obsidian-direct](https://api.skillhub.cn/ruslanlanket/obsidian-direct)
  （作者 **ruslanlanket**，发布于 skillhub.cn）的 `scripts/obsidian_cli.py`，行为保持等价。
  该 skill 已从本机卸载，本仓库保留内联实现以去掉运行时依赖。
  **本仓库未能确认 obsidian-direct 的明确开源许可证；若原作者对此有异议，请联系删除相关部分。**

## License

除上述内联部分（权利归原作者）与 fork 自上游的部分（遵循上游 MIT，
版权归 jackwener）外，本项目采用 MIT。
