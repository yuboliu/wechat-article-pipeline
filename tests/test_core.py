import pytest
from bs4 import BeautifulSoup

from wechat_article_to_markdown import (
    _strip_para_indent,
    convert_to_markdown,
    extract_publish_time,
    extract_source_url,
    format_timestamp,
    normalize_wechat_url,
    process_content,
    replace_image_urls,
)


# ------------------------------------------------------------------
# normalize_wechat_url
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Clean URL – no change
        (
            "https://mp.weixin.qq.com/s?__biz=ABC&mid=123&idx=1&sn=xyz",
            "https://mp.weixin.qq.com/s?__biz=ABC&mid=123&idx=1&sn=xyz",
        ),
        # Backslash-escaped separators (zsh url-quote-magic)
        (
            r"https://mp.weixin.qq.com/s\?__biz=ABC\&mid=123",
            "https://mp.weixin.qq.com/s?__biz=ABC&mid=123",
        ),
        # HTML entity &amp;
        (
            "https://mp.weixin.qq.com/s?__biz=ABC&amp;mid=123",
            "https://mp.weixin.qq.com/s?__biz=ABC&mid=123",
        ),
        # Wrapped in double quotes
        (
            '"https://mp.weixin.qq.com/s?a=1"',
            "https://mp.weixin.qq.com/s?a=1",
        ),
        # Wrapped in angle brackets
        (
            "<https://mp.weixin.qq.com/s?a=1>",
            "https://mp.weixin.qq.com/s?a=1",
        ),
        # http → https
        (
            "http://mp.weixin.qq.com/s?a=1",
            "https://mp.weixin.qq.com/s?a=1",
        ),
        # Bare hostname (no scheme)
        (
            "mp.weixin.qq.com/s?a=1",
            "https://mp.weixin.qq.com/s?a=1",
        ),
        # // prefix
        (
            "//mp.weixin.qq.com/s?a=1",
            "https://mp.weixin.qq.com/s?a=1",
        ),
        # Empty / None
        ("", ""),
        ("  ", ""),
    ],
)
def test_normalize_wechat_url(raw: str, expected: str) -> None:
    assert normalize_wechat_url(raw) == expected


def test_extract_publish_time_supports_multiple_patterns() -> None:
    ts = 1700000000
    expected = format_timestamp(ts)

    assert extract_publish_time(f"create_time:'{ts}'") == expected
    assert extract_publish_time(f'create_time:"{ts}"') == expected
    assert extract_publish_time(f"create_time = {ts}") == expected
    assert extract_publish_time(f"create_time:JsDecode('{ts}')") == expected


def test_extract_source_url_supports_both_quote_styles() -> None:
    url = "https://mp.weixin.qq.com/s/tKlag40gOMkeELuMtT-vmw"

    assert extract_source_url(f'var msg_link = "{url}"') == url
    assert extract_source_url(f"var msg_link = '{url}'") == url


def test_extract_source_url_decodes_html_entities() -> None:
    html = 'var msg_link = "https://mp.weixin.qq.com/s?a=1&amp;b=2"'

    assert extract_source_url(html) == "https://mp.weixin.qq.com/s?a=1&b=2"


def test_extract_source_url_returns_empty_when_absent() -> None:
    assert extract_source_url("<html><body>no link here</body></html>") == ""


def test_replace_image_urls_handles_parentheses() -> None:
    md = (
        "![](https://example.com/a_(1).png)\n"
        "![alt](https://example.com/b.png?x=1&y=2)"
    )
    url_map = {
        "https://example.com/a_(1).png": "images/a.png",
        "https://example.com/b.png?x=1&y=2": "images/b.png",
    }

    out = replace_image_urls(md, url_map)
    assert "![](images/a.png)" in out
    assert "![alt](images/b.png)" in out


