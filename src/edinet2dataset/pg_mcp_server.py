"""
PostgreSQL の EDINET データ（reports テーブル）に接続する MCP サーバー。

「〇〇社について調べて」と聞かれたとき、過去の経営成績・経営戦略・戦術を
DB から取得して分析できるようにするツール群を提供します。

起動方法:
    uv run python src/edinet2dataset/pg_mcp_server.py

前提:
    - 環境変数 DATABASE_URL（.env でも可）
    - scripts/load_to_postgres.py で reports テーブルにデータ投入済みであること
"""

import html
import json
import os
import re

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("edinet-postgres")

# 経営成績の推移で取り出す主要指標（summary JSONB のキー）
KEY_METRICS = [
    "売上高",
    "経常利益",
    "税引前利益(IFRS)",
    "親会社株主に帰属する当期純利益",
    "親会社株主に帰属する当期純利益 (IFRS)",
    "当期純利益又は当期純損失",
    "純資産額",
    "総資産額",
    "自己資本比率",
    "自己資本利益率、経営指標等",
    "営業活動によるキャッシュ・フロー",
    "投資活動によるキャッシュ・フロー",
    "財務活動によるキャッシュ・フロー",
    "現金及び現金同等物の残高",
    "従業員数",
    "１株当たり当期純利益又は当期純損失",
    "１株当たり配当額",
    "配当性向",
]


# IFRS 企業などは summary に「売上高」が無いため、PL 側の収益科目で補完する
PL_REVENUE_KEYS = ["売上高", "売上収益", "営業収益合計", "営業収益", "経常収益"]


def _connect():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("環境変数 DATABASE_URL が設定されていません。")
    return psycopg2.connect(database_url)


def _strip_html(text: str) -> str:
    """テキストブロックの HTML タグを除去して読みやすくする。"""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _flatten_text_value(value) -> str:
    """text JSONB の値（{年度コンテキスト: 本文} の dict または文字列）を本文に変換する。"""
    if isinstance(value, dict):
        return "\n".join(str(v) for v in value.values())
    return str(value)


def _fetch_report(cur, edinet_code: str, fiscal_year_end: str | None, columns: str):
    """指定企業のレポート1件を取得する。fiscal_year_end 未指定なら最新。"""
    if fiscal_year_end:
        cur.execute(
            f"SELECT {columns} FROM reports"
            " WHERE edinet_code = %s AND fiscal_year_end = %s"
            " ORDER BY is_amended DESC NULLS LAST LIMIT 1",
            (edinet_code, fiscal_year_end),
        )
    else:
        cur.execute(
            f"SELECT {columns} FROM reports"
            " WHERE edinet_code = %s"
            " ORDER BY fiscal_year_end DESC NULLS LAST LIMIT 1",
            (edinet_code,),
        )
    return cur.fetchone()


@mcp.tool()
def search_company(query: str) -> str:
    """
    会社名の部分一致（大文字小文字を区別しない）で企業を検索し、
    EDINET コードと保有レポートの決算期一覧を返します。

    ヒットしない場合はカタカナ・英語・漢字など表記を変えて再検索してください
    （例: サイバーダイン → CYBERDYNE）。

    Args:
        query: 会社名の一部（例: "トヨタ", "CYBERDYNE"）
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT edinet_code, company_name, security_code,
                   COUNT(*) AS n_reports,
                   MIN(fiscal_year_end) AS oldest,
                   MAX(fiscal_year_end) AS latest
            FROM reports
            WHERE company_name ILIKE %s
            GROUP BY edinet_code, company_name, security_code
            ORDER BY company_name
            LIMIT 50
            """,
            (f"%{query}%",),
        )
        rows = cur.fetchall()

    if not rows:
        return (
            f"「{query}」に一致する企業が見つかりませんでした。"
            "表記を変えて再検索してください（カタカナ⇔英語⇔漢字、株式会社の有無など）。"
        )

    lines = [f"「{query}」の検索結果: {len(rows)} 社\n"]
    for code, name, sec, n, oldest, latest in rows:
        lines.append(
            f"- {name} (EDINETコード: {code}, 証券コード: {sec}, "
            f"レポート {n} 件, 決算期 {oldest}〜{latest})"
        )
    return "\n".join(lines)


