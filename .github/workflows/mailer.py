"""
Gmail送信モジュール
smtplib + SSL で Gmail に接続。
環境変数:
  GMAIL_ADDRESS      送信元アドレス
  GMAIL_APP_PASSWORD Gmailアプリパスワード（16文字）
  TO_EMAIL           送付先アドレス
"""

import os
import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def send(subject: str, html_body: str, attachments: list[Path] | None = None) -> None:
    """
    HTMLメールを送信する。attachments に Path リストを渡すと添付される。

    Raises
    ------
    EnvironmentError  環境変数未設定時
    smtplib.SMTPException  送信失敗時
    """
    from_addr = _require("GMAIL_ADDRESS")
    password  = _require("GMAIL_APP_PASSWORD")
    to_addr   = _require("TO_EMAIL")

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = to_addr

    # HTMLパート
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # 添付ファイル
    for path in (attachments or []):
        if not path.exists():
            logger.warning("添付ファイルが見つかりません: %s", path)
            continue
        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition", "attachment",
            filename=path.name.encode("utf-8").decode("ascii", errors="replace")
        )
        msg.attach(part)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(from_addr, password)
        smtp.send_message(msg)

    logger.info("送信完了: %s → %s | %s", from_addr, to_addr, subject)


def _require(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        raise EnvironmentError(f"環境変数 {key} が設定されていません")
    return val
