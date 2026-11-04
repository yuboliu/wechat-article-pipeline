# -*- coding: utf-8 -*-
"""配置解析中心 —— 所有「每台机器不一样」的值都走这里。

设计目标
--------
1. **仓库可以直接公开**：受版本管理的文件里永远不出现本机绝对路径。
   真实的 vault 路径只活在 `.env`（已 gitignore）与 `.env.example`（纯占位符）之间。
2. **零依赖**：只解析最简单的一层 KEY=VALUE，不引入 python-dotenv。
   （venv 里没装它；为了一个配置文件再拉依赖，会让 `pip install -r` 变重。）
3. **优先级明确且可解释**：命令行 > 真实环境变量 > .env > 兼容层 local_config.py > 报错。
   真实环境变量排在 .env 之前，是为了让 CI / 临时覆盖（`WECHAT_VAULT=x python …`）能生效。

支持的 .env 语法（刻意保持最小集）
---------------------------------
    # 注释
    KEY=value
    export KEY=value
    KEY="带空格或 # 的值"
    KEY='单引号不展开变量'
    KEY=~/vaults/iNote          # 支持 ~ 展开
    KEY=${HOME}/vaults/iNote    # 支持 ${VAR} 引用已解析的值

不支持的：多行值、\n 转义、嵌套引用 —— 出现这些就说明该换格式了，别在这里硬撑。

用法
----
    import env_config
    env_config.load_env()                       # 幂等，可重复调用
    vault = env_config.resolve_vault()           # 未配置时给出可操作的报错
    sub   = env_config.resolve_subfolder()       # 支持 *公众号 这类通配
    idx   = env_config.resolve_index_pattern()
"""
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
#: 键名 → 说明。集中在一处，方便 setup_env.py / doctor() / 文档三边保持一致。
KEYS = {
    "WECHAT_VAULT": "Obsidian vault 根目录（那个装有 .obsidian 的目录）",
    "WECHAT_SUBFOLDER": "落库的一级目录名，写死名字时用（优先级高于通配）",
    "WECHAT_SUBFOLDER_PATTERN": "落库一级目录的通配模式，默认 *公众号",
    "WECHAT_INDEX_PATTERN": "索引页文件名通配，默认 *知识库索引*.md",
    "WECHAT_OUTPUT_BASE": "抓取/转换产物根目录，默认 <当前目录>/output",
    "WECHAT_PYTHON": "本机解释器路径（仅文档用途，脚本不读）",
    "WECHAT_TAXONOMY": "标签词表路径，默认 references/taxonomy.json",
    "WECHAT_INDEX_LAYOUT": "索引布局路径，默认 references/index_layout.json",
}

#: 落库一级目录的兜底名（vault 里通常叫「公众号」）
DEFAULT_SUBFOLDER = "公众号"
DEFAULT_SUBFOLDER_PATTERN = "*公众号"
DEFAULT_INDEX_PATTERN = "*知识库索引*.md"

_ENTRY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_loaded = None          # 已加载的 dict（load_env 的缓存）
_loaded_from = None     # 实际读到的 .env 路径，便于 doctor 打印


# ---------------------------------------------------------------------------
# 定位与解析
# ---------------------------------------------------------------------------
def repo_root() -> Path:
    """仓库根目录（本文件在 <root>/scripts/ 下）。"""
    return Path(__file__).resolve().parent.parent


def env_file_path() -> Path:
    """.env 的位置。

    优先级：`WECHAT_ENV_FILE` 环境变量 → 仓库根 `.env`。
    固定用「脚本所在仓库根」而不是 cwd —— 否则在 vault 目录里跑脚本就会找不到配置，
    这是最难排查的一类「明明配了却不生效」。
    """
    explicit = os.environ.get("WECHAT_ENV_FILE")
    if explicit:
        return Path(explicit).expanduser()
    return repo_root() / ".env"


def _expand(value: str, environ=None) -> str:
    """展开 ${VAR} 与 ~。未定义的变量保持原样，避免静默变成空串。

    `environ` 显式传入是为了让 parse_env_text 能用「给定的上下文」而不是进程环境 ——
    否则单测里传 base_env 就不生效，而且解析顺序会变成「谁先写 os.environ 谁赢」。
    """
    env = os.environ if environ is None else environ

    def sub(m):
        return env.get(m.group(1), m.group(0))
    value = _VAR_RE.sub(sub, value)
    if value.startswith("~"):
        value = os.path.expanduser(value)
    return value


