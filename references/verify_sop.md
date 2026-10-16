# 抓完即校验 SOP（WeChat → Obsidian）

把「抓取 → 转换 → 落库」升级为「抓取 → 转换 → **校验** → 落库」。
校验分两层：Tier-1 每篇必跑（本地、零成本），Tier-2 按需触发（联网、对照原文）。

---

## 流程总览

```
1. 抓取   wechat_article_to_markdown.py <url>        → output/<目录名>/<目录名>.md + images/
2. 转换   scripts/to_obsidian.py                      → <目录名>.obsidian.md
3. 校验   ├─ Tier-1  scripts/verify_wechat_md.py（必跑，本地零成本）
         └─ Tier-2  WebFetch 对照原文（命中升级条件时才跑）
4. 落库   scripts/sync_to_vault.py                    → vault/公众号/<标题>/（folder=标题，只复制被引用的图）
```

> 四个环节现已合并进**同一个 skill**（`wechat-article-pipeline`），脚本同处一仓、
> **自包含**、不依赖外部写库引擎。
> 本 SOP 早期版本写的「转换用 obsidian-markdown、落库用 obsidian-direct」已过时：
> `obsidian-direct`（ClawHub）已于 2026-09-23 卸载，写库逻辑内联进 `sync_to_vault.py`。
> 抓取器 2026-09-23 起换成 jackwener/Camoufox 版（原 ClawHub `-v2` Playwright 版已删，
> `--no-playwright` 降级参数不再存在），并在其上做了两级抓取重构。

---

## Tier-1：结构体检（每篇必跑，本地零成本）

命令：

```bash
# 相对路径调用最稳（Windows/Git Bash 下 $HOME 是 /c/...，Python 打不开，见 SKILL.md 提示）
cd ~/.workbuddy/skills/wechat-article-pipeline
python3 scripts/verify_wechat_md.py "<项目根>/output/<标题>/<标题>.obsidian.md"
# 可选：--images "<自定义images目录>"   --strict（把 WARN 也当失败）
```

覆盖 7 类**不看原文就能判定**的机械缺陷：

| # | 检查项 | 命中含义 | 级别 |
|---|--------|----------|------|
| 1 | CODEBLOCK 占位符残留 | `__CODEBLOCK_i__` 未还原（skill restore 逻辑漏） | FAIL |
| 2 | 重复代码块 | 多个块内容完全相同（**灌错内容**的强信号） | FAIL |
| 3 | 空 / 截断代码块 | 块体为空或仅 1~2 字符 | FAIL |
| 4 | 代码围栏闭合 | ``` 数量为奇数，围栏没闭合 | FAIL |
| 5 | 标题-正文粘连 | 标题里混入中文句末标点后的正文句 | WARN |
| 6 | 残留远程资源 | 残留 http 图片 / `javascript:;` / CDN 链接 | WARN |
| 7 | 图片嵌入 vs 文件 | 引用了但文件缺失=FAIL；文件多于引用=仅提示 | FAIL / 提示 |

退出码：`0`=PASS/仅WARN，`2`=FAIL。可接进脚本做门禁。

**判读规则：**
- **FAIL → 必须处理**：占位符残留、重复块、空块、围栏不闭合、图片缺失。
- **WARN → 人工过目**：标题粘连（路径/版本号里的点已豁免，剩下的基本是真的）、远程残留。
- 「文件多于引用」是微信常态（二维码/头像/装饰图/分隔线），只提示不扣分。

---

## Tier-2：语义比对（按需触发，联网对照原文）

Tier-1 只能证明"结构完整"，证明不了"内容对不对"。以下三类缺陷必须对照原文才能发现，
**满足任一升级条件时执行 Tier-2**：

**升级条件（命中其一即触发）：**
1. Tier-1 报出重复块 / 空块 / 占位符残留（说明代码提取环节出过问题）。
2. 文章是**代码/命令密集型**（教程、配置、CLI 指南）——正文里代码块 ≥ 5 个。
3. 正文出现"如下图"「见下图」但对应位置是 `![[images/...]]`，怀疑**关键内容是截图**（源码/表格被渲染成图，抓不到文字）。
4. 高价值文章，要求归档质量高。

**执行步骤：**
1. `WebFetch` 拉取 `mp.weixin.qq.com` 原文作为 ground-truth。
2. 逐项 diff：① 各级标题清单 ② 每个代码块内容 ③ 段落首句 ④ 列表/表格 ⑤ 图内文字（截图型）。
3. 发现差异 → 从原文回填正确内容 → 重新 Tier-1 → 重新落库。

> 已实测的 Tier-2 战果：article 1（Skill 系统设计）7 个代码块被灌成同一个 create-skill 模板，
> Hermes 多行命令被拆行，SOUL.md 正文因源是截图而丢失——这三类都是 Tier-1 抓不到、Tier-2 才发现的。

---

## 一键批量体检

对 output/ 下所有已转换文章跑 Tier-1：

```bash
cd "<你的公众号项目根>"
# Windows(Git Bash) 需把 MSYS 路径转成 Windows 路径；其它平台没有 cygpath 时原样返回
winpath() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }
VERIFY="$(winpath "$HOME/.workbuddy/skills/wechat-article-pipeline/scripts/verify_wechat_md.py")"
for md in output/*/*.obsidian.md; do python3 "$VERIFY" "$md"; done
```

---

## 当前状态（2026-07-17 全量体检）

| 文章 | Tier-1 | 备注 |
|------|--------|------|
| AI Agent 的 Skill 系统设计 | ✅ PASS | 修复 7 重复块+1 标题粘连后复检通过 |
| 深度解读多智能体编排… | ✅ PASS | 内容本就完整，无需修复 |
| Hermes Agent 学习指南 | ✅ PASS | 前序已补 14 处 |
