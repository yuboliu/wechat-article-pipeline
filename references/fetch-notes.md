# 抓取器笔记（本机环境 / 浏览器兜底 / 上游关系）

> 面向对象：维护 `wechat_article_to_markdown.py` 的人。
> 通用用法看 `SKILL.md` 的「1. 抓取」；转换与落库的坑看 `pitfalls.md`。

## 与上游的关系

- 本仓库 fork 自 [`jackwener/wechat-article-to-markdown`](https://github.com/jackwener/wechat-article-to-markdown)。
- `origin` = 本仓库（改动推这里），`upstream` = jackwener 那个（只用来拉上游更新）。
- 抓取脚本 **刻意留在仓库根**、名字不变 —— 这样 `git merge upstream/main` 时路径不漂移，
  上游对 `wechat_article_to_markdown.py` 的改动能被 git 自动合并。
- 上游的 `main.py`、`uv.lock`、`.github/workflows/{ci,e2e,publish,release}.yml` 已清理：
  那些是给上游那套「PyPI 发包 + 独立 CI」准备的，合并后不一致也不适用。
  现在只有一套 CI（`.github/workflows/ci.yml`）跑全部单测。
  ⚠️ 因此 `git merge upstream/main` 时，**这些被删文件会反复产生「modify/delete」冲突**，
  预期之内，保留删除即可（`git rm` 或 `git checkout --ours` 后提交）。

## 两级抓取

默认 `--mode auto`：先 `requests` 直取 HTML，只有响应不是正常文章页时才升浏览器。

判定「不是正常文章页」（`detect_page_problem()`）：

- HTTP 401 / 403 / 418 / 429 / 5xx
- 缺 `#js_content`（正文容器）或 `#activity-name`（标题元素）
- 响应体异常小（< 20 000 字符）
- 命中风控特征串（`环境异常`、`完成验证后即可继续访问`、`请在微信客户端打开链接` …）

**刻意不扫正文关键词**：文章本身可能在讨论「环境异常」「访问过于频繁」，
按关键词判会把正常文章误判成风控页（已有测试覆盖）。

`unavailable`（删除 / 违规 / 过期）**不升浏览器**，直接报错 —— 重试无意义。

实测等价性：同一篇文章三条路径（`auto`→requests、`browser`+chromium、`--html-file` 离线）
产物 **md5 完全一致**；requests 模式 15/15 图、Tier-1 PASS、与 vault 成品正文逐字一致。

## 本机运行方式

本机没有全局 `wechat-article-to-markdown` 命令，直接用 skill 自带的 `.venv` 跑源码：

```bash
cd ~/.workbuddy/skills/wechat-article-pipeline
./.venv/Scripts/python.exe wechat_article_to_markdown.py "<URL>" -o "<输出根目录>"
```

## ⚠️ 本机 camoufox 不可用（2026-09-23 定位，**勿再重复试「换版本」**）

症状：浏览器进程能起，但 chrome window 初始化不完成，Juggler 15s 后抛

```
chrome://juggler/content/TargetRegistry.js:227 Error: gBrowser never populated
```

已排除（都实测过）：

- build 版本：beta.29（上一版 stable）与 beta.30 同样失败；
- playwright 版本：1.60 / 1.62 同样；
- camoufox 封装：原生通道直 launch `camoufox.exe` 同样失败；
- 沙箱、e10s、内容沙箱、WebRender、Skeleton UI prefs —— 全无效。

决定性对照：**同一 playwright 驱动官方 firefox → 1.9s PASS；Chromium → PASS**
⇒ 环境正常，问题在 camoufox 二进制侧。

⇒ **本机需要浏览器兜底时请加 `--browser-engine chromium`。**
`--browser-timeout`（默认 90s）已做硬超时，不会像旧版那样卡死。

**版本护栏（换版本前必读）**：`camoufox/__version__.py` 里
`PLAYWRIGHT_BROWSER_FLOORS = (((1,61),'beta.30'),)` —— playwright ≥1.61 时，
低于 beta.30 的 build 会被**主动拒绝**（报 "No available Camoufox build satisfies this
library's minimum"），需同时把 playwright 降到 1.60 才能用 beta.29。
降版本前先跑 `camoufox sync` 看可用 build 清单。

## 输出路径

- `<BASE>/<safe_title>/<safe_title>.md` + `images/`。
- `safe_title` = 标题里 `/ \ ? % * : | " < >` 换成 `_`、再截断 80 字符 ——
  **不替换空格和全角标点**，所以文章目录名常带空格，命令行里务必加引号。
- 落库脚本用同一套转义规则（`safe_name()`），因此 vault 文件夹名 = `output/` 目录名。