def parse_env_text(text: str, base_env=None) -> dict:
    """把 .env 文本解析成 dict。纯函数，方便单测。

    注意：**不做任何覆盖判断**，只管解析；覆盖策略在 load_env() 里。
    """
    # 去掉 UTF-8 BOM：Windows 记事本 / PowerShell 5 的 Out-File 都会写，
    # 留着会让第一行的 KEY 认不出来（症状极隐蔽：只有第一项失效）。
    if text.startswith("\ufeff"):
        text = text[1:]
    base = dict(os.environ) if base_env is None else dict(base_env)
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENTRY_RE.match(raw)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()

        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            quote, val = val[0], val[1:-1]
            if quote == '"':
                # 双引号里允许 ${VAR} 与 ~ 展开；单引号严格字面量
                val = _expand(val, base)
        else:
            # 未加引号：去掉「空白 + #」起的行内注释。
            # 只在 # 前有空白时才切，这样 #tag、a#b 这类值不会被误伤。
            cut = re.search(r"\s+#", val)
            if cut:
                val = val[:cut.start()].rstrip()
            val = _expand(val, base)

        out[key] = val
        base[key] = val
    return out


def load_env(path=None, override=False) -> dict:
    """读取 .env 并写入 os.environ。幂等，可重复调用。

    override=False（默认）时**不覆盖**已存在的环境变量 —— 这样
    `WECHAT_VAULT=/tmp/x python sync_to_vault.py` 这种临时覆盖永远有效。
    """
    global _loaded, _loaded_from
    p = Path(path) if path else env_file_path()
    if not p.is_file():
        _loaded, _loaded_from = {}, None
        return {}
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    values = parse_env_text(text)
    for k, v in values.items():
        if override or k not in os.environ:
            os.environ[k] = v
    _loaded, _loaded_from = values, p
    return values


def get(key, default=None):
    """读一个配置键。os.environ 优先（含 .env 已注入的值）。"""
    if _loaded is None:
        load_env()
    val = os.environ.get(key)
    if val is None or val == "":
        return default
    return val


def is_configured() -> bool:
    """是否已经配好 vault（判断「新机器首次使用」的唯一依据）。"""
    return bool(get("WECHAT_VAULT"))


# ---------------------------------------------------------------------------
# 兼容层：老的 scripts/local_config.py（已降级，仍可用）
# ---------------------------------------------------------------------------
def _legacy_local_config():
    """可选导入旧的 local_config.py。读不到就返回 None，绝不让它成为必需依赖。"""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import local_config  # noqa: F401
        return local_config
    except Exception:
        return None


def _legacy_value(name):
    cfg = _legacy_local_config()
    if cfg is None:
        return None
    val = getattr(cfg, name, None)
    return str(val) if val else None


# ---------------------------------------------------------------------------
# 各配置项的解析链
# ---------------------------------------------------------------------------
MISSING_VAULT_HELP = """\
未配置 vault 路径 —— 这是唯一必须手工填的一项。

任选一种：
  1. 跑配置向导（推荐，会校验目录并生成 .env）：
       "{py}" scripts/setup_env.py
  2. 手工创建 .env（模板见 .env.example，该文件可提交、.env 不会）：
       WECHAT_VAULT=/你的/vault/根目录
  3. 临时覆盖，不落盘：
       WECHAT_VAULT=/你的/vault "{py}" scripts/sync_to_vault.py "文章目录名"
"""


def _python_hint():
    return sys.executable or "python"


def resolve_vault(cli=None, required=True, interactive=None) -> str:
    """解析 vault 根（装有 .obsidian 的目录）。

    解析顺序：
      1. 命令行 `--vault`
      2. 环境变量 / .env 的 `WECHAT_VAULT`
      3. 兼容层 `local_config.DEFAULT_VAULT`（老机器，已弃用）
      4. 交互询问（仅当 stdin 是终端且 required=True）
      5. 抛 SystemExit，附带可操作的三条指引
    """
    if cli:
        return cli

    val = get("WECHAT_VAULT")
    if val:
        return val

    legacy = _legacy_value("DEFAULT_VAULT")
    if legacy:
        print("  WARN: 正在使用已弃用的 scripts/local_config.py，"
              "建议迁移到 .env（跑 scripts/setup_env.py）", file=sys.stderr)
        return legacy

    if not required:
        return ""

    if interactive is None:
        interactive = sys.stdin is not None and sys.stdin.isatty()
    if interactive:
        got = _ask_vault()
        if got:
            return got

    raise SystemExit(MISSING_VAULT_HELP.format(py=_python_hint()))


def _ask_vault():
    """交互式询问 vault 路径，顺带校验。用户直接回车则返回空串。"""
    print("\n未找到 .env 配置。请输入你的 Obsidian vault 根目录")
    print("（即那个里面有 .obsidian 文件夹的目录，直接回车跳过）：")
    try:
        raw = input("vault 路径 > ").strip().strip('"').strip("'")
    except (EOFError, KeyboardInterrupt):
        print()
        return ""
    if not raw:
        return ""
    p = Path(os.path.expanduser(raw))
    if not p.is_dir():
        print("  ! 目录不存在：%s" % p, file=sys.stderr)
        return ""
    if not (p / ".obsidian").is_dir():
        print("  ! 目录下没有 .obsidian，可能不是 vault 根（仍会使用）", file=sys.stderr)
    print("  提示：把它写进 .env 可以免去每次输入 —— 跑 scripts/setup_env.py")
    return str(p)


