"""
JPX公開データ取得モジュール（Phase 1）

データ源（2026-07-09 に実ページで形式確認済み）:
  1. 空売り残高報告（日次・銘柄別）
     https://www.jpx.co.jp/markets/public/short-selling/index.html
     - Excelリンク例: .../t13vrt000001f565-att/20260608_Short_Positions.xls
     - URLにランダムなCMS IDを含むため、indexページをスクレイピングして
       "_Short_Positions.xls" で終わるリンクを抽出する（URL直打ち不可）。
     - 毎営業日 17:00 目処に掲載。残高割合0.5%以上の報告のみ収録。

  2. 銘柄別信用取引週末残高（週次・銘柄別・PDFのみ）
     https://www.jpx.co.jp/markets/statistics-equities/margin/05.html
     - PDF URL例: .../margin/tvdivq0000001rnl-att/syumatsu2026062600.pdf
       → "syumatsu{申込日YYYYMMDD}00.pdf"。申込日は通常金曜。
     - 毎週第2営業日（通常火曜）16:30 目安に掲載。

  3. 投資部門別売買状況・株式週間（週次・市場全体）
     https://www.jpx.co.jp/markets/statistics-equities/investor-type/index.html
     - Excelリンク例: .../t13vrt000001iqby-att/stock_val_1_260604.xls（金額ベース）
     - URLにランダムなCMS IDを含むため、スクレイピングで最新リンクを取得。
     - 毎週第4営業日（通常木曜）15:30 に掲載。

注意: JPXサイトの構成変更でパースに失敗した場合は例外を握りつぶさず
      None / 空dict を返し、シグナル判定側で「データ欠損（判定除外）」として扱う。
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date, timedelta
from dataclasses import dataclass, field

import pandas as pd
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

JPX_BASE = "https://www.jpx.co.jp"
SHORT_SELLING_INDEX = f"{JPX_BASE}/markets/public/short-selling/index.html"
MARGIN_PDF_TEMPLATE = (
    f"{JPX_BASE}/markets/statistics-equities/margin/"
    "tvdivq0000001rnl-att/syumatsu{yyyymmdd}00.pdf"
)
INVESTOR_TYPE_INDEX = f"{JPX_BASE}/markets/statistics-equities/investor-type/index.html"

HEADERS = {
    # JPXはプログラム的UAを拒否する場合があるため一般的なブラウザUAを使用
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "ja,en;q=0.8",
}
TIMEOUT = 30


def _get(url: str) -> requests.Response | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            logger.warning("HTTP %s: %s", r.status_code, url)
            return None
        return r
    except requests.RequestException as e:
        logger.warning("取得失敗 %s: %s", url, e)
        return None


# ─────────────────────────────────────────────────────────
# 1. 空売り残高報告（日次）
# ─────────────────────────────────────────────────────────
@dataclass
class ShortPositionSnapshot:
    """1営業日分の空売り残高スナップショット"""
    calc_date: str                       # ファイル名から取得した日付 YYYYMMDD
    total_ratio: dict[str, float] = field(default_factory=dict)   # code -> 残高割合合計(%)
    holders: dict[str, list[str]] = field(default_factory=dict)   # code -> 報告者名リスト


def fetch_short_positions(target_codes: set[str],
                          n_files: int = 2) -> list[ShortPositionSnapshot]:
    """
    直近 n_files 営業日分の空売り残高Excelを取得し、対象銘柄の
    「開示空売り残高割合の合計」と報告者名を返す（新しい順）。

    残高割合0.5%以上の報告のみJPXに掲載されるため、
    「合計が増加」= 大口空売り勢のポジション拡大の開示ベース近似となる。
    """
    res = _get(SHORT_SELLING_INDEX)
    if res is None:
        return []

    soup = BeautifulSoup(res.text, "html.parser")
    links: list[tuple[str, str]] = []   # (yyyymmdd, absolute_url)
    for a in soup.find_all("a", href=True):
        m = re.search(r"/(\d{8})_Short_Positions\.xls$", a["href"])
        if m:
            url = a["href"]
            if url.startswith("/"):
                url = JPX_BASE + url
            links.append((m.group(1), url))

    if not links:
        logger.warning("空売り残高: Excelリンクが見つかりません（ページ構成変更の可能性）")
        return []

    links.sort(key=lambda t: t[0], reverse=True)
    snapshots: list[ShortPositionSnapshot] = []

    for yyyymmdd, url in links[:n_files]:
        r = _get(url)
        if r is None:
            continue
        snap = _parse_short_positions_xls(r.content, yyyymmdd, target_codes)
        if snap is not None:
            snapshots.append(snap)

    return snapshots


def _parse_short_positions_xls(content: bytes, yyyymmdd: str,
                               target_codes: set[str]) -> ShortPositionSnapshot | None:
    """
    空売り残高Excel（.xls）を解析。
    列名はヘッダー行の文言（「コード」「割合」「氏名/名称」を含む列）で特定し、
    列順の変更に耐える設計とする。
    """
    try:
        # .xls（旧形式）→ xlrd エンジン
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None,
                               header=None, engine="xlrd")
    except Exception as e:
        logger.warning("空売り残高Excel解析失敗 (%s): %s", yyyymmdd, e)
        return None

    snap = ShortPositionSnapshot(calc_date=yyyymmdd)

    for _, df in sheets.items():
        header_row = None
        for i in range(min(len(df), 15)):
            row_text = "".join(str(v) for v in df.iloc[i].tolist())
            if "コード" in row_text and "割合" in row_text:
                header_row = i
                break
        if header_row is None:
            continue

        header = [str(v) for v in df.iloc[header_row].tolist()]
        col_code = col_ratio = col_name = None
        for j, h in enumerate(header):
            if "コード" in h and col_code is None:
                col_code = j
            if "割合" in h and "直近" not in h and col_ratio is None:
                col_ratio = j
            if ("氏名" in h or "名称" in h or "商号" in h) and col_name is None:
                col_name = j
        if col_code is None or col_ratio is None:
            continue

        for i in range(header_row + 1, len(df)):
            raw_code = str(df.iat[i, col_code]).strip()
            code = re.sub(r"\.0$", "", raw_code)
            if code not in target_codes:
                continue
            try:
                ratio = float(df.iat[i, col_ratio])
            except (TypeError, ValueError):
                continue
            # 割合が 0-1 のとき（Excel内でパーセント書式の場合）は%へ換算
            if 0 < ratio < 0.2:
                ratio *= 100
            snap.total_ratio[code] = snap.total_ratio.get(code, 0.0) + ratio
            if col_name is not None:
                name = str(df.iat[i, col_name]).strip()
                if name and name != "nan":
                    snap.holders.setdefault(code, [])
                    if name not in snap.holders[code]:
                        snap.holders[code].append(name)

    return snap


# ─────────────────────────────────────────────────────────
# 2. 銘柄別信用取引週末残高（週次・PDF）
# ─────────────────────────────────────────────────────────
def fetch_weekly_margin(target_codes: set[str],
                        weeks_back: int = 3) -> dict[str, dict]:
    """
    直近の「銘柄別信用取引週末残高」PDFを取得し、対象銘柄の行から数値を抽出。
    戻り値: {code: {"date": YYYYMMDD, "numbers": [int, ...], "line": str}}

    ※ PDFの列構成（売残・買残の並び）は実ファイルで初回に目視確認すること。
      本関数は行の数値列をそのまま返し、列の意味づけは signals 側の
      MARGIN_COLUMN_MAP 設定で行う（README参照）。
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber未インストール。requirementsを確認してください。")
        return {}

    # 方式1: 掲載ページから最新のPDFリンクを直接取得（公表スケジュール変更に強い）
    pdf_bytes, used_date = None, None
    page = _get(f"{JPX_BASE}/markets/statistics-equities/margin/05.html")
    if page is not None:
        soup = BeautifulSoup(page.text, "html.parser")
        pdf_links: list[tuple[str, str]] = []
        for a in soup.find_all("a", href=True):
            m = re.search(r"/syumatsu(\d{8})00\.pdf$", a["href"])
            if m:
                url = a["href"]
                if url.startswith("/"):
                    url = JPX_BASE + url
                pdf_links.append((m.group(1), url))
        if pdf_links:
            pdf_links.sort(key=lambda t: t[0], reverse=True)
            latest_date, latest_url = pdf_links[0]
            r = _get(latest_url)
            if r is not None and r.content[:4] == b"%PDF":
                pdf_bytes, used_date = r.content, latest_date
                logger.info("信用残PDF取得: %s申込分（ページ掲載の最新）", latest_date)
        else:
            logger.warning("信用残: ページ上にsyumatsu*.pdfリンクなし（構成変更の可能性）")

    # 方式2（フォールバック）: 直近の金曜からURLを推測
    if pdf_bytes is None:
        d = date.today()
        d -= timedelta(days=(d.weekday() - 4) % 7)   # 直近の金曜
        for _ in range(weeks_back):
            url = MARGIN_PDF_TEMPLATE.format(yyyymmdd=d.strftime("%Y%m%d"))
            r = _get(url)
            if r is not None and r.content[:4] == b"%PDF":
                pdf_bytes, used_date = r.content, d.strftime("%Y%m%d")
                break
            d -= timedelta(days=7)

    if pdf_bytes is None:
        logger.warning("信用残PDFが見つかりません（祝日ずれ・URL変更の可能性）")
        return {}

    result: dict[str, dict] = {}
    # PDF内のコード欄は5桁表記（銘柄コード+末尾0。例: 2413→24130, 285A→285A0）
    pdf_code_map = {c + "0": c for c in target_codes}
    remaining = set(pdf_code_map.keys())
    sample_lines: list[str] = []
    try:
        import unicodedata
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                if not remaining:
                    break
                text = page.extract_text() or ""
                for line in text.splitlines():
                    norm = unicodedata.normalize("NFKC", line).strip()
                    if not norm:
                        continue
                    if "JP3" in norm and len(sample_lines) < 5:
                        sample_lines.append(norm)   # 診断用: データ行のみ採取
                    pdf_code = None
                    for c in remaining:
                        # 前後が英数字でない位置で照合（銘柄名との連結にも一致）
                        if re.search(rf"(?<![0-9A-Za-z]){re.escape(c)}(?![0-9A-Za-z])", norm):
                            pdf_code = c
                            break
                    if pdf_code is not None:
                        after = norm.split(pdf_code, 1)[1]
                        # 数値抽出: 「▲ 300」= -300（▲は直後の数値を負にする）
                        numbers: list[int] = []
                        neg = False
                        for t in after.split():
                            if t in ("▲", "△", "-"):
                                neg = True
                                continue
                            if re.fullmatch(r"\d{1,3}(?:,\d{3})*|\d+", t):
                                v = int(t.replace(",", ""))
                                numbers.append(-v if neg else v)
                            neg = False
                        result[pdf_code_map[pdf_code]] = {
                            "date": used_date,
                            "numbers": numbers,
                            "line": norm,
                        }
                        remaining.discard(pdf_code)
    except Exception as e:
        logger.warning("信用残PDF解析失敗: %s", e)
        return {}

    if remaining:
        logger.info("信用残: 次の銘柄はPDF内に見つかりませんでした（貸借/制度信用の対象外の可能性）: %s",
                    sorted(pdf_code_map[c] for c in remaining))
    if not result and sample_lines:
        logger.warning("信用残PDF抽出サンプル（診断用・データ行5件）:")
        for s in sample_lines:
            logger.warning("  | %s", s)
    return result


