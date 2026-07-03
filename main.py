import sys
print("=== 起動確認 ===", flush=True)
print(f"argv={sys.argv}, cwd={__import__('os').getcwd()}", flush=True)
"""
株価レポート自動配信 メインスクリプト
実行モード:
  RUN_MODE=weekly  → 全銘柄ウィークリーレポート送信
  RUN_MODE=daily   → 急変チェックのみ（±5%超があれば即時アラート）
  未設定           → 曜日で自動判定（金曜 → weekly、その他 → daily）
"""

import logging
import os
import sys
from datetime import date
from pathlib import Path

# src/ を検索パスに追加
sys.path.insert(0, str(Path(__file__).parent / "src"))

from stocks import fetch_all, fetch_history_for_chart
from chart import weekly_bar_chart, price_history_chart
from analyzer import analyze
from report import weekly_html, alert_html
from mailer import send

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)


def detect_mode() -> str:
    env = os.environ.get("RUN_MODE", "").strip().lower()
    if env in ("weekly", "daily"):
        return env
    return "weekly" if date.today().weekday() == 4 else "daily"


def main() -> None:
    mode = detect_mode()
    today = date.today()
    logger.info("実行開始: mode=%s date=%s", mode, today)

    # ── Step 1: 全銘柄データ取得 ──
    df = fetch_all()
    alert_df = df[df["急変フラグ"] == True]
    logger.info("取得完了: 全%d件、急変%d件", len(df), len(alert_df))

    # ── Step 2: 急変銘柄 → Gemini 分析 ──
    analyses: dict[str, str] = {}
    if not alert_df.empty and os.environ.get("GEMINI_API_KEY"):
        for _, row in alert_df.iterrows():
            code = row["コード"]
            logger.info("Gemini 分析中: %s %s", code, row["銘柄名"])
            analyses[code] = analyze(code, row["銘柄名"], row["週間騰落率"])
    elif not alert_df.empty:
        logger.warning("GEMINI_API_KEY 未設定のため急変分析をスキップ")

    # ── Step 3a: 急変アラートメール（急変あれば常時送信） ──
    if not alert_df.empty:
        html = alert_html(alert_df, analyses)
        n = len(alert_df)
        subject = f"⚡【急変アラート】{today:%m/%d} {n}銘柄が±5%超 | 株価レポート"

        # 急変銘柄の個別チャートを添付
        chart_paths: list[Path] = []
        for _, row in alert_df.iterrows():
            hist = fetch_history_for_chart(row["コード"])
            p = price_history_chart(row["コード"], row["銘柄名"], hist)
            if p:
                chart_paths.append(p)

        send(subject, html, chart_paths)
        logger.info("急変アラート送信: %d件", n)

    # ── Step 3b: ウィークリーレポート（金曜のみ） ──
    if mode == "weekly":
        bar_chart = weekly_bar_chart(df)
        html = weekly_html(df, analyses)
        n_alert = len(alert_df)
        subject = (
            f"📊【週次レポート】{today:%Y/%m/%d} 全{len(df)}銘柄"
            + (f"（急変{n_alert}件）" if n_alert > 0 else "")
        )
        send(subject, html, [bar_chart])
        logger.info("ウィークリーレポート送信完了")

    elif mode == "daily" and alert_df.empty:
        logger.info("急変なし・dailyモード → 送信なし")

    logger.info("実行完了")


if __name__ == "__main__":
    main()
