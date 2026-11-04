# -*- coding: utf-8 -*-
"""配置层（env_config / setup_env）测试。

重点不是「能读到值」，而是三条容易出错的性质：

1. **优先级**：命令行 > 真实环境变量 > .env —— CI 与临时覆盖依赖这条；
2. **不覆盖**：.env 不能悄悄盖掉用户已经 export 的变量；
3. **缺失时可操作**：没配 vault 时必须报错并给出三条具体指引，
   而不是退回一个 `~/iNote` 这种「看起来能跑、实际写错地方」的默认值。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts"))
import env_config  # noqa: E402


class IsolateEnvMixin:
    """把环境变量与 env_config 的模块级缓存都清干净。

    env_config 会把 .env 注入 os.environ，测试之间不隔离就会互相污染 ——
    真实 .env 里的 vault 路径会让「未配置」用例假通过。
    """

    def setUp(self):
        self._saved = dict(os.environ)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        for k in list(os.environ):
            if k.startswith("WECHAT_") or k == "HOME":
                del os.environ[k]
        # 指向一个不存在的 .env，避免读到开发者本机的真实配置
        os.environ["WECHAT_ENV_FILE"] = str(self.tmp / "no-such.env")
        env_config._loaded = None
        env_config._loaded_from = None

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)
        env_config._loaded = None
        env_config._loaded_from = None
        self._tmp.cleanup()


class TestParseEnvText(unittest.TestCase):
    """纯解析：不碰文件系统、不碰 os.environ。"""

    def test_basic_and_comments(self):
        got = env_config.parse_env_text(
            "# 注释\n\nKEY=value\nOTHER = spaced \n")
        self.assertEqual(got["KEY"], "value")
        self.assertEqual(got["OTHER"], "spaced")

    def test_export_prefix(self):
        self.assertEqual(env_config.parse_env_text("export KEY=v\n")["KEY"], "v")

    def test_double_quote_keeps_hash(self):
        got = env_config.parse_env_text('KEY="a #b c"\n')
        self.assertEqual(got["KEY"], "a #b c")

    def test_single_quote_is_literal(self):
        # 单引号不展开 ${VAR}：这是给人放正则/特殊字符用的
        got = env_config.parse_env_text("KEY='${HOME}/x'\n")
        self.assertEqual(got["KEY"], "${HOME}/x")

    def test_inline_comment_only_after_space(self):
        # 「空白 + #」才算注释；`a#b` 不是
        self.assertEqual(env_config.parse_env_text("A=v # note\n")["A"], "v")
        self.assertEqual(env_config.parse_env_text("B=a#b\n")["B"], "a#b")

    def test_var_expansion(self):
        got = env_config.parse_env_text('P="${BASE}/vault"\n', base_env={"BASE": "/data"})
        self.assertEqual(got["P"], "/data/vault")

    def test_undefined_var_kept_as_is(self):
        # 未定义变量保持原样，避免静默变成空串把路径吃掉
        got = env_config.parse_env_text('P="${NOPE}/vault"\n', base_env={})
        self.assertEqual(got["P"], "${NOPE}/vault")

    def test_tilde_expansion(self):
        got = env_config.parse_env_text("P=~/vaults\n", base_env={"HOME": "/home/u"})
        self.assertEqual(got["P"], os.path.expanduser("~/vaults"))

    def test_ignores_malformed_lines(self):
        got = env_config.parse_env_text("这不是配置\n=novalue\nKEY=ok\n")
        self.assertEqual(got, {"KEY": "ok"})

    def test_strips_bom(self):
        got = env_config.parse_env_text("\ufeffKEY=v\n")
        self.assertEqual(got.get("KEY"), "v")


class TestLoadEnv(IsolateEnvMixin, unittest.TestCase):

    def test_missing_file_returns_empty(self):
        self.assertEqual(env_config.load_env(), {})
        self.assertFalse(env_config.is_configured())

    def test_loads_and_injects(self):
        p = self.tmp / ".env"
        p.write_text("WECHAT_VAULT=/v\nOTHER=1\n", encoding="utf-8")
        self.assertEqual(env_config.load_env(path=p)["WECHAT_VAULT"], "/v")
        self.assertEqual(os.environ["WECHAT_VAULT"], "/v")

    def test_does_not_override_existing_env(self):
        """真实环境变量优先 —— 否则 `WECHAT_VAULT=x python …` 会失效。"""
        os.environ["WECHAT_VAULT"] = "/from-env"
        p = self.tmp / ".env"
        p.write_text("WECHAT_VAULT=/from-file\n", encoding="utf-8")
        env_config.load_env(path=p)
        self.assertEqual(os.environ["WECHAT_VAULT"], "/from-env")
        self.assertEqual(env_config.resolve_vault(), "/from-env")

    def test_override_true_wins(self):
        os.environ["WECHAT_VAULT"] = "/from-env"
        p = self.tmp / ".env"
        p.write_text("WECHAT_VAULT=/from-file\n", encoding="utf-8")
        env_config.load_env(path=p, override=True)
        self.assertEqual(os.environ["WECHAT_VAULT"], "/from-file")

    def test_env_file_env_var_is_honoured(self):
        p = self.tmp / "custom.env"
        p.write_text("WECHAT_VAULT=/custom\n", encoding="utf-8")
        os.environ["WECHAT_ENV_FILE"] = str(p)
        self.assertEqual(env_config.env_file_path(), p)
        env_config.load_env()
        self.assertEqual(env_config.resolve_vault(), "/custom")

    def test_repo_root_located_by_file_not_cwd(self):
        """cwd 换到别处也要能找到仓库根的 .env（否则「明明配了却不生效」）。"""
        del os.environ["WECHAT_ENV_FILE"]      # 恢复默认定位规则
        self.assertEqual(env_config.env_file_path().parent, env_config.repo_root())
        self.assertTrue((env_config.repo_root() / "scripts" / "env_config.py").is_file())


class TestResolveVault(IsolateEnvMixin, unittest.TestCase):

    def test_cli_wins(self):
        os.environ["WECHAT_VAULT"] = "/from-env"
        self.assertEqual(env_config.resolve_vault(cli="/cli"), "/cli")

    def test_missing_raises_with_actionable_help(self):
        with self.assertRaises(SystemExit) as cm:
            env_config.resolve_vault()
        msg = str(cm.exception.code)
        self.assertIn("setup_env.py", msg)        # 指引 1
        self.assertIn(".env.example", msg)        # 指引 2
        self.assertIn("WECHAT_VAULT", msg)        # 指引 3

    def test_non_interactive_does_not_prompt(self):
        # 测试环境 stdin 非 tty；显式 interactive=False 时绝不能去 input()
        with self.assertRaises(SystemExit):
            env_config.resolve_vault(interactive=False)

    def test_required_false_returns_empty(self):
        self.assertEqual(env_config.resolve_vault(required=False), "")

    def test_is_configured(self):
        self.assertFalse(env_config.is_configured())
        os.environ["WECHAT_VAULT"] = "/v"
        self.assertTrue(env_config.is_configured())


class TestResolveSubfolder(IsolateEnvMixin, unittest.TestCase):
    """落库目录用通配解析 —— vault 会改名、加编号前缀。"""

    def _vault(self, *dirs):
        v = self.tmp / "vault"
        v.mkdir(exist_ok=True)
        (v / ".obsidian").mkdir(exist_ok=True)
        for d in dirs:
            (v / d).mkdir(exist_ok=True)
        os.environ["WECHAT_VAULT"] = str(v)
        return v

    def test_cli_wins(self):
        self.assertEqual(env_config.resolve_subfolder(cli="X"), "X")

    def test_literal_beats_pattern(self):
        self._vault("【15】公众号")
        os.environ["WECHAT_SUBFOLDER"] = "固定名"
        self.assertEqual(env_config.resolve_subfolder(), "固定名")

    def test_pattern_matches_numbered_dir(self):
        self._vault("【15】公众号", "会议纪要")
        self.assertEqual(env_config.resolve_subfolder(), "【15】公众号")

    def test_pattern_no_hit_falls_back(self):
        self._vault("会议纪要")
        self.assertEqual(env_config.resolve_subfolder(), env_config.DEFAULT_SUBFOLDER)

    def test_ambiguous_pattern_errors(self):
        self._vault("公众号", "【15】公众号")
        with self.assertRaises(SystemExit) as cm:
            env_config.resolve_subfolder()
        self.assertIn("歧义", str(cm.exception.code))

    def test_no_vault_returns_default(self):
        self.assertEqual(env_config.resolve_subfolder(), env_config.DEFAULT_SUBFOLDER)


class TestResolvePaths(IsolateEnvMixin, unittest.TestCase):

    def test_output_base_default_is_cwd_output(self):
        self.assertEqual(env_config.resolve_output_base(),
                         str(Path.cwd() / "output"))

    def test_output_base_from_env_file(self):
        p = self.tmp / ".env"
        p.write_text("WECHAT_OUTPUT_BASE=/out\n", encoding="utf-8")
        env_config.load_env(path=p)
        self.assertEqual(env_config.resolve_output_base(), "/out")

    def test_taxonomy_and_layout_default_inside_repo(self):
        # 默认值必须落在仓库内，不能是个人目录
        self.assertTrue(env_config.resolve_taxonomy().endswith("references/taxonomy.json")
                        or env_config.resolve_taxonomy().endswith("references\\taxonomy.json"))
        self.assertIn("references", env_config.resolve_index_layout())

    def test_index_pattern_default(self):
        self.assertEqual(env_config.resolve_index_pattern(),
                         env_config.DEFAULT_INDEX_PATTERN)


class TestDoctor(IsolateEnvMixin, unittest.TestCase):

    def test_unconfigured_returns_2(self):
        self.assertEqual(env_config.doctor(verbose=False), 2)

    def test_configured_ok_returns_0(self):
        v = self.tmp / "vault"
        (v / ".obsidian").mkdir(parents=True)
        os.environ["WECHAT_VAULT"] = str(v)
        self.assertEqual(env_config.doctor(verbose=False), 0)

    def test_missing_dotobsidian_returns_1(self):
        v = self.tmp / "vault"
        v.mkdir()
        os.environ["WECHAT_VAULT"] = str(v)
        self.assertEqual(env_config.doctor(verbose=False), 1)

    def test_doctor_does_not_print_full_path(self):
        """体检输出会被贴进 issue / 聊天，不能带出完整路径。"""
        v = self.tmp / "vault"
        (v / ".obsidian").mkdir(parents=True)
        os.environ["WECHAT_VAULT"] = str(v)
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            env_config.doctor()
        self.assertNotIn(str(v), buf.getvalue())


class TestSetupEnvWizard(unittest.TestCase):
    """setup_env 的写入行为：模板渲染、拒绝覆盖、占位符不含真实路径。"""

    def test_render_has_no_real_path_when_given_placeholder(self):
        import setup_env
        text = setup_env.render({
            "WECHAT_VAULT": "/path/to/your/obsidian-vault",
            "WECHAT_SUBFOLDER_PATTERN": "*公众号",
            "WECHAT_INDEX_PATTERN": "*知识库索引*.md",
        })
        self.assertIn("WECHAT_VAULT=/path/to/your/obsidian-vault", text)
        self.assertIn("WECHAT_SUBFOLDER_PATTERN=*公众号", text)

    def test_refuses_overwrite_without_force(self):
        import setup_env
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / ".env"
            target.write_text("OLD=1\n", encoding="utf-8")
            cfg = {"WECHAT_VAULT": "/v"}
            self.assertEqual(setup_env.write_env(target, cfg), 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "OLD=1\n")

    def test_force_overwrites(self):
        import setup_env
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / ".env"
            target.write_text("OLD=1\n", encoding="utf-8")
            cfg = {"WECHAT_VAULT": "/v", "WECHAT_SUBFOLDER_PATTERN": "*公众号",
                   "WECHAT_INDEX_PATTERN": "*知识库索引*.md"}
            self.assertEqual(setup_env.write_env(target, cfg, force=True), 0)
            text = target.read_text(encoding="utf-8")
            self.assertIn("WECHAT_VAULT=/v", text)
            self.assertNotIn("OLD=1", text)

    def test_dry_run_writes_nothing(self):
        import setup_env
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / ".env"
            cfg = {"WECHAT_VAULT": "/v"}
            self.assertEqual(setup_env.write_env(target, cfg, dry_run=True), 0)
            self.assertFalse(target.exists())


class TestExampleFileIsPublicSafe(unittest.TestCase):
    """`.env.example` 会进公开仓库，只能有占位符。"""

    def test_example_exists_and_has_placeholder(self):
        p = env_config.repo_root() / ".env.example"
        self.assertTrue(p.is_file(), "缺少 .env.example")
        text = p.read_text(encoding="utf-8")
        self.assertIn("WECHAT_VAULT=", text)
        # 占位符形态，不是某台机器上的真实路径
        val = [ln.split("=", 1)[1].strip() for ln in text.splitlines()
               if ln.startswith("WECHAT_VAULT=")][0]
        self.assertTrue(val.startswith("/path/to/") or val.startswith("<"),
                        "WECHAT_VAULT 必须是占位符，实际是：%s" % val)

    def test_example_has_no_user_home_path(self):
        p = env_config.repo_root() / ".env.example"
        text = p.read_text(encoding="utf-8")
        for bad in ("C:\\", "C:/", "/Users/", "/home/"):
            self.assertNotIn(bad, text, ".env.example 里出现了疑似真实路径：%s" % bad)


if __name__ == "__main__":
    unittest.main()
