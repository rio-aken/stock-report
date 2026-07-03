"""
株価データ取得モジュール
yfinance を使って42銘柄の週次データを取得・集計する。
"""

import time
import logging
from datetime import date, timedelta

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

# ── 対象銘柄 ──────────────────────────────────────────
STOCKS: dict[str, str] = {
    "5411": "JFEホールディングス",
    "9984": "ソフトバンクグループ",
    "4536": "参天製薬",
    "4552": "JCRファーマ",
    "7182": "ゆうちょ銀行",
    "9022": "東海旅客鉄道",
    "4568": "第一三共",
    "8058": "三菱商事",
    "9697": "カプコン",
    "8031": "三井物産",
    "2413": "エムスリー",
    "3962": "チェンジホールディングス",
    "6702": "富士通",
    "8473": "SBIホールディングス",
    "8593": "三菱HCキャピタル",
    "4689": "LINEヤフー",
    "6501": "日立製作所",
    "6965": "浜松ホトニクス",
    "8035": "東京エレクトロン",
    "8002": "丸紅",
    "9432": "NTT",
    "8233": "高島屋",
    "4434": "サーバーワークス",
    "2914": "日本たばこ産業",
    "6754": "アンリツ",
    "9104": "商船三井",
    "9843": "ニトリホールディングス",
    "8306": "三菱UFJフィナンシャルG",
    "8316": "三井住友フィナンシャルG",
    "4063": "信越化学工業",
    "4516": "日本新薬",
    "4661": "オリエンタルランド",
    "4901": "富士フイルムホールディングス",
    "6981": "村田製作所",
    "8359": "八十二長野銀行",
    "7011": "三菱重工業",
    "5802": "住友電気工業",
    "9201": "日本航空",
    "5831": "しずおかフィナンシャルグループ",
    "6902": "デンソー",
    "7203": "トヨタ自動車",
    "6758": "ソニーグループ",
}

ALERT_THRESHOLD = 0.05  # ±5% で急変フラグ


def _ticker(code: str) -> str:
    return f"{code}.T"


def fetch_all(lookback_days: int = 14) -> pd.DataFrame:
    """
    全銘柄の株価を取得し、週間騰落率・急変フラグを付与したDataFrameを返す。

    Returns
    -------
    pd.DataFrame  columns:
        コード, 銘柄名, 現在株価, 前週末株価, 週間騰落率(%), 急変フラグ, 取得失敗
    """
    end = date.today()
    start = end - timedelta(days=lookback_days)
    rows: list[dict] = []

    for code, name in STOCKS.items():
        try:
            hist = yf.Ticker(_ticker(code)).history(
                start=str(start), end=str(end), auto_adjust=True
            )
            if len(hist) < 2:
                logger.warning("データ不足: %s %s (%d行)", code, name, len(hist))
                rows.append(_error_row(code, name))
                time.sleep(0.5)
                continue

            close = hist["Close"].dropna()
            price_now = float(close.iloc[-1])
            # 前週末株価 = 5営業日前（取れなければ先頭）
            prev_idx = -6 if len(close) >= 6 else 0
            price_prev = float(close.iloc[prev_idx])
            change_pct = (price_now - price_prev) / price_prev * 100

            rows.append({
                "コード":     code,
                "銘柄名":     name,
                "現在株価":   round(price_now, 1),
                "前週末株価": round(price_prev, 1),
                "週間騰落率": round(change_pct, 2),
                "急変フラグ": abs(change_pct) >= ALERT_THRESHOLD * 100,
                "取得失敗":   False,
            })
            time.sleep(0.3)          # Yahoo Finance レート制限回避

        except Exception as exc:
            logger.error("取得エラー: %s %s – %s", code, name, exc)
            rows.append(_error_row(code, name))
            time.sleep(1.0)

    df = pd.DataFrame(rows)
    df = df.sort_values("週間騰落率", ascending=False).reset_index(drop=True)
    return df


def _error_row(code: str, name: str) -> dict:
    return {
        "コード":     code,
        "銘柄名":     name,
        "現在株価":   None,
        "前週末株価": None,
        "週間騰落率": None,
        "急変フラグ": False,
        "取得失敗":   True,
    }


def fetch_history_for_chart(code: str, weeks: int = 13) -> pd.DataFrame:
    """チャート用に1銘柄の週足終値を返す（最大13週）。"""
    end = date.today()
    start = end - timedelta(weeks=weeks)
    hist = yf.Ticker(_ticker(code)).history(
        start=str(start), end=str(end), auto_adjust=True
    )
    return hist[["Close"]].dropna() if not hist.empty else pd.DataFrame()
