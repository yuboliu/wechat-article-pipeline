# -*- coding: utf-8 -*-
"""to_obsidian.py 推广截断规则的回归测试（纯标准库，不需要网络/浏览器）。

跑法（在 skill 目录下）：
    python -m unittest discover -s tests -v
或直接：
    python tests/test_promo_trim.py

覆盖两个函数：
  * find_promo_head() —— 文首引流块（pitfalls #22）
  * find_promo_tail() —— 无结尾 `---` 时的文末推广（pitfalls #21）

这些规则一旦改错，代价是**整篇文章被腰斩**（白皮书类文章开头就带「扫码获取」），
所以每次改动都请跑一遍这里，再对本篇真实文章重跑做回归。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import to_obsidian as m  # noqa: E402


HEAD_FULL = (
    "\n---\n\n"
    "![](https://mmbiz.qpic.cn/mmbiz_png/AAA/640?wx_fmt=png&from=appmsg \"undefined\")\n\n"
    "本章节节选自《企业 DNS 建设白皮书》。\n\n"
    "**扫描下方二维码**\n\n"
    "**添加 F5 市场部助手小安**\n\n"
    "**即可免费获取完整白皮书**\n\n"
    "**《企业 DNS 建设白皮书》**\n\n"
    "![](https://mmbiz.qpic.cn/mmbiz_png/BBB/640?wx_fmt=png&from=appmsg \"undefined\")\n\n"
    "\n"
    "![](images/img_003.png)\n\n**需求分析**\n\n由于 DNS 技术历史悠久" + "…" * 200
)


class TestPromoHead(unittest.TestCase):
    def test_full_head_block_is_trimmed(self):
        idx = m.find_promo_head(HEAD_FULL)
        self.assertNotEqual(idx, -1)
        kept = HEAD_FULL[idx:].lstrip("\n")
        self.assertTrue(kept.startswith("![](images/img_003.png)"), kept[:60])
        self.assertNotIn("扫描下方二维码", kept)
        self.assertNotIn("mmbiz.qpic.cn", kept)

    def test_body_first_is_untouched(self):
        text = "\n---\n\n![](images/img_001.png)\n\n**需求分析**\n\n正文" * 3
        self.assertEqual(m.find_promo_head(text), -1)

    def test_lone_remote_image_at_head_is_untouched(self):
        """文首只有一张没本地化成功的远程图、没有引流话术 -> 不砍。"""
        text = "\n![](https://a.com/x.png)\n\n**需求分析**\n\n由于 DNS 技术历史悠久" * 3
        self.assertEqual(m.find_promo_head(text), -1)

    def test_quote_only_without_claim_is_untouched(self):
        """只有「节选自《X》」一句、没有索取诉求 -> 不砍。"""
        text = "\n---\n\n本章节节选自《企业 DNS 建设白皮书》。\n\n![[images/img_003.png]]\n\n正文" * 3
        self.assertEqual(m.find_promo_head(text), -1)

    def test_does_not_cross_into_body(self):
        """引流块后面紧跟正文段落时，只能砍到正文前一行。"""
        idx = m.find_promo_head(HEAD_FULL)
        self.assertNotIn("需求分析", HEAD_FULL[:idx])


class TestPromoTail(unittest.TestCase):
    def test_tail_markers_without_separator(self):
        """没有结尾 `---`，靠文末标记截断（需通过 33% 比例闸 + 推广特征闸）。"""
        body = "正文段落。" * 200
        tail = (
            "\n\n**关注 F5社区 微信公众号**\n\n![[images/img_007.jpeg]]\n\n"
            "**近期好文**\n\n[一篇好文](https://mp.weixin.qq.com/s?__biz=xx)\n"
        )
        idx = m.find_promo_tail(body + tail)
        self.assertNotEqual(idx, -1)
        # find_promo_tail 返回的是「推广起点」，调用方取 text[:idx] —— 故尾巴从这里开始
        self.assertTrue((body + tail)[idx:].lstrip("\n").startswith("**关注"), (body + tail)[idx:][:40])

    def test_head_qr_alone_does_not_bisect_article(self):
        """白皮书类文章开头就有「扫码获取」，尾巴占比过高 -> 不当作文末推广。"""
        text = (
            "\n**扫描下方二维码**\n\n**扫码获取完整白皮书**\n\n![](images/img_001.png)\n\n"
            + "正文段落。" * 200
        )
        self.assertEqual(m.find_promo_tail(text), -1)


class TestPromoTailTWTFooter(unittest.TestCase):
    """pitfalls #23：转载社区的固定页脚（原题 / 资料推荐 / 长按二维码 / 下载 APP）。"""

    BODY = "正文段落。" * 200
    FOOTER = (
        "\n\n> 原题：容器云平台网络架构设计及优化，首发于2021年**点击阅读原文可下载本资料**"
        "**觉得本文有用，请****转发、点赞****或点击****在看**\n\n"
        " 资料/文章推荐：\n\n"
        "- [容器云平台安全设计参考](http://mp.weixin.qq.com/s?__biz=MjM5NTk0MTM1Mw==&idx=2)\n"
        "- [容器云平台运维的范围与架构设计](http://mp.weixin.qq.com/s?__biz=MjM5NTk0MTM1Mw==&idx=1)\n\n"
        "欢迎关注社区**“容器云”技术主题**，将会不断更新优质资料、文章。\n\n"
        "**下载 twt 社区客户端 APP**\n\n![[images/img_015.png]]\n\n"
        "长按识别二维码即可下载\n\n或到应用商店搜索“twt”\n\n"
        "长按二维码关注公众号\n![[images/img_017.jpeg]]\n"
    )

    def test_footer_is_trimmed_from_the_first_marker(self):
        text = self.BODY + self.FOOTER
        idx = m.find_promo_tail(text)
        self.assertNotEqual(idx, -1)
        kept = text[:idx]
        self.assertTrue(kept.startswith("正文段落。"))
        for junk in ("原题：", "资料/文章推荐", "下载 twt", "长按识别二维码"):
            self.assertNotIn(junk, kept)

    def test_plain_quote_block_at_tail_is_kept(self):
        """普通引用块结尾（不是推广）不能被 `>` 前缀误伤。"""
        text = self.BODY + "\n\n> 注意：以上数据来自公开资料，仅供参考。\n"
        self.assertEqual(m.find_promo_tail(text), -1)


