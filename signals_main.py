"""
複合シグナルチェック メインスクリプト（Phase 1）

実行フロー:
  1. watchlist.csv から監視銘柄を読み込み
  2. data/signal_state.json から前回状態（信用残・海外勢フロー履歴）を読み込み
  3. JPX公開データ + yfinance を取得
  4. 危険/強気シグナルを判定
  5. 閾値以上の銘柄があれば src/mailer.py でメール送信
  6. stateを更新して保存（GitHub Actionsがコミットして永続化）

環境変数（既存 stock-report と共通）:
  GMAIL_ADDRESS / GMAIL_APP_PASSWORD / TO_EMAIL
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("signals_main")

STATE_PATH = ROOT / "data" / "signal_state.json"
WATCHLIST_PATH = ROOT / "watchlist.csv"
FOREIGN_HISTORY_MAX = 8   # 海外勢フローの保持週数


def load_watchlist() -> list[dict]:
    if not WATCHLIST_PATH.exists():
        logger.error("watchlist.csv がありません。README_signals.md を参照してください。")
        sys.exit(1)
    # Windowsのメモ帳/Excelで編集された場合に備え、
    # UTF-8(BOM付き含む) → Shift_JIS(CP932) の順で自動判別する
    rows = None
    for enc in ("utf-8-sig", "cp932"):
        try:
            with open(WATCHLIST_PATH, encoding=enc) as f:
                rows = [r for r in csv.DictReader(f) if (r.get("code") or "").strip()]
            logger.info("watchlist.csv を %s として読み込みました", enc)
            break
        except UnicodeDecodeError:
            continue
    if rows is None:
        logger.error("watchlist.csv の文字コードを判別できません（UTF-8またはShift_JISで保存してください）。")
        sys.exit(1)
    if not rows:
        logger.error("watchlist.csv に銘柄がありません。")
        sys.exit(1)
    for r in rows:
        r["code"] = r["code"].strip()
        r["name"] = (r.get("name") or r["code"]).strip()
        r["yf_ticker"] = r.get("yf_ticker", "").strip() or f"{r['code']}.T"
    return rows


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("state破損。初期化します。")
    return {"foreign_flow": [], "margin": {}}


def save_state(state: dict) -> None:
    parent = STATE_PATH.parent
    # 「data」という名前のファイルが誤って存在するとmkdirが失敗するため退避
    if parent.exists() and not parent.is_dir():
        logger.warning("'%s' がファイルとして存在するため削除してフォルダを作成します", parent)
        parent.unlink()
    parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def fetch_price_history(tickers: list[str]):
    import yfinance as yf
    data = {}
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period="4mo", auto_adjust=False)
            data[t] = hist if len(hist) else None
        except Exception as e:
            logger.warning("株価取得失敗 %s: %s", t, e)
            data[t] = None
    return data


def main() -> None:
    from jpx_sources import (fetch_short_positions, fetch_weekly_margin,
                             fetch_foreign_investor_flow)
    from signals import (build_stock_signal, evaluate_foreign_flow,
                         MIN_SCORE_TO_ALERT)
    from signal_report import signal_alert_html, build_subject
    import mailer

    watchlist = load_watchlist()
    codes = {r["code"] for r in watchlist}
    state = load_state()

    # ── 海外投資家フロー（週次・市場全体）: 取得してstateに蓄積 ──
    # 同じ週を再取得した場合は上書きする（過去の誤取得値の自動修正を兼ねる）
    # 過去3週分を取り込み（D1/B1の連続判定を即時有効化）
    latest_flows = fetch_foreign_investor_flow(n_files=3)
    flow_map = {h["week"]: h for h in state["foreign_flow"]}
    for f in latest_flows:
        flow_map[f["week"]] = {"week": f["week"], "net": f["net"]}
    state["foreign_flow"] = sorted(flow_map.values(),
                                   key=lambda h: h["week"], reverse=True)[:FOREIGN_HISTORY_MAX]
    foreign = evaluate_foreign_flow(state["foreign_flow"])

    # ── 空売り残高（日次・銘柄別）: 直近2営業日分を取得して比較 ──
    short_snaps = fetch_short_positions(codes, n_files=2)

    # ── 信用買残（週次・銘柄別・PDF）: 今週分取得、前回state分と比較 ──
    margin_now = fetch_weekly_margin(codes)
    margin_prev_state = state.get("margin", {})

    # ── 株価（yfinance） ──
    prices = fetch_price_history([r["yf_ticker"] for r in watchlist])

    # ── 判定 ──
    results = []
    for r in watchlist:
        sig = build_stock_signal(
            code=r["code"], name=r["name"],
            hist=prices.get(r["yf_ticker"]),
            short_snapshots=short_snaps,
            margin_current=margin_now.get(r["code"]),
            margin_prev=margin_prev_state.get(r["code"]),
            foreign=foreign,
        )
        results.append(sig)
        logger.info("%s %s: 危険%d/5 強気%d/5",
                    r["code"], r["name"], sig.danger_score, sig.bullish_score)

    # ── 信用残stateの更新（新しい週のデータが取れた銘柄のみ上書き） ──
    for code, cur in margin_now.items():
        prev = margin_prev_state.get(code)
        if prev is None or prev.get("date") != cur.get("date"):
            margin_prev_state[code] = cur
    state["margin"] = margin_prev_state
    save_state(state)

    # ── 送信判定 ──
    hits = [s for s in results
            if s.danger_score >= MIN_SCORE_TO_ALERT
            or s.bullish_score >= MIN_SCORE_TO_ALERT]
    if not hits:
        logger.info("アラート水準の銘柄なし。メールは送信しません。")
        return

    html = signal_alert_html(results)
    subject = build_subject(results)
    mailer.send(subject, html)
    logger.info("アラート送信完了: %s", subject)


if __name__ == "__main__":
    main()
