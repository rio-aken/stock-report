[README.md](https://github.com/user-attachments/files/29620852/README.md)
# 株価レポート自動配信システム

## 構成

```
yfinance（無料）→ GitHub Actions（無料）→ Gemini API Flash 無料枠 → Gmail（無料）
```

月間費用：¥0

---

## セットアップ手順（5ステップ）

### STEP 1：GitHubリポジトリを作成する

1. https://github.com → 「New repository」
2. リポジトリ名：`stock-report`（任意）
3. **Public** を選択（Actionsの無料実行時間が無制限になる）
4. このフォルダの中身を全てプッシュする

```bash
cd stock-report
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/あなたのユーザー名/stock-report.git
git push -u origin main
```

### STEP 2：Gmailアプリパスワードを取得する

1. https://myaccount.google.com/security を開く
2. 「2段階認証プロセス」をオンにする（未設定の場合）
3. 同ページで「アプリパスワード」を検索して選択
4. アプリ名を任意に入力して「生成」→ **16文字のパスワードをメモ**

### STEP 3：Gemini APIキーを取得する（無料）

1. https://aistudio.google.com/app/apikey を開く
2. Googleアカウントでログイン
3. 「Create API key」→ キーをコピー
4. 無料枠：Gemini 2.5 Flash で1日1,500リクエストまで無料（週10件以下なので十分）

### STEP 4：GitHubにSecretsを登録する

リポジトリ → Settings → Secrets and variables → Actions → **New repository secret**

| Secret名           | 値                              |
|--------------------|--------------------------------|
| `GMAIL_ADDRESS`    | 送信元のGmailアドレス            |
| `GMAIL_APP_PASSWORD` | STEP2で取得した16文字のパスワード |
| `TO_EMAIL`         | 送付先メールアドレス（自分宛でOK）  |
| `GEMINI_API_KEY`   | STEP3で取得したAPIキー           |

### STEP 5：テスト実行

リポジトリ → **Actions** タブ → 「株価レポート自動配信」→ **Run workflow** → `weekly` を選択 → Run

Gmailの受信トレイにレポートが届いたら完成。

---

## 自動実行スケジュール

| タイミング | 動作 |
|---|---|
| 毎週金曜 16:30 JST | ウィークリーレポート（全銘柄一覧 + チャート）送信 |
| 平日毎日 10:00 JST | 急変チェック（±5%超の銘柄があればアラートメール送信） |

---

## 銘柄を変更する場合

`src/stocks.py` の `STOCKS` 辞書を編集する。

```python
STOCKS: dict[str, str] = {
    "7203": "トヨタ自動車",   # 証券コード: 銘柄名
    ...
}
```

急変フラグの閾値（デフォルト±5%）は同ファイルの `ALERT_THRESHOLD` で変更できる。

---

## 注意事項

- yfinanceはYahoo Financeの非公式ライブラリ。個人利用の範囲で使用すること。
- Gemini API無料枠では入力データがGoogle製品改善に利用される場合がある。
- 本システムは情報提供目的のみ。投資判断は自己責任で行うこと。