# ─────────────────────────────────────────────────────────
# 3. 投資部門別売買状況（海外投資家・週次・市場全体）
# ─────────────────────────────────────────────────────────
def fetch_foreign_investor_flow(n_files: int = 1) -> list[dict]:
    """
    株式週間売買状況（金額ベース stock_val_1_*.xls）から
    海外投資家の売り・買い金額を抽出し、差引き（買い−売り）を返す。
    戻り値: [{"week": "260604", "net": int(千円), "confidence": "high|low"}]（新しい順）
    """
    res = _get(INVESTOR_TYPE_INDEX)
    if res is None:
        return []

    soup = BeautifulSoup(res.text, "html.parser")
    links: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        m = re.search(r"/stock_val_1_(\d{6})\.xls$", a["href"])
        if m:
            url = a["href"]
            if url.startswith("/"):
                url = JPX_BASE + url
            links.append((m.group(1), url))

    if not links:
        logger.warning("投資部門別: Excelリンクが見つかりません")
        return []

    links.sort(key=lambda t: t[0], reverse=True)
    logger.info("投資部門別: %d件のファイルを検出（最新: %s週分）", len(links), links[0][0])
    out: list[dict] = []
    for week, url in links[:n_files]:
        r = _get(url)
        if r is None:
            continue
        net, conf = _parse_foreign_net(r.content)
        if net is not None:
            logger.info("投資部門別: %s週 海外投資家 差引き %+d千円 (confidence=%s)",
                        week, net, conf)
            out.append({"week": week, "net": net, "confidence": conf})
    return out


