"""
edinet2dataset MCP サーバー。
Claude から「営業利益が伸びている会社を教えて」と聞かれたとき、
EDINET データをもとに答えられるようにするツール群を提供します。

起動方法:
    uv run python src/edinet2dataset/mcp_server.py

インデックスが未作成の場合は先に以下を実行してください:
    uv run python scripts/build_profit_index.py
"""

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from edinet2dataset.parser import parse_tsv

mcp = FastMCP("edinet2dataset")

# プロジェクトルートを基準にパスを解決
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_INDEX_PATH = _PROJECT_ROOT / "edinet_corpus" / "profit_index.json"
_CORPUS_DIR = _PROJECT_ROOT / "edinet_corpus" / "annual"


def _load_index() -> list[dict]:
    if not _INDEX_PATH.exists():
        raise FileNotFoundError(
            f"インデックスファイルが見つかりません: {_INDEX_PATH}\n"
            "先に `uv run python scripts/build_profit_index.py` を実行してください。"
        )
    with open(_INDEX_PATH, encoding="utf-8") as f:
        return json.load(f)


@mcp.tool()
def rank_by_operating_profit_growth(
    top_n: int = 20,
    sort_by: str = "growth_rate_pct",
) -> str:
    """
    営業利益の伸びが大きい会社をランキングして返します。
    EDINET に提出された有価証券報告書（直近期）のデータを使用します。

    Args:
        top_n: 上位何社を返すか（デフォルト 20）
        sort_by: ソート基準。
            "growth_rate_pct"  … 前期比増加率（%）が大きい順（デフォルト）
            "growth_amount"    … 前期比増加額（円）が大きい順
    """
    data = _load_index()

    if sort_by not in ("growth_rate_pct", "growth_amount"):
        return "sort_by は 'growth_rate_pct' または 'growth_amount' を指定してください。"

    ranked = sorted(data, key=lambda x: x.get(sort_by, float("-inf")), reverse=True)
    top = ranked[:top_n]

    lines = [f"## 営業利益の伸び ランキング（上位 {top_n} 社）\n"]
    lines.append(f"{'順位':<4} {'会社名':<30} {'決算期':<12} {'前期(億円)':>10} {'当期(億円)':>10} {'増減率(%)':>10} {'増減額(億円)':>12}")
    lines.append("-" * 95)
    for i, row in enumerate(top, 1):
        prev = row["operating_profit_prev"] / 1e8
        curr = row["operating_profit_current"] / 1e8
        rate = row["growth_rate_pct"]
        amount = row["growth_amount"] / 1e8
        lines.append(
            f"{i:<4} {row['company_name']:<30} {row['period_end']:<12} {prev:>10.1f} {curr:>10.1f} {rate:>10.1f} {amount:>12.1f}"
        )

    return "\n".join(lines)


@mcp.tool()
def get_company_financials(edinet_code: str) -> str:
    """
    指定した EDINET コードの企業の直近財務データ（BS/PL/CF/サマリー）を返します。

    Args:
        edinet_code: 企業の EDINET コード（例: "E02144" = トヨタ自動車）
    """
    company_dir = _CORPUS_DIR / edinet_code
    if not company_dir.exists():
        return f"企業ディレクトリが見つかりません: {edinet_code}"

    # 最新の TSV ファイルを探す
    latest_tsv = None
    latest_period_end = ""
    company_name = ""

    for tsv_path in company_dir.glob("*.tsv"):
        json_path = tsv_path.with_suffix(".json")
        if not json_path.exists():
            continue
        with open(json_path, encoding="utf-8") as f:
            meta = json.load(f)
        period_end = meta.get("periodEnd", "")
        if period_end > latest_period_end:
            latest_period_end = period_end
            latest_tsv = tsv_path
            company_name = meta.get("filerName", "")

    if latest_tsv is None:
        return f"TSV ファイルが見つかりません: {edinet_code}"

    try:
        financial_data = parse_tsv(str(latest_tsv))
    except Exception as e:
        return f"パースエラー: {e}"

    if financial_data is None:
        return "個別決算のみの企業のため、連結データがありません。"

    result = {
        "company_name": company_name,
        "edinet_code": edinet_code,
        "period_end": latest_period_end,
        "meta": financial_data.meta,
        "summary": financial_data.summary,
        "bs": financial_data.bs,
        "pl": financial_data.pl,
        "cf": financial_data.cf,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def search_company_by_name(query: str) -> str:
    """
    会社名の部分一致でインデックス内の企業を検索します。
    EDINET コードを調べるときに使います。

    Args:
        query: 検索キーワード（例: "トヨタ"、"ソフトバンク"）
    """
    data = _load_index()
    matches = [row for row in data if query in row.get("company_name", "")]

    if not matches:
        return f"「{query}」に一致する企業が見つかりませんでした。"

    lines = [f"「{query}」の検索結果: {len(matches)} 社\n"]
    lines.append(f"{'会社名':<30} {'EDINETコード':<12} {'決算期':<12} {'営業利益増減率(%)':>16}")
    lines.append("-" * 75)
    for row in matches:
        lines.append(
            f"{row['company_name']:<30} {row['edinet_code']:<12} {row['period_end']:<12} {row['growth_rate_pct']:>16.1f}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
