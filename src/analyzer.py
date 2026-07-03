"""
急変銘柄分析モジュール
Gemini API（gemini-2.5-flash）無料枠を使って急変理由・背景・市況を生成する。
API KEY は環境変数 GEMINI_API_KEY から取得。
"""

import os
import time
import logging

import yfinance as yf
import google.generativeai as genai

logger = logging.getLogger(__name__)

_client_initialized = False


def _init():
    global _client_initialized
    if not _client_initialized:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise EnvironmentError("環境変数 GEMINI_API_KEY が設定されていません")
        genai.configure(api_key=api_key)
        _client_initialized = True


def analyze(code: str, name: str, change_pct: float) -> str:
    """
    急変銘柄1件について Gemini Flash に分析テキストを生成させる。

    Returns
    -------
    str  分析テキスト（主因 / 市況 / 短期見通し / 示唆）
         エラー時は空文字を返す。
    """
    _init()

    # yfinance でニュースタイトルを最大5件取得
    news_text = _fetch_news(code)

    prompt = f"""以下の銘柄の株価が今週急変しました。背景・理由・市況を、個人投資家が読む短いレポート形式で日本語で出力してください。

【銘柄】{name}（証券コード {code}）
【週間騰落率】{change_pct:+.2f}%
【直近ニュース（参考）】
{news_text}

【出力形式】箇条書きで4項目、各1〜2文：
- 主な変動要因：
- セクター・市況環境：
- 短期見通し（1〜4週）：
- 個人投資家への示唆："""

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.3,
                max_output_tokens=400,
            ),
        )
        result = response.text.strip()
        time.sleep(1.0)   # 無料枠 RPM 制限への配慮
        return result
    except Exception as exc:
        logger.error("Gemini APIエラー %s %s – %s", code, name, exc)
        return ""


def _fetch_news(code: str) -> str:
    """yfinance 経由でニュースタイトルを取得する。取れなければ空文字。"""
    try:
        ticker = yf.Ticker(f"{code}.T")
        news = ticker.news or []
        titles = []
        for item in news[:5]:
            content = item.get("content", {})
            title = content.get("title") or item.get("title", "")
            if title:
                titles.append(f"・{title}")
        return "\n".join(titles) if titles else "（ニュース取得なし）"
    except Exception:
        return "（ニュース取得失敗）"
