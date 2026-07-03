"""
レポート生成モジュール
1. ウィークリーHTMLメール本文（全銘柄一覧 + 急変ハイライト）
2. 急変アラートHTMLメール本文（詳細分析付き）
"""

from datetime import date
from pathlib import Path

import pandas as pd


# ── カラー定義 ─────────────────────────────────────────
C_UP_BG    = "#FEF0ED"
C_UP_TEXT  = "#C0392B"
C_DOWN_BG  = "#EBF4FB"
C_DOWN_TEXT= "#1A5276"
C_FLAT_BG  = "#F8F8F8"
C_HDR_BG   = "#1A3557"
C_HDR_TEXT = "#FFFFFF"
C_ALT_ROW  = "#F4F6F8"


def _pct_style(v) -> str:
    """騰落率の色スタイルを返す。"""
    if v is None:
        return "color:#999"
    if v >= 5.0:
        return f"color:{C_UP_TEXT};font-weight:bold"
    if v >= 1.0:
        return f"color:{C_UP_TEXT}"
    if v <= -5.0:
        return f"color:{C_DOWN_TEXT};font-weight:bold"
    if v <= -1.0:
        return f"color:{C_DOWN_TEXT}"
    return "color:#555"


def _row_bg(v, i: int) -> str:
    if v is None:
        return C_FLAT_BG
    if abs(v) >= 5.0:
        return C_UP_BG if v > 0 else C_DOWN_BG
    return C_ALT_ROW if i % 2 == 0 else "#FFFFFF"


def _fmt(v, suffix=""):
    return "─" if v is None else f"{v:,}{suffix}"


def _fmt_pct(v):
    return "─" if v is None else f"{v:+.2f}%"


