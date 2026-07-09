"""
複合シグナルアラートのHTMLメール本文生成
既存 stock-report の src/mailer.py（send(subject, html_body)）で送信する前提。
"""

from __future__ import annotations

from datetime import date

from signals import StockSignal, MAX_SCORE, MIN_SCORE_TO_ALERT, alert_level

C_DANGER = "#A93226"
C_BULL = "#1E8449"
C_GRAY = "#888888"


def _mark(v: bool | None) -> str:
    if v is True:
        return "●"
    if v is False:
        return "─"
    return "？"


def _signal_table(title: str, items: dict[str, bool | None], color: str) -> str:
    rows = ""
    for label, v in items.items():
        style = f"color:{color};font-weight:bold" if v is True else f"color:{C_GRAY}"
        note = "（データ欠損・判定除外）" if v is None else ""
        rows += (f'<tr><td style="padding:2px 8px;{style}">{_mark(v)}</td>'
                 f'<td style="padding:2px 8px;{style}">{label}{note}</td></tr>')
    return (f'<div style="font-size:12px;font-weight:bold;margin-top:8px">{title}</div>'
            f'<table style="font-size:12px;border-collapse:collapse">{rows}</table>')


def signal_alert_html(signals: list[StockSignal],
                      run_date: date | None = None) -> str:
    run_date = run_date or date.today()
    alerted = [s for s in signals
               if s.danger_score >= MIN_SCORE_TO_ALERT
               or s.bullish_score >= MIN_SCORE_TO_ALERT]

    html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;font-size:13px;color:#222;margin:0;padding:16px;background:#F0F2F5">
<div style="background:#fff;border-radius:8px;padding:24px;margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,.08)">
  <h1 style="font-size:18px;margin:0 0 6px">複合シグナルアラート　{run_date:%Y年%m月%d日}</h1>
  <p style="color:#666;font-size:12px;margin:0">
    危険シグナル5条件／強気シグナル5条件のうち{MIN_SCORE_TO_ALERT}条件以上が成立した銘柄を通知します。<br>
    「？」はデータ欠損（公表前・取得失敗）で判定から除外した条件です。
  </p>
</div>
"""

    for s in alerted:
        is_danger = s.danger_score >= s.bullish_score
        color = C_DANGER if is_danger else C_BULL
        score = s.danger_score if is_danger else s.bullish_score
        level = alert_level(score) if is_danger else (
            "最大強気（5条件すべて成立）" if score >= MAX_SCORE
            else f"強気（{score}/{MAX_SCORE}条件成立）")
        icon = "⚠️" if is_danger else "📈"

        details = "".join(
            f'<div style="margin:2px 0"><span style="color:#666">{k}:</span> {v}</div>'
            for k, v in s.detail.items())

        html += f"""
<div style="background:#fff;border-radius:8px;padding:24px;margin-bottom:20px;border-top:4px solid {color};box-shadow:0 1px 4px rgba(0,0,0,.08)">
  <div style="font-size:15px;font-weight:bold">{icon} {s.name}
    <span style="font-size:12px;color:#888">{s.code}</span></div>
  <div style="color:{color};font-weight:bold;font-size:13px;margin:4px 0">{level}</div>
  {_signal_table("危険シグナル", s.danger, C_DANGER)}
  {_signal_table("強気シグナル", s.bullish, C_BULL)}
  <div style="background:#FAFBFC;border-left:3px solid {color};padding:10px 12px;margin-top:10px;font-size:12px;line-height:1.7">
    {details}
  </div>
</div>"""

    if not alerted:
        html += """
<div style="background:#fff;border-radius:8px;padding:24px;box-shadow:0 1px 4px rgba(0,0,0,.08)">
  <p style="font-size:13px;margin:0">本日、アラート水準に達した銘柄はありません。</p>
</div>"""

    html += """
<p style="font-size:10px;color:#999;margin-top:20px;text-align:center">
  本メールは公開データ（JPX・Yahoo Finance）に基づく個人利用目的の自動生成レポートです。<br>
  空売り残高は残高割合0.5%以上の開示分のみ、海外投資家フローは市場全体の週次集計です。<br>
  投資判断は自己責任でお願いします。
</p></body></html>"""
    return html


def build_subject(signals: list[StockSignal]) -> str:
    danger_max = [s for s in signals if s.danger_score >= MAX_SCORE]
    bull_max = [s for s in signals if s.bullish_score >= MAX_SCORE]
    if danger_max:
        return f"【最大警戒】{danger_max[0].name}ほか 危険シグナル5条件成立"
    if bull_max:
        return f"【最大強気】{bull_max[0].name}ほか 強気シグナル5条件成立"
    danger = [s for s in signals if s.danger_score >= MIN_SCORE_TO_ALERT]
    bull = [s for s in signals if s.bullish_score >= MIN_SCORE_TO_ALERT]
    parts = []
    if danger:
        parts.append(f"警戒{len(danger)}銘柄")
    if bull:
        parts.append(f"強気{len(bull)}銘柄")
    return f"【複合シグナル】{'・'.join(parts)}"