@mcp.tool()
def list_reports(edinet_code: str) -> str:
    """
    指定した企業の DB に保存されている有価証券報告書の一覧
    （doc_id / 決算期 / 会計基準 / 連結有無）を返します。

    Args:
        edinet_code: 企業の EDINET コード（例: "E02144"）
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT doc_id, fiscal_year_start, fiscal_year_end,
                   accounting_standard, is_consolidated, is_amended
            FROM reports
            WHERE edinet_code = %s
            ORDER BY fiscal_year_end
            """,
            (edinet_code,),
        )
        rows = cur.fetchall()

    if not rows:
        return f"EDINET コード {edinet_code} のレポートが見つかりません。"

    lines = [f"{edinet_code} のレポート一覧（{len(rows)} 件）\n"]
    for doc_id, fy_start, fy_end, standard, consolidated, amended in rows:
        lines.append(
            f"- {doc_id}: {fy_start}〜{fy_end}, 会計基準={standard}, "
            f"連結={'あり' if consolidated else 'なし'}, 修正={'あり' if amended else 'なし'}"
        )
    return "\n".join(lines)


@mcp.tool()
def get_financial_history(edinet_code: str) -> str:
    """
    指定した企業の経営成績の推移を返します（過去の経営成績分析に使う）。

    保存されている全レポートの主要指標（売上高・利益・ROE・キャッシュフロー・従業員数など、
    各決算期の当期値）に加え、最古レポートの「主要な経営指標等の推移」5期分も含めるため、
    保存レポートより前の年度もある程度カバーされます。

    金額の単位は円（自己資本比率・ROE などの比率は小数）。

    Args:
        edinet_code: 企業の EDINET コード（例: "E02144"）
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT fiscal_year_end, accounting_standard, summary, pl
            FROM reports
            WHERE edinet_code = %s
            ORDER BY fiscal_year_end
            """,
            (edinet_code,),
        )
        rows = cur.fetchall()

    if not rows:
        return f"EDINET コード {edinet_code} のレポートが見つかりません。"

    history = {}
    for fy_end, standard, summary, pl in rows:
        summary = summary or {}
        pl = pl or {}
        record = {"会計基準": standard}
        for metric in KEY_METRICS:
            values = summary.get(metric)
            if isinstance(values, dict) and "CurrentYear" in values:
                record[metric] = values["CurrentYear"]
        operating = pl.get("営業利益")
        if isinstance(operating, dict) and "CurrentYear" in operating:
            record["営業利益"] = operating["CurrentYear"]
        if "売上高" not in record:
            for key in PL_REVENUE_KEYS:
                revenue = pl.get(key)
                if isinstance(revenue, dict) and "CurrentYear" in revenue:
                    record[f"売上高（PL: {key}）"] = revenue["CurrentYear"]
                    break
        history[str(fy_end)] = record

    result = {
        "edinet_code": edinet_code,
        "各決算期の当期値": history,
        "最古レポートの5期推移（それ以前の年度の参考値）": rows[0][2],
    }
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


