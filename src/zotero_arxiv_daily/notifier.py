from __future__ import annotations

import os
from pathlib import Path

import requests
from loguru import logger

REQUEST_TIMEOUT = 12


def split_message(message: str, limit: int) -> list[str]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in message.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > limit:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        if line_len > limit:
            for start in range(0, len(line), limit):
                chunks.append(line[start:start + limit])
            continue
        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current))
    return chunks or [""]


def _post_json(url: str, payload: dict) -> None:
    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()


def send_feishu(webhook: str, message: str, limit: int, dry_run: bool = False) -> int:
    chunks = split_message(message, limit)
    for chunk in chunks:
        payload = {"msg_type": "text", "content": {"text": chunk}}
        if dry_run:
            logger.info("Dry run: skip Feishu webhook post")
        else:
            _post_json(webhook, payload)
    return len(chunks)


def send_wechat_work(webhook: str, message: str, limit: int, dry_run: bool = False) -> int:
    chunks = split_message(message, limit)
    for chunk in chunks:
        payload = {"msgtype": "markdown", "markdown": {"content": chunk}}
        if dry_run:
            logger.info("Dry run: skip WeChat Work webhook post")
        else:
            _post_json(webhook, payload)
    return len(chunks)


def send_notifications(config, markdown_path: Path) -> None:
    if not config.get("enabled", True):
        return

    message = markdown_path.read_text(encoding="utf-8")
    dry_run = bool(config.get("dry_run", False))

    feishu_webhook = os.getenv("FEISHU_WEBHOOK")
    if feishu_webhook:
        count = send_feishu(feishu_webhook, message, int(config.get("feishu_limit", 3500)), dry_run)
        logger.info(f"Sent Feishu notification in {count} chunk(s)")

    wechat_webhook = os.getenv("WECHAT_WORK_WEBHOOK")
    if wechat_webhook:
        count = send_wechat_work(wechat_webhook, message, int(config.get("wechat_work_limit", 3900)), dry_run)
        logger.info(f"Sent WeChat Work notification in {count} chunk(s)")