class TestPromoTailCommunityFooterNoOrigin(unittest.TestCase):
    """twt 社区 2026 版页脚：**没有 `原题：…` 那一行**（pitfalls #36）。

    旧规则里 twt 页脚全靠 `原题：` 命中；这一版把 `原题` 换掉了，其余行又都是
    「标记不在行首」（`> 欢迎点击文末阅读原文…`）或「标记后还有一整句」
    （`…，请点赞、转发或点击“♡”`），于是**一条都对不上**，整段推广（含二维码图）
    留在了笔记里。新增的几条宽松写法各带 ≤16 字行内前缀 + `[^\n]*` 吃尾巴。
    """

    BODY = "正文段落。" * 200
    FOOTER = (
        "\n\n> 支持社区支持本文同行观点，请点赞、转发或点击“♡”\n\n"
        "> 欢迎点击文末阅读原文，可以直接看到社区中本文中可能不包括的的全部信息和最新更新\n\n"
        "关联推荐：[金融可信AI趋势下，智算存储架构的核心挑战](http://mp.weixin.qq.com/s?__biz=MjM5NTk0MTM1Mw==&idx=1)"
        "[大型三甲医院网络安全垂域大模型研究](http://mp.weixin.qq.com/s?__biz=MjM5NTk0MTM1Mw==&idx=2)\n\n"
        "欢迎关注社区**“大语言模型”相关**内容**，**了解最新行业同行专家的分享和大家的观点。\n\n"
        "地址：https://www.talkwithtrend.com/Topic/154263\n\n"
        "长按二维码关注公众号\n\n![[images/img_006.jpeg]]\n\n"
        "*本公众号所发布内容仅代表作者观点，不代表社区立场，封面图片由AI生成\n\n"
        "点击下方↙↙↙阅读原文，更丰富，更精彩\n"
    )

    def test_footer_without_origin_line_is_trimmed(self):
        text = self.BODY + self.FOOTER
        idx = m.find_promo_tail(text)
        self.assertNotEqual(idx, -1, "twt 新版页脚（无 原题 行）应当被识别")
        kept = text[:idx]
        self.assertTrue(kept.startswith("正文段落。"))
        for junk in ("支持社区支持本文同行观点", "关联推荐", "长按二维码关注公众号",
                     "本公众号所发布内容", "img_006.jpeg"):
            self.assertNotIn(junk, kept)
        # 截断点必须落在页脚第一行，不能早于它
        self.assertNotIn(">", kept)

    def test_single_marker_at_head_not_trimmed(self):
        """正文里偶然出现「点击…阅读原文」但尾巴占比过高 -> 比例闸挡下。"""
        text = "点击下面阅读原文可以看到完整资料。\n\n" + self.BODY
        self.assertEqual(m.find_promo_tail(text), -1)

    def test_lone_marker_line_without_promo_features_is_kept(self):
        """只有一行「长按二维码关注公众号」、尾巴里既无 mp 链接也无第二个标记 -> 不砍。"""
        text = self.BODY + "\n\n长按二维码关注公众号，谢谢。\n"
        self.assertEqual(m.find_promo_tail(text), -1)


