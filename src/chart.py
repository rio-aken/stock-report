"""
チャート生成モジュール
1. 全銘柄週間騰落率 水平バーチャート（メール添付用PNG）
2. 急変銘柄の13週株価推移チャート（同上）
"""

import io
import logging
from pathlib import Path
from datetime import date

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
matplotlib.rcParams['font.family'] = 'Noto Sans CJK JP'

logger = logging.getLogger(__name__)

# 出力先ディレクトリ
OUTPUT_DIR = Path("/tmp/stock_charts")
OUTPUT_DIR.mkdir(exist_ok=True)

COLOR_UP   = "#E8593C"   # 上昇：コーラル
COLOR_DOWN = "#3B8BD4"   # 下落：ブルー
COLOR_FLAT = "#9B9B95"   # ほぼ変わらず：グレー


def weekly_bar_chart(df: pd.DataFrame) -> Path:
    """
    全銘柄の週間騰落率を水平バーチャートで描画し、PNGパスを返す。
    取得失敗銘柄は除外。
    """
    valid = df[df["取得失敗"] == False].copy()
    valid = valid.sort_values("週間騰落率", ascending=True)   # 下からプロット
    labels = valid["銘柄名"] + "\n(" + valid["コード"] + ")"
    values = valid["週間騰落率"].astype(float)
    colors = [
        COLOR_UP if v >= 1.0 else (COLOR_DOWN if v <= -1.0 else COLOR_FLAT)
        for v in values
    ]

    fig_h = max(10, len(valid) * 0.38)
    fig, ax = plt.subplots(figsize=(12, fig_h))

    bars = ax.barh(range(len(valid)), values, color=colors, height=0.65, edgecolor="none")

    # 値ラベル
    for i, (bar, v) in enumerate(zip(bars, values)):
        x = v + (0.15 if v >= 0 else -0.15)
        ha = "left" if v >= 0 else "right"
        ax.text(x, i, f"{v:+.2f}%", va="center", ha=ha, fontsize=7.5, color="#333333")

    ax.set_yticks(range(len(valid)))
    ax.set_yticklabels(labels, fontsize=8.5)
    ax.axvline(0, color="#555555", linewidth=0.8, linestyle="--")
    ax.set_xlabel("週間騰落率（%）", fontsize=10)
    ax.set_title(
        f"保有銘柄 週間騰落率一覧　{date.today():%Y年%m月%d日}基準",
        fontsize=12, fontweight="bold", pad=12
    )

    # 凡例
    legend_patches = [
        mpatches.Patch(color=COLOR_UP,   label="+1%以上"),
        mpatches.Patch(color=COLOR_FLAT, label="±1%未満"),
        mpatches.Patch(color=COLOR_DOWN, label="−1%以下"),
    ]
    ax.legend(handles=legend_patches, loc="lower right", fontsize=9)
    ax.grid(axis="x", alpha=0.3, linewidth=0.5)

    fig.tight_layout()
    out = OUTPUT_DIR / "weekly_bar.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("週次バーチャート生成: %s", out)
    return out


def price_history_chart(code: str, name: str, hist: pd.DataFrame) -> Path | None:
    """
    急変銘柄の13週株価推移チャートを生成し、PNGパスを返す。
    データが空の場合は None を返す。
    """
    if hist.empty:
        return None

    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.plot(hist.index, hist["Close"], color=COLOR_UP, linewidth=1.8, zorder=3)
    ax.fill_between(hist.index, hist["Close"], alpha=0.12, color=COLOR_UP)

    # 週末ごとにグリッド
    ax.grid(axis="x", alpha=0.25, linewidth=0.5)
    ax.grid(axis="y", alpha=0.25, linewidth=0.5)
    ax.set_title(f"{name}（{code}）　直近13週株価推移", fontsize=11, fontweight="bold")
    ax.set_ylabel("株価（円）", fontsize=9)
    ax.tick_params(axis="x", labelsize=8, rotation=30)
    ax.tick_params(axis="y", labelsize=8)

    fig.tight_layout()
    out = OUTPUT_DIR / f"history_{code}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out