def test_process_content_extracts_code_and_images() -> None:
    html = """
    <div id="js_content">
      <img data-src="https://example.com/1.png" />
      <img src="https://example.com/1.png" />
      <div class="code-snippet__fix">
        <pre data-lang="python"></pre>
        <code>print('hello')</code>
      </div>
      <script>bad()</script>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")

    content_html, code_blocks, img_urls = process_content(soup)

    assert "script" not in content_html
    assert img_urls == ["https://example.com/1.png"]
    assert code_blocks == [{"lang": "python", "code": "print('hello')"}]


def test_convert_to_markdown_restores_code_block() -> None:
    html = "<p>before</p><p>CODEBLOCK-PLACEHOLDER-0</p><p>after</p>"
    md = convert_to_markdown(html, [{"lang": "python", "code": "print(1)"}])

    assert "```python" in md
    assert "print(1)" in md
    assert "CODEBLOCK-PLACEHOLDER-0" not in md


# ------------------------------------------------------------------
# _strip_para_indent  （&nbsp; 首行缩进的残留会被当成缩进代码块）
# ------------------------------------------------------------------


def test_strip_para_indent_removes_plain_paragraph_indent() -> None:
    md = "    当金融机构的用户发起请求，需要有权威服务器解析。"
    assert _strip_para_indent(md) == "当金融机构的用户发起请求，需要有权威服务器解析。"


def test_strip_para_indent_keeps_markdown_structure_lines() -> None:
    # 列表续行、引用、标题、表格、图片行都不该被去缩进
    md = (
        "    - 1.2.1 协议栈\n"
        "    > 引用行\n"
        "    # 标题\n"
        "    | a | b |\n"
        "    ![x](y.png)"
    )
    assert _strip_para_indent(md) == md


def test_strip_para_indent_keeps_fenced_code_content() -> None:
    md = "```\n    缩进属于代码内容，必须保留\n```"
    assert _strip_para_indent(md) == md


def test_strip_para_indent_end_to_end_via_convert() -> None:
    # nbsp 首行缩进经 markdownify + \u00a0 清理后不得残留 4 空格缩进
    html = "<p>&nbsp;&nbsp;&nbsp;&nbsp;正文段落</p>"
    md = convert_to_markdown(html, [])
    assert "\n    正文段落" not in md
    assert "正文段落" in md


# ------------------------------------------------------------------
# 标题标签里裹着图片  （markdownify 会连图带标签一起丢掉）
# ------------------------------------------------------------------


def test_image_inside_heading_is_not_lost() -> None:
    """`<h3><img/></h3>` 里的图片必须留下来。

    markdownify 的 `<hN>` 转换只保留 alt 文字，`<h3><img alt="图片"/></h3>` 会被渲染成
    `### 图片` —— 图没了，还白送一个大纲里的假标题。真实样本：「不管你是运维还是开发，
    微服务这些你得知道!」的 img_001.gif 就是这样下载了却从未被引用。
    """
    html = (
        '<div id="js_content">'
        '<h3 style="text-align:center"><span>'
        '<img data-src="https://mmbiz.qpic.cn/a/640?wx_fmt=gif" alt="图片" /></span></h3>'
        "<h3><span>一、还是从网站开始</span></h3>"
        "</div>"
    )
    soup = BeautifulSoup(html, "html.parser")
    content_html, _blocks, img_urls = process_content(soup)
    md = convert_to_markdown(content_html, [])

    assert img_urls == ["https://mmbiz.qpic.cn/a/640?wx_fmt=gif"]
    assert "![图片](https://mmbiz.qpic.cn/a/640?wx_fmt=gif)" in md
    assert "### 图片" not in md
    # 真标题不受影响
    assert "### 一、还是从网站开始" in md


def test_heading_with_text_and_image_is_unwrapped_too() -> None:
    html = '<div id="js_content"><h3>示意图<img src="https://x/y.png" alt="图" /></h3></div>'
    soup = BeautifulSoup(html, "html.parser")
    content_html, _blocks, img_urls = process_content(soup)
    md = convert_to_markdown(content_html, [])

    assert img_urls == ["https://x/y.png"]
    assert "![图](https://x/y.png)" in md
    assert "###" not in md
