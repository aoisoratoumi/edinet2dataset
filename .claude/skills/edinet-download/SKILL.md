---
name: edinet-download
description: EDINET から有価証券報告書・四半期報告書などをダウンロードして edinet_corpus/ に保存し、PostgreSQL に投入して DB を最新化する。「EDINETからデータを取得」「有報をダウンロード」「DBを最新にして」「edinet_corpus.sh を実行」などの依頼で使う。
---

# EDINET データダウンロード & PostgreSQL 投入

EDINET API から書類（有価証券報告書など）を一括ダウンロードして `edinet_corpus/<doc_type>/<EDINETコード>/` 配下に TSV / PDF / JSON メタデータとして保存し、続けて PostgreSQL の `reports` テーブルに投入する。**ダウンロードと DB 投入は必ずセットで実行し、DB を最新の状態にすること。**

## 前提条件

1. 環境変数 `EDINET_API_KEY` が設定されていること（未設定だと `Downloader` の初期化で assert エラーになる）。
   ```bash
   # .env または環境変数で設定されているか確認
   echo $EDINET_API_KEY
   grep EDINET_API_KEY .env 2>/dev/null
   ```
   未設定の場合はユーザーに API キーの設定を依頼して止まること（キーは https://api.edinet-fsa.go.jp/ で取得）。

2. 環境変数 `DATABASE_URL` が設定されていること（PostgreSQL 投入に必要。`.env` でも可）。
   ```bash
   grep DATABASE_URL .env 2>/dev/null || echo $DATABASE_URL
   ```
   例: `postgresql://user:password@localhost:5432/edinet`

3. 依存関係がインストールされていること（`uv sync` 済み）。

## 実行方法

手順は2ステップ: **① EDINET からダウンロード → ② PostgreSQL に投入**。①だけで終わらせないこと。

## ステップ①: EDINET からダウンロード

### 方法 A: edinet_corpus.sh で一括取得（開始年〜今日まで）

「最新までダウンロード」と言われたらこの方法を使う。開始年の1月から**実行日（今日）まで**を月単位で自動的にダウンロードする。未来の月はスキップされ、当月は今日までに丸められる。

```bash
bash edinet_corpus.sh          # デフォルト: 2026年1月〜今日
bash edinet_corpus.sh 2024     # 2024年1月〜今日
```

- 書類種別はスクリプト内の `doc_types=(...)` で切り替える（デフォルトは annual と quarterly。他はコメントアウトを外す）。
- 1ヶ月ごとに `scripts/prepare_edinet_corpus.py` を呼び出す。全期間の完了には時間がかかる（API のレート制限対策で1書類ごとに 1〜1.5 秒スリープする）ため、長時間かかる場合はバックグラウンド実行を検討する。

### 方法 B: prepare_edinet_corpus.py を直接実行（期間をピンポイント指定）

特定の期間だけ取得したい場合はシェルスクリプトを経由せず直接実行するほうが早い:

```bash
uv run python scripts/prepare_edinet_corpus.py \
  --doc_type annual \
  --start_date 2025-01-01 \
  --end_date 2025-02-01 \
  --max_workers 3
```

| オプション | デフォルト | 説明 |
|---|---|---|
| `--start_date` | `2025-01-01` | 取得開始日（提出日ベース） |
| `--end_date` | `2025-03-01` | 取得終了日（この日を含む） |
| `--doc_type` | `annual` | `annual` / `quarterly` / `semiannual` / `annual_amended` / `quarterly_amended` / `semiannual_amended` |
| `--output_dir` | `edinet_corpus` | 出力先ディレクトリ |
| `--max_workers` | `8` | 並列ダウンロード数（レート制限を考慮し 3 程度を推奨） |

### ダウンロード動作の特徴（方法 A / B 共通）

- **再実行安全**: `<docID>.json` が既に存在する書類はスキップされるため、中断後の再実行や差分取得はそのまま再実行すればよい。
- 取り下げ済み書類（withdrawalStatus=1）は自動でスキップされる。
- 出力: `edinet_corpus/<doc_type>/<EDINETコード>/<docID>.{tsv,pdf,json}`

## ステップ②: PostgreSQL に投入（DB の最新化）

ダウンロード完了後、**取得した doc_type ごと**に `load_to_postgres.py` を実行して `reports` テーブルを最新化する:

```bash
# annual をダウンロードした場合
uv run python scripts/load_to_postgres.py --corpus_dir edinet_corpus/annual

# quarterly もダウンロードした場合は続けて実行
uv run python scripts/load_to_postgres.py --corpus_dir edinet_corpus/quarterly
```

- `doc_id` キーの UPSERT（`ON CONFLICT DO UPDATE`）なので何度実行しても安全。新規取得分は INSERT、既存分は UPDATE される。
- テーブルが無ければ自動作成される。
- 完了時のログ「完了: N 件 INSERT/UPDATE、M 件スキップ」を確認し、結果をユーザーに報告すること。
