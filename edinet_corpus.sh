#!/bin/bash
# EDINET から start_year の1月〜実行日（今日）までの書類を月単位でダウンロードする。
# Usage: bash edinet_corpus.sh [start_year]   (デフォルト: 2026)
# ダウンロード済みの書類は自動でスキップされるため、再実行すれば最新分だけ取得される。

start_year="${1:-2026}"

doc_types=(
    "annual"
    "quarterly"
    # "semiannual"
    # "annual_amended"
    # "quarterly_amended"
    # "semiannual_amended"
)

today=$(date +%F)
current_year=$(date +%Y)

for year in $(seq "$start_year" "$current_year")
do
    for doc_type in "${doc_types[@]}"
    do
    for month in {1..12}
    do
        start_date="${year}-$(printf "%02d" "$month")-01"

        # 未来の月はスキップ
        if [[ "$start_date" > "$today" ]]; then
            continue
        fi

        # 月が12の場合は翌年の1月にする
        if [ "$month" -eq 12 ]; then
        end_date="$((year + 1))-01-01"
        else
        end_date="${year}-$(printf "%02d" $((month + 1)))-01"
        fi

        # 当月は今日まで取得する（end_date はその日を含む）
        if [[ "$end_date" > "$today" ]]; then
            end_date="$today"
        fi

        echo "doc_type: $doc_type, start_date: $start_date, end_date: $end_date"
        python scripts/prepare_edinet_corpus.py --doc_type "$doc_type" --start_date "$start_date" --end_date "$end_date" --max_workers 3
    done
    done
done