def resolve_subfolder(cli=None) -> str:
    """解析落库的一级目录名。

    目录会加编号前缀、会整体搬家（`公众号` → `【15】公众号` 真实发生过），
    所以配置项是**通配模式**，运行期 glob 唯一候选：

      1. 命令行 `--subfolder`
      2. `WECHAT_SUBFOLDER`（写死名字，优先级高于通配）
      3. `WECHAT_SUBFOLDER_PATTERN` / 兼容层 SUBFOLDER_PATTERN → glob 唯一命中
      4. 字面量「公众号」

    多个候选直接报错 —— 写错目录比报错更难发现。
    """
    if cli:
        return cli

    literal = get("WECHAT_SUBFOLDER")
    if literal:
        return literal

    pattern = (get("WECHAT_SUBFOLDER_PATTERN")
               or _legacy_value("SUBFOLDER_PATTERN")
               or DEFAULT_SUBFOLDER_PATTERN)

    vault = Path(resolve_vault(required=False) or "")
    if not vault.is_dir():
        return DEFAULT_SUBFOLDER

    hits = sorted(p for p in vault.glob(pattern) if p.is_dir())
    if len(hits) == 1:
        return hits[0].name
    if len(hits) > 1:
        raise SystemExit(
            "落库目录有歧义：vault 下匹配 %s 的有 %d 个 → %s\n"
            "请用 --subfolder 指定，或在 .env 里把 WECHAT_SUBFOLDER 写成具体目录名"
            % (pattern, len(hits), ", ".join(h.name for h in hits)))
    print("  WARN: vault 下没有匹配 %s 的目录，回落为「%s」"
          % (pattern, DEFAULT_SUBFOLDER))
    return DEFAULT_SUBFOLDER


def resolve_index_pattern(cli=None) -> str:
    """索引页文件名通配。索引改名也不用动代码。"""
    return (cli or get("WECHAT_INDEX_PATTERN")
            or _legacy_value("INDEX_PATTERN") or DEFAULT_INDEX_PATTERN)


def resolve_output_base(cli=None) -> str:
    """抓取/转换产物根目录。默认跟随当前工作目录，不写死任何绝对路径。"""
    if cli:
        return cli
    val = get("WECHAT_OUTPUT_BASE")
    if val:
        return val
    return str(Path.cwd() / "output")


def resolve_taxonomy(cli=None) -> str:
    return cli or get("WECHAT_TAXONOMY") or str(repo_root() / "references" / "taxonomy.json")


def resolve_index_layout(cli=None) -> str:
    return (cli or get("WECHAT_INDEX_LAYOUT")
            or str(repo_root() / "references" / "index_layout.json"))


# ---------------------------------------------------------------------------
# 体检
# ---------------------------------------------------------------------------
def doctor(verbose=True) -> int:
    """打印当前配置的解析结果。**输出里故意不打印 vault 全路径**，
    只打印是否配置、是否合法 —— 这样把体检结果贴给别人也不会泄漏路径。"""
    load_env()
    ok = True
    p = _loaded_from
    if verbose:
        print("配置文件 : %s" % (p if p else "未找到（%s 不存在）" % env_file_path()))

    if not is_configured():
        if verbose:
            print("状态     : 未配置 —— 需要填 WECHAT_VAULT")
            print(MISSING_VAULT_HELP.format(py=_python_hint()))
        return 2

    vault = Path(get("WECHAT_VAULT")).expanduser()
    is_dir = vault.is_dir()
    has_obs = (vault / ".obsidian").is_dir()
    if not is_dir:
        ok = False
    if verbose:
        print("vault    : %s（%s）" % ("已配置", "存在" if is_dir else "!! 目录不存在"))
        print("           .obsidian: %s" % ("有" if has_obs else "!! 没有"))
        if is_dir:
            pat = get("WECHAT_SUBFOLDER_PATTERN") or DEFAULT_SUBFOLDER_PATTERN
            hits = sorted(x.name for x in vault.glob(pat) if x.is_dir())
            print("           落库目录 pattern=%s → %s"
                  % (pat, ", ".join(hits) if hits else "无命中（将回落「%s」）" % DEFAULT_SUBFOLDER))
            ipat = resolve_index_pattern()
            idx = sorted(x.name for x in vault.glob(ipat))
            print("           索引页 pattern=%s → %s"
                  % (ipat, ", ".join(idx) if idx else "无命中"))
        print("   提示：这里不打印完整路径，避免体检输出顺手泄漏给别人")
    return 0 if ok and has_obs else 1


if __name__ == "__main__":
    raise SystemExit(doctor())