class TestPromoTailSignatureFooter(unittest.TestCase):
    """pitfalls #27：文末「作者：/编辑：」署名 + 个人简介 + 推荐阅读列表。"""

    BODY = "正文段落。" * 200
    FOOTER = (
        "\n\n作者：张先强\n\n"
        "从事云计算领域多年，专注于 IAAS 和容器技术，致力于优化资源管理和提升系统性能。\n\n"
        "![[images/img_010.jpeg]]\n\n"
        "编辑：刘  颜\n\n"
        "专注于容器、DevOps、可观测以及微服务架构技术，在云原生和云架构领域不断探索与深耕。\n\n"
        "![[images/img_011.gif]]\n\n"
        "[G行基于Hudi的实时数据湖架构与实践](http://mp.weixin.qq.com/s?__biz=MzI1MTA5NDg5Ng==&idx=1)"
        "[对象存储的多中心多活架构设计](http://mp.weixin.qq.com/s?__biz=MzI1MTA5NDg5Ng==&idx=2)\n"
    )

    def test_signature_footer_is_trimmed(self):
        text = self.BODY + self.FOOTER
        idx = m.find_promo_tail(text)
        self.assertNotEqual(idx, -1)
        kept = text[:idx]
        self.assertNotIn("作者：张先强", kept)
        self.assertNotIn("编辑：刘", kept)

    def test_lone_author_line_is_kept(self):
        """文末只有一行「作者：xxx」、后面没有任何推荐链接 -> 不砍（第二道闸挡下）。"""
        text = self.BODY + "\n\n作者：某某\n"
        self.assertEqual(m.find_promo_tail(text), -1)

    def test_head_author_line_is_kept(self):
        """文章开头就写「作者：xxx」-> 尾巴占比过高，被比例闸挡下。"""
        text = "作者：某某\n\n" + self.BODY
        self.assertEqual(m.find_promo_tail(text), -1)


class TestBackstageClaimLineKill(unittest.TestCase):
    """整行删除「后台 + 私信/对话框/留言/回复 + 获取/领取/下载 + 名词」引导（pitfalls #39、#41）。

    两个真实样本（同一个号「模智空间」的两次再发版，措辞各不相同）：
      「MIT发布Agent信心指数」：`模智空间后台对话框私信260702获取完整白皮书！`
      「79页RSI综述」：        `模智空间后台回复260923获取完整综述！`
    初版正则要求 `后台私信` **紧邻**、名词限于 `原文|报告|文件|资料|PDF`：
    第一个样本差「对话框」与「白皮书」，第二个差「回复」与「综述」，都没命中。
    """

    def _run(self, tail_line):
        import shutil
        import tempfile

        tmp = tempfile.mkdtemp()
        try:
            d = "样本"
            os.makedirs(os.path.join(tmp, d))
            with open(os.path.join(tmp, d, d + ".md"), "w", encoding="utf-8") as f:
                f.write(
                    "# 样本\n\n> 公众号: 模智空间\n> 发布时间: 2026-07-02\n\n---\n\n"
                    "正文一段。\n\n" + tail_line + "\n"
                )
            dst = m.convert(d, tmp, ["标签"])
            with open(dst, encoding="utf-8") as f:
                return f.read()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_backstage_dialog_claim_line_is_removed(self):
        out = self._run("模智空间后台对话框私信260702获取完整白皮书！")
        self.assertNotIn("后台对话框私信", out)
        self.assertIn("正文一段。", out)

    def test_plain_backstage_claim_still_removed(self):
        out = self._run("关注公众号后台私信获取完整报告")
        self.assertNotIn("后台私信", out)

    def test_ordinary_backstage_mention_is_kept(self):
        """正文里正常提到「后台私信」不该被误删（缺「获取/领取/下载」+ 名词）。"""
        out = self._run("我们在后台私信里收到了一些反馈，说明该功能需要改进。")
        self.assertIn("说明该功能需要改进", out)

    def test_backstage_reply_claim_line_is_removed(self):
        """「后台回复 + 编码 + 获取 + 综述」变体（第 14 篇「79页RSI综述」结尾）。

        原文：`模智空间后台回复260923获取完整综述！`
        触发词 `回复` 与名词 `综述` 都是 #39 那次没有的，于是整句留在了笔记末尾。
        """
        out = self._run("模智空间后台回复260923获取完整综述！")
        self.assertNotIn("后台回复260923", out)
        self.assertIn("正文一段。", out)

    def test_ordinary_backstage_reply_mention_is_kept(self):
        """正文里「后台回复」不带获取 + 名词时不删（三条件须同时成立）。"""
        out = self._run("系统支持在后台回复用户消息，管理员可随时查看记录。")
        self.assertIn("管理员可随时查看记录", out)