# ─────────────────────────────────────────────────────────
# 1. ウィークリーレポートHTML（全銘柄一覧）
# ─────────────────────────────────────────────────────────
def weekly_html(df: pd.DataFrame, alert_analyses: dict[str, str]) -> str:
    today = date.today()
    alert_df = df[df["急変フラグ"] == True]
    n_up   = int((df["週間騰落率"] > 0).sum())
    n_down = int((df["週間騰落率"] < 0).sum())

    # ── ヘッダー ──
    html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<style>
  body{{font-family:Arial,'Helvetica Neue',sans-serif;font-size:13px;color:#222;margin:0;padding:16px;background:#F0F2F5}}
  .card{{background:#fff;border-radius:8px;padding:24px;margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
  h1{{font-size:18px;color:{C_HDR_BG};margin:0 0 6px}}
  h2{{font-size:14px;color:{C_HDR_BG};margin:16px 0 8px;border-left:4px solid {C_HDR_BG};padding-left:8px}}
  table{{border-collapse:collapse;width:100%;font-size:12px}}
  th{{background:{C_HDR_BG};color:{C_HDR_TEXT};padding:7px 10px;text-align:center}}
  td{{padding:6px 10px;border-bottom:1px solid #E8EAED;text-align:right}}
  td.left{{text-align:left}}
  .badge-up{{background:{C_UP_BG};color:{C_UP_TEXT};border-radius:4px;padding:2px 7px;font-weight:bold;font-size:11px}}
  .badge-dn{{background:{C_DOWN_BG};color:{C_DOWN_TEXT};border-radius:4px;padding:2px 7px;font-weight:bold;font-size:11px}}
  .analysis{{background:#FAFBFC;border-left:3px solid #B0B8C1;padding:10px 12px;margin:10px 0 0;font-size:12px;line-height:1.7;white-space:pre-wrap}}
  .disclaimer{{font-size:10px;color:#999;margin-top:20px;text-align:center}}
</style></head><body>

<div class="card">
  <h1>📊 週次株価レポート　{today:%Y年%m月%d日}基準</h1>
  <p style="color:#666;font-size:12px;margin:0">
    対象銘柄 {len(df)}件　／　上昇 {n_up}件・下落 {n_down}件
    {'　／　<span style="color:'+C_UP_TEXT+';font-weight:bold">急変（±5%超）'+str(len(alert_df))+'件</span>' if len(alert_df) > 0 else ''}
  </p>
</div>
"""

    # ── 急変銘柄ハイライト（あれば） ──
    if len(alert_df) > 0:
        html += '<div class="card"><h2>⚡ 急変銘柄ハイライト（週間騰落率 ±5%超）</h2>'
        for _, row in alert_df.iterrows():
            v = row["週間騰落率"]
            direction = "上昇" if v and v > 0 else "下落"
            badge_cls = "badge-up" if v and v > 0 else "badge-dn"
            analysis = alert_analyses.get(row["コード"], "")
            html += f"""
<div style="border:1px solid #E0E4E8;border-radius:6px;padding:12px;margin-bottom:12px">
  <div style="display:flex;align-items:center;gap:10px">
    <span style="font-weight:bold;font-size:13px">{row['銘柄名']}</span>
    <span style="color:#888;font-size:11px">{row['コード']}</span>
    <span class="{badge_cls}">{direction} {_fmt_pct(v)}</span>
  </div>
  <div style="font-size:12px;color:#555;margin-top:4px">
    現在株価 {_fmt(row['現在株価'], '円')}　前週末 {_fmt(row['前週末株価'], '円')}
  </div>
  {'<div class="analysis">'+analysis+'</div>' if analysis else ''}
</div>"""
        html += "</div>"

    # ── 全銘柄一覧テーブル ──
    html += '<div class="card"><h2>📋 全銘柄一覧</h2><table>'
    html += "<tr><th>#</th><th style='text-align:left'>銘柄名</th><th>コード</th><th>現在株価</th><th>前週末株価</th><th>週間騰落率</th><th>状態</th></tr>"
    for i, (_, row) in enumerate(df.iterrows(), 1):
        v = row["週間騰落率"]
        bg = _row_bg(v, i)
        pct_s = _pct_style(v)
        flag = ""
        if row["取得失敗"]:
            flag = "<span style='color:#999;font-size:10px'>取得失敗</span>"
        elif row["急変フラグ"]:
            flag = "⚡ 急変"
        html += f"""
<tr style="background:{bg}">
  <td style="text-align:center;color:#888">{i}</td>
  <td class="left">{row['銘柄名']}</td>
  <td style="text-align:center">{row['コード']}</td>
  <td>{_fmt(row['現在株価'], '円')}</td>
  <td>{_fmt(row['前週末株価'], '円')}</td>
  <td style="{pct_s}">{_fmt_pct(v)}</td>
  <td style="text-align:center;font-size:11px">{flag}</td>
</tr>"""
    html += "</table></div>"

    html += f'<p class="disclaimer">本メールは個人利用目的の自動生成レポートです。投資判断は自己責任でお願いします。<br>データソース：yfinance（Yahoo Finance）</p></body></html>'
    return html


# ─────────────────────────────────────────────────────────
# 2. 急変アラートHTML（随時配信）
# ─────────────────────────────────────────────────────────
def alert_html(alert_df: pd.DataFrame, analyses: dict[str, str]) -> str:
    today = date.today()
    html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<style>
  body{{font-family:Arial,sans-serif;font-size:13px;color:#222;margin:0;padding:16px;background:#F0F2F5}}
  .card{{background:#fff;border-radius:8px;padding:24px;margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
  h1{{font-size:18px;color:#A93226;margin:0 0 6px}}
  .analysis{{background:#FAFBFC;border-left:3px solid #E74C3C;padding:10px 12px;margin:10px 0 0;font-size:12px;line-height:1.7;white-space:pre-wrap}}
  .disclaimer{{font-size:10px;color:#999;margin-top:20px;text-align:center}}
</style></head><body>
<div class="card">
  <h1>⚡ 急変アラート　{today:%Y年%m月%d日}</h1>
  <p style="color:#666;font-size:12px">以下の銘柄が週間騰落率±5%を超えました。</p>
</div>
"""
    for _, row in alert_df.iterrows():
        v = row["週間騰落率"]
        direction = "上昇" if v and v > 0 else "下落"
        border_color = C_UP_TEXT if v and v > 0 else C_DOWN_TEXT
        analysis = analyses.get(row["コード"], "（分析生成なし）")
        html += f"""
<div class="card" style="border-top:4px solid {border_color}">
  <div style="font-size:15px;font-weight:bold">{row['銘柄名']}　<span style="font-size:12px;color:#888">{row['コード']}</span></div>
  <div style="margin:6px 0;font-size:13px">
    週間{direction}：<strong style="color:{border_color}">{_fmt_pct(v)}</strong>　
    現在株価 {_fmt(row['現在株価'], '円')}　前週末 {_fmt(row['前週末株価'], '円')}
  </div>
  <div class="analysis">{analysis}</div>
</div>"""

    html += '<p class="disclaimer">本メールは個人利用目的の自動生成レポートです。投資判断は自己責任でお願いします。</p></body></html>'
    return html

