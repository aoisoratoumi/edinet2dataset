"""
全企業の有価証券報告書データを PostgreSQL に保存するスクリプト。

テーブル設計:
  reports テーブル: 1行 = 1書類（TSV ファイル）
    - 構造化カラム: doc_id / edinet_code / 決算期 / 会計基準 など
    - JSONB カラム: meta / summary / bs / pl / cf / text

Usage:
    uv run python scripts/load_to_postgres.py

環境変数 (.env ファイルでも可):
    DATABASE_URL=postgresql://user:password@localhost:5432/edinet
"""

import glob
import json
import os
import sys
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from loguru import logger
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from edinet2dataset.parser import parse_tsv

load_dotenv()

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS reports (
    id                  SERIAL PRIMARY KEY,
    doc_id              TEXT    NOT NULL UNIQUE,
    edinet_code         TEXT    NOT NULL,
    company_name        TEXT,
    security_code       TEXT,
    accounting_standard TEXT,
    fiscal_year_start   DATE,
    fiscal_year_end     DATE,
    is_consolidated     BOOLEAN,
    is_amended          BOOLEAN,
    meta                JSONB,
    summary             JSONB,
    bs                  JSONB,
    pl                  JSONB,
    cf                  JSONB,
    text                JSONB
);
CREATE INDEX IF NOT EXISTS idx_reports_edinet_code     ON reports (edinet_code);
CREATE INDEX IF NOT EXISTS idx_reports_company_name    ON reports (company_name);
CREATE INDEX IF NOT EXISTS idx_reports_fiscal_year_end ON reports (fiscal_year_end);
"""

UPSERT_SQL = """
INSERT INTO reports (
    doc_id, edinet_code, company_name, security_code,
    accounting_standard, fiscal_year_start, fiscal_year_end,
    is_consolidated, is_amended,
    meta, summary, bs, pl, cf, text
) VALUES (
    %(doc_id)s, %(edinet_code)s, %(company_name)s, %(security_code)s,
    %(accounting_standard)s, %(fiscal_year_start)s, %(fiscal_year_end)s,
    %(is_consolidated)s, %(is_amended)s,
    %(meta)s, %(summary)s, %(bs)s, %(pl)s, %(cf)s, %(text)s
)
ON CONFLICT (doc_id) DO UPDATE SET
    company_name        = EXCLUDED.company_name,
    security_code       = EXCLUDED.security_code,
    accounting_standard = EXCLUDED.accounting_standard,
    fiscal_year_start   = EXCLUDED.fiscal_year_start,
    fiscal_year_end     = EXCLUDED.fiscal_year_end,
    is_consolidated     = EXCLUDED.is_consolidated,
    is_amended          = EXCLUDED.is_amended,
    meta    = EXCLUDED.meta,
    summary = EXCLUDED.summary,
    bs      = EXCLUDED.bs,
    pl      = EXCLUDED.pl,
    cf      = EXCLUDED.cf,
    text    = EXCLUDED.text;
"""


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return str(value).lower() == "true"


def _parse_date(value: str | None) -> str | None:
    if not value or value.strip() in ("", "－"):
        return None
    return value


def process_tsv(tsv_path: str, edinet_code: str) -> dict | None:
    """TSV 1ファイルをパースして INSERT 用の辞書を返す。失敗時は None。"""
    json_path = tsv_path.replace(".tsv", ".json")
    if not os.path.exists(json_path):
        return None

    with open(json_path, encoding="utf-8") as f:
        file_meta = json.load(f)

    doc_id = file_meta.get("docID")
    if not doc_id:
        return None

    try:
        financial_data = parse_tsv(tsv_path)
    except Exception as e:
        logger.warning(f"パースエラー {tsv_path}: {e}")
        return None

    if financial_data is None:
        return None

    meta = financial_data.meta
    return {
        "doc_id": doc_id,
        "edinet_code": edinet_code,
        "company_name": meta.get("会社名"),
        "security_code": meta.get("証券コード"),
        "accounting_standard": meta.get("会計基準"),
        "fiscal_year_start": _parse_date(meta.get("当事業年度開始日")),
        "fiscal_year_end": _parse_date(meta.get("当事業年度終了日")),
        "is_consolidated": _parse_bool(meta.get("連結決算の有無")),
        "is_amended": _parse_bool(meta.get("修正の有無")),
        "meta":    json.dumps(meta,                    ensure_ascii=False),
        "summary": json.dumps(financial_data.summary,  ensure_ascii=False),
        "bs":      json.dumps(financial_data.bs,       ensure_ascii=False),
        "pl":      json.dumps(financial_data.pl,       ensure_ascii=False),
        "cf":      json.dumps(financial_data.cf,       ensure_ascii=False),
        "text":    json.dumps(financial_data.text,     ensure_ascii=False),
    }


def collect_tsv_paths(corpus_dir: str) -> list[tuple[str, str]]:
    """(tsv_path, edinet_code) のリストを返す。"""
    result = []
    for edinet_code in sorted(os.listdir(corpus_dir)):
        company_dir = os.path.join(corpus_dir, edinet_code)
        if not os.path.isdir(company_dir):
            continue
        for tsv_file in glob.glob(os.path.join(company_dir, "*.tsv")):
            result.append((tsv_file, edinet_code))
    return result


def flush(conn, records: list[dict]) -> None:
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, UPSERT_SQL, records)
    conn.commit()


def main() -> None:
    parser = ArgumentParser(description="EDINET データを PostgreSQL に保存する")
    parser.add_argument("--corpus_dir",   default="edinet_corpus/annual")
    parser.add_argument("--database_url", default=os.getenv("DATABASE_URL"),
                        help="例: postgresql://user:pass@localhost:5432/edinet")
    parser.add_argument("--num_workers",  type=int, default=8,  help="並列スレッド数")
    parser.add_argument("--batch_size",   type=int, default=200, help="1回のINSERT件数")
    args = parser.parse_args()

    if not args.database_url:
        logger.error("DATABASE_URL が未設定です。.env または --database_url で指定してください。")
        sys.exit(1)

    conn = psycopg2.connect(args.database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
        conn.commit()
        logger.info("テーブル作成/確認完了")

        tsv_paths = collect_tsv_paths(args.corpus_dir)
        logger.info(f"処理対象: {len(tsv_paths)} ファイル")

        pending: list[dict] = []
        inserted = skipped = 0

        with ThreadPoolExecutor(max_workers=args.num_workers) as executor:
            futures = {
                executor.submit(process_tsv, path, code): path
                for path, code in tsv_paths
            }
            for future in tqdm(as_completed(futures), total=len(futures), desc="パース & 保存"):
                record = future.result()
                if record:
                    pending.append(record)
                else:
                    skipped += 1

                if len(pending) >= args.batch_size:
                    flush(conn, pending)
                    inserted += len(pending)
                    pending = []

        if pending:
            flush(conn, pending)
            inserted += len(pending)

        logger.info(f"完了: {inserted} 件 INSERT/UPDATE、{skipped} 件スキップ")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