def _parse_foreign_net(content: bytes) -> tuple[int | None, str]:
    """
    「海外投資家」（表記ゆれ「外国人」も許容）の行を全シートから探し、
    差引き額を推定する。数値がExcel内で文字列（"1,234,567"）として
    格納されている場合にも対応。
    差引き = 買い − 売り を再計算して行内の値と一致すれば confidence=high。
    """
    try:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None,
                               header=None, engine="xlrd")
    except Exception as e:
        logger.warning("投資部門別Excel解析失敗: %s", e)
        return None, "low"

    def to_num(v) -> float | None:
        if isinstance(v, (int, float)) and not pd.isna(v):
            return float(v)
        if isinstance(v, str):
            s = v.strip().replace(",", "").replace("△", "-").replace("▲", "-")
            try:
                return float(s)
            except ValueError:
                return None
        return None

    total_sell = 0.0
    total_buy = 0.0
    sheets_used: list[str] = []
    all_validated = True
    candidates = []   # 診断用

    for sheet_name, df in sheets.items():
        # 「海外投資家」ラベル行（売り行）を探す。
        # 実構造: ['海外投資家','売り','Sales', 金額, 比率, 増減...] の行に続き、
        # 次行以降に '買い/Purchases'・'合計/Total'・'差引き/Balance' の行が並ぶ。
        for i in range(len(df)):
            row = df.iloc[i].tolist()
            if not any(isinstance(v, str) and ("海外投資家" in v or "外国人" in v)
                       for v in row):
                continue

            sell = buy = block_total = balance = None
            for j in range(i, min(i + 6, len(df))):
                r = df.iloc[j].tolist()
                labels = " ".join(str(v) for v in r if isinstance(v, str))
                nums = [n for n in (to_num(v) for v in r) if n is not None]
                big = [n for n in nums if abs(n) >= 1e5]   # 金額列（比率%等を除外）
                if not big:
                    continue
                if sell is None and ("売り" in labels or "Sales" in labels):
                    sell = max(big)
                elif buy is None and ("買い" in labels or "Purchase" in labels):
                    buy = max(big)
                elif block_total is None and ("合計" in labels or "Total" in labels):
                    block_total = max(big)
                elif balance is None and ("差引" in labels or "Balance" in labels):
                    balance = max(big, key=abs)   # 差引きは負値もあり得る

            if sell is None or buy is None:
                candidates.append((sheet_name, i, row[:8],
                                   f"売り={sell} 買い={buy}"))
                continue

            # 検算: 合計行または差引き行と自前計算の一致を確認
            diff = buy - sell
            validated = False
            if block_total is not None and \
                    abs((sell + buy) - block_total) <= max(10.0, block_total * 0.001):
                validated = True
            if balance is not None and abs(diff - balance) <= max(10.0, abs(diff) * 0.001):
                validated = True
            if (block_total is not None or balance is not None) and not validated:
                logger.warning(f"投資部門別: sheet={sheet_name} 検算不一致のため除外 "
                               f"(売{sell:,.0f} 買{buy:,.0f} 合計{block_total} 差引{balance})")
                all_validated = False
                break

            total_sell += sell
            total_buy += buy
            sheets_used.append(sheet_name)
            logger.info(f"投資部門別: sheet={sheet_name} 売り{sell:,.0f} "
                        f"買い{buy:,.0f} 差引き{diff:+,.0f}"
                        f"{'（検算OK）' if validated else ''}")
            break   # 1シートにつき1ブロック

    if sheets_used:
        net = total_buy - total_sell
        conf = "high" if all_validated else "low"
        logger.info(f"投資部門別: 全市場合算（{'+'.join(sheets_used)}） "
                    f"海外投資家 差引き {net:+,.0f}千円")
        return int(net), conf

    # ここに到達 = 抽出失敗。原因究明用の診断ログを必ず残す
    if candidates:
        logger.warning("投資部門別: 海外投資家ブロックの売り/買い行を特定できず。診断:")
        for sheet, i, cells, note in candidates[:3]:
            logger.warning("  | sheet=%s row=%d %s cells=%s", sheet, i, note, cells)
    else:
        logger.warning("投資部門別: 『海外投資家』の行が見つかりません。シート名: %s",
                       list(sheets.keys()))
    return None, "low"
