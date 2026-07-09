"""
複合シグナル判定モジュール（Phase 1: 5条件 + 逆パターン5条件）

危険シグナル（ユーザー定義の「最も危険なサイン」）:
  D1 海外投資家が数週間連続で売り越し   … 市場全体フラグ（JPX投資部門別・週次）
  D2 空売り残高が増加                   … 銘柄別（JPX空売り残高報告・日次、開示ベース）
  D3 信用買残が増加                     … 銘柄別（JPX銘柄別信用取引週末残高・週次）
  D4 株価が25日移動平均線を割り込む     … 銘柄別（yfinance・日次）
  D5 出来高を伴って下落                 … 銘柄別（yfinance・日次）

強気シグナル（逆パターン）:
  B1 海外投資家が数週間連続で買い越し
  B2 空売り残高が減少（買い戻し）
  B3 信用買残が減少（需給改善）
  B4 株価が25日移動平均線を上抜け
  B5 出来高を伴って上昇

各条件は True / False / None（データ欠損＝判定除外）の3値。
スコア = True の数。判定除外があった場合はレポートに明記する。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

logger = logging.getLogger(__name__)

# ── 閾値設定（必要に応じて調整） ──────────────────────────
FOREIGN_STREAK_WEEKS = 3          # D1/B1: 連続売り越し/買い越しの週数
SHORT_RATIO_DELTA_PT = 0.3        # D2/B2: 開示空売り残高割合合計の増減(±pt)
MARGIN_BUY_DELTA_PCT = 10.0       # D3/B3: 信用買残の週次増減率(±%)
VOLUME_SPIKE_RATIO = 1.5          # D5/B5: 20日平均出来高に対する倍率
PRICE_MOVE_PCT = 3.0              # D5/B5: 当日騰落率の閾値(±%)
MA_DAYS = 25                      # D4/B4: 移動平均日数
MIN_SCORE_TO_ALERT = 3            # この点数以上の銘柄があればメール送信
MAX_SCORE = 5

# 信用残PDFの数値列の意味づけ（2026/6/26申込分の実PDFで検証済み）。
# 行の数値は 売残高, 売残前週比, 買残高, 買残前週比, （以下内訳）の順。
MARGIN_COLUMN_MAP = {"sell_balance": 0, "sell_change": 1,
                     "buy_balance": 2, "buy_change": 3}


@dataclass
class StockSignal:
    code: str
    name: str
    danger: dict[str, bool | None] = field(default_factory=dict)
    bullish: dict[str, bool | None] = field(default_factory=dict)
    detail: dict[str, str] = field(default_factory=dict)

    @property
    def danger_score(self) -> int:
        return sum(1 for v in self.danger.values() if v is True)

    @property
    def bullish_score(self) -> int:
        return sum(1 for v in self.bullish.values() if v is True)

    @property
    def missing(self) -> list[str]:
        return [k for k, v in {**self.danger}.items() if v is None]


# ─────────────────────────────────────────────────────────
# D1/B1: 海外投資家フロー（市場全体）
# ─────────────────────────────────────────────────────────
def evaluate_foreign_flow(history: list[dict]) -> tuple[bool | None, bool | None, str]:
    """
    history: [{"week": "260604", "net": int}, ...]（新しい順、stateに蓄積したもの）
    戻り値: (D1判定, B1判定, 説明文)
    """
    if len(history) < FOREIGN_STREAK_WEEKS:
        return None, None, f"海外投資家フロー: 蓄積{len(history)}週分（{FOREIGN_STREAK_WEEKS}週必要）"

    recent = history[:FOREIGN_STREAK_WEEKS]
    nets = [h["net"] for h in recent]
    d1 = all(n < 0 for n in nets)
    b1 = all(n > 0 for n in nets)
    desc = "／".join(f"{h['week']}週: {'買越' if h['net'] > 0 else '売越'} {abs(h['net']):,}千円"
                    for h in recent)
    return d1, b1, desc


# ─────────────────────────────────────────────────────────
# D2/B2: 空売り残高（銘柄別・開示ベース）
# ─────────────────────────────────────────────────────────
def evaluate_short_positions(code: str, snapshots: list) -> tuple[bool | None, bool | None, str]:
    """
    snapshots: jpx_sources.ShortPositionSnapshot のリスト（新しい順、2件以上）
    開示閾値(0.5%)未満は掲載されないため「開示ベースの近似」である点に注意。
    """
    if len(snapshots) < 2:
        return None, None, "空売り残高: 比較用データ不足"

    latest, prev = snapshots[0], snapshots[1]
    cur = latest.total_ratio.get(code, 0.0)
    old = prev.total_ratio.get(code, 0.0)
    delta = cur - old

    if cur == 0.0 and old == 0.0:
        return False, False, "空売り残高: 開示対象(0.5%以上)の報告なし"

    holders = latest.holders.get(code, [])
    holder_txt = f"（報告者: {', '.join(holders[:3])}{'…' if len(holders) > 3 else ''}）" if holders else ""
    desc = f"開示空売り残高合計 {old:.2f}% → {cur:.2f}%（{delta:+.2f}pt）{holder_txt}"
    return delta >= SHORT_RATIO_DELTA_PT, delta <= -SHORT_RATIO_DELTA_PT, desc


# ─────────────────────────────────────────────────────────
# D3/B3: 信用買残（銘柄別・週次）
# ─────────────────────────────────────────────────────────
def evaluate_margin_buy(code: str, current: dict | None,
                        prev_state: dict | None = None) -> tuple[bool | None, bool | None, str]:
    """
    current: jpx_sources.fetch_weekly_margin() の1銘柄分 {"date", "numbers", "line"}
    PDF自体に前週比が含まれるため、当週データのみで判定できる
    （prev_state は互換性のため残しているが使用しない）。
    """
    idx_b = MARGIN_COLUMN_MAP["buy_balance"]
    idx_c = MARGIN_COLUMN_MAP["buy_change"]
    if current is None or len(current.get("numbers", [])) <= max(idx_b, idx_c):
        return None, None, "信用買残: 今週分データなし（貸借/制度信用の対象外の可能性）"

    cur = current["numbers"][idx_b]
    chg = current["numbers"][idx_c]
    prev = cur - chg
    if prev <= 0:
        return None, None, "信用買残: 前週値が算出不能"
    pct = chg / prev * 100
    desc = f"信用買残 {prev:,} → {cur:,}株（{pct:+.1f}%、{current['date']}申込分）"
    return pct >= MARGIN_BUY_DELTA_PCT, pct <= -MARGIN_BUY_DELTA_PCT, desc


# ─────────────────────────────────────────────────────────
# D4/B4/D5/B5: 株価テクニカル（yfinance）
# ─────────────────────────────────────────────────────────
def evaluate_price_signals(hist: pd.DataFrame) -> dict:
    """
    hist: yfinanceのhistory DataFrame（Close, Volume。60営業日以上推奨）
    戻り値: {"d4","b4","d5","b5","desc_ma","desc_vol"}
    """
    out = {"d4": None, "b4": None, "d5": None, "b5": None,
           "desc_ma": "株価データ不足", "desc_vol": "株価データ不足"}
    if hist is None or len(hist) < MA_DAYS + 1:
        return out

    close = hist["Close"]
    vol = hist["Volume"]
    ma = close.rolling(MA_DAYS).mean()

    last_close = float(close.iloc[-1])
    last_ma = float(ma.iloc[-1])
    out["d4"] = last_close < last_ma
    out["b4"] = last_close > last_ma
    out["desc_ma"] = f"終値 {last_close:,.1f}円 / 25日線 {last_ma:,.1f}円（乖離 {(last_close/last_ma-1)*100:+.1f}%）"

    day_ret = (float(close.iloc[-1]) / float(close.iloc[-2]) - 1) * 100
    avg_vol = float(vol.iloc[-21:-1].mean())
    last_vol = float(vol.iloc[-1])
    spike = avg_vol > 0 and last_vol >= avg_vol * VOLUME_SPIKE_RATIO
    out["d5"] = spike and day_ret <= -PRICE_MOVE_PCT
    out["b5"] = spike and day_ret >= PRICE_MOVE_PCT
    out["desc_vol"] = (f"当日騰落 {day_ret:+.1f}% / 出来高 {last_vol:,.0f}"
                       f"（20日平均比 {last_vol/avg_vol:.1f}倍）" if avg_vol > 0
                       else f"当日騰落 {day_ret:+.1f}% / 出来高平均が算出不能")
    return out


# ─────────────────────────────────────────────────────────
# 統合
# ─────────────────────────────────────────────────────────
def build_stock_signal(code: str, name: str, hist: pd.DataFrame,
                       short_snapshots: list,
                       margin_current: dict | None, margin_prev: dict | None,
                       foreign: tuple[bool | None, bool | None, str]) -> StockSignal:
    s = StockSignal(code=code, name=name)

    d1, b1, f_desc = foreign
    s.danger["D1 海外勢連続売り越し"] = d1
    s.bullish["B1 海外勢連続買い越し"] = b1
    s.detail["海外投資家(市場全体)"] = f_desc

    d2, b2, desc2 = evaluate_short_positions(code, short_snapshots)
    s.danger["D2 空売り残高増加"] = d2
    s.bullish["B2 空売り残高減少"] = b2
    s.detail["空売り残高"] = desc2

    d3, b3, desc3 = evaluate_margin_buy(code, margin_current, margin_prev)
    s.danger["D3 信用買残増加"] = d3
    s.bullish["B3 信用買残減少"] = b3
    s.detail["信用買残"] = desc3

    p = evaluate_price_signals(hist)
    s.danger["D4 25日線割れ"] = p["d4"]
    s.bullish["B4 25日線上抜け"] = p["b4"]
    s.danger["D5 出来高を伴う下落"] = p["d5"]
    s.bullish["B5 出来高を伴う上昇"] = p["b5"]
    s.detail["25日移動平均"] = p["desc_ma"]
    s.detail["出来高・騰落"] = p["desc_vol"]

    return s


def alert_level(score: int) -> str:
    if score >= MAX_SCORE:
        return "最大警戒（5条件すべて成立）"
    if score >= MIN_SCORE_TO_ALERT:
        return f"警戒（{score}/{MAX_SCORE}条件成立）"
    return ""
