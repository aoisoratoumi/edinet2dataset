# edinet2dataset
📚 [Paper](https://arxiv.org/abs/2506.08762) | 📝 [Blog](https://sakana.ai/edinet-bench/) | 📁 [Dataset](https://huggingface.co/datasets/SakanaAI/EDINET-Bench) | 🧑‍💻 [Code](https://github.com/SakanaAI/EDINET-Bench)

edinet2dataset is a tool to construct financial datasets using [EDINET](https://disclosure2.edinet-fsa.go.jp). 

edinet2dataset has two classes to build Japanese financial dataset using EDINET.
- **Downloader**: Download financial reports of Japanese listed companies using the EDINET API.
- **Parser**: Extract key items such as the balance sheet (BS), cash flow statement (CF), profit and loss statement (PL), summary, and text from the downloaded TSV reports.


edinet2dataset is used to construct [EDINET-Bench](https://huggingface.co/datasets/SakanaAI/EDINET-Bench), a challenging Japanese financial benchmark dataset.

## Installation

Install the dependencies using uv.
```bash
uv sync
```

To use EDINET-API, configure your EDINET-API key in a .env file.
Please refer to the [official documentation](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0110.html) to obtain the API key.

## Basic Usage

- Search for a company name using a substring match query.
  
```bash
$ python src/edinet2dataset/downloader.py --query トヨタ
```
<table border="1" cellspacing="0" cellpadding="5">
  <thead>
    <tr>
      <th>提出者名</th>
      <th>ＥＤＩＮＥＴコード</th>
      <th>提出者業種</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>トヨタ紡織株式会社</td>
      <td>E00540</td>
      <td>輸送用機器</td>
    </tr>
    <tr>
      <td>トヨタ自動車株式会社</td>
      <td>E02144</td>
      <td>輸送用機器</td>
    </tr>
    <tr>
      <td>トヨタファイナンス株式会社</td>
      <td>E05031</td>
      <td>サービス業</td>
    </tr>
    <tr>
      <td>トヨタ モーター クレジット コーポレーション</td>
      <td>E05904</td>
      <td>外国法人・組合</td>
    </tr>
    <tr>
      <td>トヨタ ファイナンス オーストラリア リミテッド</td>
      <td>E05954</td>
      <td>外国法人・組合</td>
    </tr>
    <tr>
      <td>トヨタ モーター ファイナンス（ネザーランズ）ビーブイ</td>
      <td>E20989</td>
      <td>外国法人・組合</td>
    </tr>
    <tr>
      <td>トヨタファイナンシャルサービス株式会社</td>
      <td>E23700</td>
      <td>内国法人・組合（有価証券報告書等の提出義務者以外）</td>
    </tr>
  </tbody>
</table>


- Download the annual report submitted by Toyota Motor Corporation for the period from June 1, 2024, to June 28, 2024.

```bash
$ uv run python src/edinet2dataset/downloader.py --start_date 2024-06-01 --end_date 2024-06-28 --company_name "トヨタ自動車株式会社" --doc_type annual  
Downloading documents (2024-06-01 - 2024-06-28): 100%|███████████████████████████████████████████| 28/28 [00:02<00:00,  9.76it/s]
```

- Extract balance sheet (BS) items from the annual report.

```bash
$ uv run python src/edinet2dataset/parser.py --file_path data/E02144/S100TR7I.tsv --category_list BS
2025-04-26 22:03:16.026 | INFO     | __main__:parse_tsv:130 - Found 2179 unique elements in data/E02144/S100TR7I.tsv
{'現金及び預金': {'Prior1Year': '2965923000000', 'CurrentYear': '4278139000000'}, '現金及び現金同等物': {'Prior2Year': '6113655000000', 'Prior1Year': '1403311000000', 'CurrentYear': '9412060000000'}, '売掛金': {'Prior1Year': '1665651000000', 'CurrentYear': '1888956000000'}, '有価証券': {'Prior1Year': '1069082000000', 'CurrentYear': '3938698000000'}, '商品及び製品': {'Prior1Year': '271851000000', 'CurrentYear': '257113000000'}
```


## MCP Server

edinet2dataset provides an [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that lets Claude answer questions like *"営業利益が伸びている会社を大きい順から挙げてください"* directly from EDINET data.

### Setup

**Step 1.** Build the profit index (run once after downloading the corpus):

```bash
uv run python scripts/build_profit_index.py
```

This parses all TSV files in `edinet_corpus/annual/` and saves a pre-computed index to `edinet_corpus/profit_index.json`.

**Step 2.** Register the MCP server with Claude Code by adding the following to `.claude/settings.json` in this project (already included in the repository):

```json
{
  "mcpServers": {
    "edinet2dataset": {
      "command": "uv",
      "args": ["run", "python", "src/edinet2dataset/mcp_server.py"],
      "cwd": "/path/to/edinet2dataset"
    }
  }
}
```

**Step 3.** Restart Claude Code. Run `/mcp` to confirm `edinet2dataset` is connected.

### Available Tools

| Tool | Description |
|---|---|
| `rank_by_operating_profit_growth` | Ranks companies by operating profit growth rate or growth amount |
| `get_company_financials` | Returns BS / PL / CF data for a given EDINET code |
| `search_company_by_name` | Searches the index by company name to find its EDINET code |

### Example Queries

```
営業利益が伸びている会社を大きい順から20社挙げてください
トヨタ自動車の直近の財務データを見せてください
"ソニー"で会社を検索してください
```

## PostgreSQL MCP Server

For deeper company research (financial history across all reported years, plus qualitative sections like management strategy and R&D), edinet2dataset also provides an MCP server backed by the PostgreSQL `reports` table populated by `scripts/load_to_postgres.py`.

### Setup

**Step 1.** Load the corpus into PostgreSQL (see [Load into PostgreSQL](#load-into-postgresql) above).

**Step 2.** The server is already registered in `.mcp.json` at the project root:

```json
{
  "mcpServers": {
    "edinet-postgres": {
      "command": "uv",
      "args": ["run", "python", "src/edinet2dataset/pg_mcp_server.py"]
    }
  }
}
```

Requires `DATABASE_URL` to be set (via `.env` or environment variable).

**Step 3.** Run `/mcp` in Claude Code to confirm `edinet-postgres` is connected.

### Available Tools

| Tool | Description |
|---|---|
| `search_company` | Fuzzy-searches company names to find their EDINET code |
| `list_reports` | Lists all reports stored for a given EDINET code |
| `get_financial_history` | Returns revenue, operating/ordinary/net profit, ROE, cash flows etc. across every stored fiscal year |
| `list_text_sections` | Lists the qualitative text sections (business overview, management policy, R&D, risks, etc.) available for a report |
| `get_text_section` | Returns the (HTML-stripped, paginated) text of a given section |
| `run_readonly_sql` | Runs an arbitrary read-only `SELECT` against the `reports` table for custom aggregations/comparisons |

### Example Queries

```
サイバーダインについて調べてください
トヨタ自動車の過去10年の経営成績と経営戦略をレポートしてください
ランダムに10社の経営成績、経営戦略、戦術を調べてレポートしてください
```

## Claude Code Skills

This repository ships two Claude Code skills under `.claude/skills/`:

| Skill | Triggers on | What it does |
|---|---|---|
| `edinet-download` | "EDINETから最新までダウンロードして" etc. | Runs `edinet_corpus.sh` to fetch new filings, then loads them into PostgreSQL via `load_to_postgres.py` so the DB stays current |
| `company-research` | "〇〇について調べて" / "〇〇を分析して" | Uses the `edinet-postgres` MCP tools to research a company's financial performance (including revenue/operating/ordinary/net profit trends), management strategy and tactics, and produce a report |

## Reproduce EDINET-Bench

You can reproduce [EDINET-Bench](https://huggingface.co/datasets/SakanaAI/EDINET-Bench) by running following commands. 

> [!NOTE]  
> Since only the past 10 years of annual reports are available via the EDINET API, the time window used to construct the dataset shifts with each execution. As a result, datasets generated at different times may not be identical.
### Construct EDINET-Corpus
Download all annual reports for the year 2024.

```bash
$ python scripts/prepare_edinet_corpus.py --doc_type annual --start_date 2024-01-01 --end_date 2025-01-01
```

Download securities reports spanning 10 years for approximately 4,000 companies from EDINET.
```bash
$ bash edinet_corpus.sh
```

`edinet_corpus.sh` downloads month by month from the start year (default `2026`, override with `bash edinet_corpus.sh 2020`) through **today's date**, so re-running it later fetches only the newly published reports. Already-downloaded documents are skipped automatically, so it is safe to run repeatedly (e.g. on a schedule) to keep the corpus up to date.

> [!NOTE]
> Please be careful not to send too many requests in parallel, as downloading reports from the past 10 years could place a significant load on EDINET.

### Load into PostgreSQL

Load the downloaded corpus into a PostgreSQL `reports` table (one row per document, with structured columns plus JSONB columns for `meta`/`summary`/`bs`/`pl`/`cf`/`text`):

```bash
$ uv run python scripts/load_to_postgres.py --corpus_dir edinet_corpus/annual
```

Set `DATABASE_URL` (e.g. `postgresql://user:password@localhost:5432/edinet`) via `.env` or `--database_url`. The load is an upsert keyed on `doc_id`, so re-running it after downloading new reports only inserts/updates the diff.


You will get the following directories
```
edinet_corpus
├── annual
│   ├── E00004
│   │   ├── S1005SBA.json
│   │   ├── S1005SBA.pdf
│   │   ├── S1005SBA.tsv
│   │   ├── S1008JYI.json
│   │   ├── S1008JYI.pdf
│   │   ├── S1008JYI.tsv
```

### Construct Accounting Fraud Detection Task

Build a benchmark to detect accounting fraud in the securities report of a given fiscal year.
```bash
$ python scripts/fraud_detection/prepare_fraud.py
$ python scripts/fraud_detection/prepare_nonfraud.py
$ python scripts/fraud_detection/prepare_dataset.py
```


You can analyze the amended report classified as fraud-related by running the following command:
```bash
$ python scripts/fraud_detection/analyze_fraud_explanation.py 
```


### Construct Earnings Forecasting Task

Build a benchmark to forecast the following year’s profit based on the securities report of a given fiscal year.
```bash
$ python  scripts/profit_forecast/prepare_dataset.py 
```


### Construct Industry Prediction Task

Buid a benchmark to predict industry given an annual report.
```bash
$ python scripts/industry_prediction/prepare_dataset.py 
```

## Citation
```
@inproceedings{
sugiura2026edinetbench,
title={{EDINET}-Bench: Evaluating {LLM}s on Complex Financial Tasks using Japanese Financial Statements},
author={Issa Sugiura and Takashi Ishida and Taro Makino and Chieko Tazuke and Takanori Nakagawa and Kosuke Nakago and David Ha},
booktitle={The Fourteenth International Conference on Learning Representations},
year={2026},
url={https://openreview.net/forum?id=Dxns0cj15A}
}
```

## Acknowledgement
We acknowledge [edgar-crawler](https://github.com/lefterisloukas/edgar-crawler) as an inspiration for our tool.
We also thank [EDINET](https://disclosure2.edinet-fsa.go.jp), which served as the primary resource for constructing our benchmark.
