"""
全企業の営業利益を事前計算し、edinet_corpus/profit_index.json に保存するスクリプト。
MCP サーバーが起動時に読み込むインデックスファイルを生成します。

Usage:
    uv run python scripts/build_profit_index.py
    uv run python scripts/build_profit_index.py --corpus_dir edinet_corpus/annual --output edinet_corpus/profit_index.json
"""

import argparse
import json
import os
import sys

from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from edinet2dataset.parser import parse_tsv


def load_metadata(json_path: str) -> dict:
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def find_latest_tsv(company_dir: str) -> tuple[str | None, dict | None]:
    """企業ディレクトリから最新の TSV ファイルとそのメタデータを返す。"""
    latest_tsv = None
    latest_meta = None
    latest_period_end = ""

    for filename in os.listdir(company_dir):
        if not filename.endswith(".tsv"):
            continue
        json_path = os.path.join(company_dir, filename.replace(".tsv", ".json"))
        if not os.path.exists(json_path):
            continue
        meta = load_metadata(json_path)
        period_end = meta.get("periodEnd", "")
        if period_end > latest_period_end:
            latest_period_end = period_end
            latest_tsv = os.path.join(company_dir, filename)
            latest_meta = meta

    return latest_tsv, latest_meta


def build_index(corpus_dir: str, output_path: str) -> None:
    edinet_codes = sorted(os.listdir(corpus_dir))
    results = []
    skipped = 0

    for edinet_code in tqdm(edinet_codes, desc="企業をパース中"):
        company_dir = os.path.join(corpus_dir, edinet_code)
        if not os.path.isdir(company_dir):
            continue

        tsv_path, meta = find_latest_tsv(company_dir)
        if tsv_path is None:
            skipped += 1
            continue

        try:
            financial_data = parse_tsv(tsv_path)
        except Exception:
            skipped += 1
            continue

        if financial_data is None:
            skipped += 1
            continue

        operating_profit = financial_data.pl.get("営業利益")
        if operating_profit is None:
            skipped += 1
            continue

        curr_str = operating_profit.get("CurrentYear")
        prev_str = operating_profit.get("Prior1Year")
        if curr_str is None or prev_str is None:
            skipped += 1
            continue

        try:
            curr = float(curr_str)
            prev = float(prev_str)
        except (ValueError, TypeError):
            skipped += 1
            continue

        if prev == 0:
            skipped += 1
            continue

        growth_rate = (curr - prev) / abs(prev) * 100

        results.append(
            {
                "edinet_code": edinet_code,
                "company_name": meta.get("filerName", ""),
                "period_end": meta.get("periodEnd", ""),
                "operating_profit_current": curr,
                "operating_profit_prev": prev,
                "growth_rate_pct": round(growth_rate, 2),
                "growth_amount": curr - prev,
            }
        )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"インデックス作成完了: {len(results)} 社 (スキップ: {skipped} 社)")
    print(f"保存先: {output_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="営業利益インデックスを構築する")
    parser.add_argument(
        "--corpus_dir",
        default="edinet_corpus/annual",
        help="edinet_corpus の annual ディレクトリ",
    )
    parser.add_argument(
        "--output",
        default="edinet_corpus/profit_index.json",
        help="出力 JSON ファイルのパス",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build_index(args.corpus_dir, args.output)