class TestPromoNav(unittest.TestCase):
    """文末「历史文章导航区」截断（find_promo_nav）。

    样本：「华创策略姚佩」那篇研报，正文 47 k，其后堆了 200 来条自家历史文章链接
    （`**再通胀牛市市场观点：**` + `**十五五系列：**` 等小节），连法律声明一起 23 k，
    占全文 33.9% —— 恰好顶掉 find_promo_tail 的 33% 比例闸，整段导航连二维码
    一起留在笔记里。新判据不看比例、看结构：从最后一条链接行向上回溯，只吃
    「空行 / 短小节标题 / 链接行」，整块 ≥8 条 mp 链接才认。
    """

    LINK = "[【策略】某篇文章%d](https://mp.weixin.qq.com/s?__biz=AAA&mid=%d)"

    def _nav(self, n):
        lines = ["# 标题", "", "正文最后一段。", "", "**再通胀牛市市场观点：**", ""]
        for i in range(n):
            lines += [self.LINK % (i, i), ""]
        return "\n".join(lines)

    def test_nav_block_is_found(self):
        t = self._nav(10)
        idx = m.find_promo_nav(t)
        self.assertNotEqual(-1, idx)
        self.assertIn("正文最后一段。", t[:idx])
        self.assertNotIn("某篇文章", t[:idx])

    def test_nav_block_with_series_and_tail_qr(self):
        """系列小节标题夹在链接之间、末尾再挂「关注 + 二维码图」时，整块一起截掉。"""
        lines = ["# 标题", "", "正文。", "", "**再通胀牛市市场观点：**", ""]
        for i in range(10):
            lines += [self.LINK % (i, i), ""]
        lines += ["**十五五系列：**", ""]
        for i in range(10, 15):
            lines += [self.LINK % (i, i), ""]
        lines += ["欢迎长按二维码关注", "", "![](images/img_099.jpeg)", ""]
        t = "\n".join(lines)
        idx = m.find_promo_nav(t)
        self.assertNotEqual(-1, idx)
        self.assertNotIn("某篇文章", t[:idx])
        self.assertNotIn("欢迎长按二维码关注", t[:idx])

    def test_too_few_links_is_not_nav(self):
        """只有 3 条链接的小「往期推荐」交给 find_promo_tail，不归这里。"""
        self.assertEqual(-1, m.find_promo_nav(self._nav(3)))

    def test_ordinary_inline_link_is_not_nav(self):
        """正文里带链接的句子不是导航行（去掉链接后仍有正文）。"""
        t = ("# 标题\n\n正文。\n\n"
             "参考[我们的另一篇文章](https://mp.weixin.qq.com/s?__biz=AAA&mid=1)"
             "讨论了这个问题，值得一读。\n\n"
             "最后一段。\n")
        self.assertEqual(-1, m.find_promo_nav(t))

    def test_link_in_code_fence_is_ignored(self):
        """代码块里的 mp 链接不算导航行（围栏感知）。"""
        t = ("# 标题\n\n正文。\n\n```\n"
             + "\n".join(self.LINK % (i, i) for i in range(10))
             + "\n```\n\n收尾。\n")
        self.assertEqual(-1, m.find_promo_nav(t))


if __name__ == "__main__":
    unittest.main(verbosity=2)
