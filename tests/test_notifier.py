from zotero_arxiv_daily.notifier import send_feishu, send_wechat_work, split_message


def test_split_message_respects_limit():
    chunks = split_message("a\nbb\nccc", 4)
    assert all(len(chunk) <= 4 for chunk in chunks)
    assert chunks


def test_send_feishu_uses_text_payload(monkeypatch):
    sent = []

    def fake_post(url, json, timeout):
        sent.append((url, json, timeout))
        return type("Response", (), {"raise_for_status": lambda self: None})()

    monkeypatch.setattr("zotero_arxiv_daily.notifier.requests.post", fake_post)
    assert send_feishu("https://example.com/feishu", "hello", 100) == 1
    assert sent[0][1]["msg_type"] == "text"


def test_send_wechat_work_uses_markdown_payload(monkeypatch):
    sent = []

    def fake_post(url, json, timeout):
        sent.append((url, json, timeout))
        return type("Response", (), {"raise_for_status": lambda self: None})()

    monkeypatch.setattr("zotero_arxiv_daily.notifier.requests.post", fake_post)
    assert send_wechat_work("https://example.com/wechat", "hello", 100) == 1
    assert sent[0][1]["msgtype"] == "markdown"