@mcp.tool()
def list_text_sections(edinet_code: str, fiscal_year_end: str = "") -> str:
    """
    有価証券報告書の定性情報（テキストセクション）の一覧と文字数を返します。
    経営戦略・戦術の分析には「経営方針、経営環境及び対処すべき課題等」
    「事業等のリスク」「財政状態、経営成績及びキャッシュ・フローの状況の分析」
    「研究開発活動」「事業の内容」あたりが有用です。

    Args:
        edinet_code: 企業の EDINET コード
        fiscal_year_end: 決算期末日 "YYYY-MM-DD"。省略時は最新のレポート。
    """
    with _connect() as conn, conn.cursor() as cur:
        row = _fetch_report(
            cur, edinet_code, fiscal_year_end or None, "fiscal_year_end, text"
        )

    if row is None:
        return f"レポートが見つかりません: {edinet_code} {fiscal_year_end}"

    fy_end, text_data = row
    if not text_data:
        return f"{edinet_code}（決算期 {fy_end}）にテキストデータがありません。"

    lines = [f"{edinet_code}（決算期 {fy_end}）のテキストセクション一覧\n"]
    for section, value in text_data.items():
        length = len(_strip_html(_flatten_text_value(value)))
        lines.append(f"- {section}（約 {length} 文字）")
    return "\n".join(lines)


@mcp.tool()
def get_text_section(
    edinet_code: str,
    section: str,
    fiscal_year_end: str = "",
    offset: int = 0,
    limit: int = 10000,
) -> str:
    """
    有価証券報告書の指定テキストセクションの本文を返します（HTML タグ除去済み）。
    経営戦略は「経営方針、経営環境及び対処すべき課題等」、
    業績の背景説明は「財政状態、経営成績及びキャッシュ・フローの状況の分析」を読むこと。
    複数年度分を取得して比較すると戦略の変遷がわかります。

    Args:
        edinet_code: 企業の EDINET コード
        section: セクション名（list_text_sections で確認。部分一致でも可）
        fiscal_year_end: 決算期末日 "YYYY-MM-DD"。省略時は最新のレポート。
        offset: 本文の読み出し開始位置（文字数）
        limit: 返す最大文字数（デフォルト 10000）
    """
    with _connect() as conn, conn.cursor() as cur:
        row = _fetch_report(
            cur, edinet_code, fiscal_year_end or None, "fiscal_year_end, text"
        )

    if row is None:
        return f"レポートが見つかりません: {edinet_code} {fiscal_year_end}"

    fy_end, text_data = row
    text_data = text_data or {}

    matched = [name for name in text_data if section in name]
    if not matched:
        return (
            f"セクション「{section}」が見つかりません。"
            f"利用可能: {', '.join(text_data.keys()) or 'なし'}"
        )

    name = matched[0]
    body = _strip_html(_flatten_text_value(text_data[name]))
    chunk = body[offset : offset + limit]
    footer = ""
    if offset + limit < len(body):
        footer = (
            f"\n\n…（続きあり: 全 {len(body)} 文字中 {offset + limit} 文字まで表示。"
            f"offset={offset + limit} で続きを取得できます）"
        )
    return f"# {name}（{edinet_code}, 決算期 {fy_end}）\n\n{chunk}{footer}"


@mcp.tool()
def run_readonly_sql(sql: str) -> str:
    """
    reports テーブルに対して読み取り専用 SQL (SELECT) を実行します。
    上記の専用ツールで足りない集計・比較をしたいときに使います。
    結果は最大 200 行。

    テーブル定義:
        reports(id, doc_id, edinet_code, company_name, security_code,
                accounting_standard, fiscal_year_start DATE, fiscal_year_end DATE,
                is_consolidated BOOL, is_amended BOOL,
                meta JSONB, summary JSONB, bs JSONB, pl JSONB, cf JSONB, text JSONB)

    JSONB の指標は {"指標名": {"CurrentYear": 値, "Prior1Year": 値, ...}} 形式。
    例: summary->'売上高'->>'CurrentYear'

    Args:
        sql: 実行する SELECT 文
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(sql)
            columns = [d.name for d in cur.description] if cur.description else []
            rows = cur.fetchmany(200)
    except psycopg2.Error as e:
        return f"SQL エラー: {e}"
    finally:
        conn.rollback()
        conn.close()

    result = {"columns": columns, "rows": rows, "row_count": len(rows)}
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    mcp.run()
