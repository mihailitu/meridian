#!/bin/bash
# Fill regeneration for the strategy diagnostic report (2026-07-18).
# Re-runs each DEAD strategy ISOLATED (no cross-strategy cash/halt coupling -
# diagnosis, not verification; caveat recorded) over the certified IS and OOS
# windows, dumping fills/orders/positions to CSV after each leg (the fulltest
# DB is wiped by every run, so dumps are the only durable per-trade record).
set -u
cd /home/mihai/workspace/meridian
OUT=data/diagnostics
PY=.venv/bin/python
export PGPASSWORD=axtrade
PSQL="psql -h localhost -p 5433 -U axtrade -d axtrade_backtest"

IS_START=2024-08-01;  IS_END=2025-08-01
OOS_START=2025-08-01; OOS_END=2026-02-01

run_leg() {
  local name=$1 leg=$2 start=$3 end=$4; shift 4
  echo "=== $name $leg ($start -> $end) start $(date -Is)" >> $OUT/runner.log
  $PY -m axtrade.fulltest run --start "$start" --end "$end" --capital 100000 \
      "$@" > "$OUT/${name}_${leg}.log" 2>&1
  local rc=$?
  echo "=== $name $leg exit=$rc $(date -Is)" >> $OUT/runner.log
  if [ $rc -eq 0 ]; then
    $PSQL -c "\copy (SELECT strategy_id,symbol,side,quantity,price,commission,filled_at FROM fills ORDER BY filled_at) TO '$PWD/$OUT/${name}_${leg}_fills.csv' CSV HEADER" >> $OUT/runner.log 2>&1
    $PSQL -c "\copy (SELECT strategy_id,symbol,side,order_type,quantity,filled_quantity,avg_fill_price,status,created_at FROM orders ORDER BY created_at) TO '$PWD/$OUT/${name}_${leg}_orders.csv' CSV HEADER" >> $OUT/runner.log 2>&1
    $PSQL -c "\copy (SELECT * FROM positions) TO '$PWD/$OUT/${name}_${leg}_positions.csv' CSV HEADER" >> $OUT/runner.log 2>&1
  fi
}

for strat in mean_reversion multi_timeframe overnight_reversal; do
  run_leg "$strat" is  "$IS_START" "$IS_END"   --symbols AAPL MSFT GOOGL AMZN NVDA --no-discovery --strategies "$strat"
  run_leg "$strat" oos "$OOS_START" "$OOS_END" --symbols AAPL MSFT GOOGL AMZN NVDA --no-discovery --strategies "$strat"
done

run_leg pairs is  "$IS_START" "$IS_END"   --symbols AAPL MSFT --no-discovery --strategies pairs
run_leg pairs oos "$OOS_START" "$OOS_END" --symbols AAPL MSFT --no-discovery --strategies pairs

run_leg discovery_momentum is  "$IS_START" "$IS_END"   --symbols AAPL MSFT GOOGL AMZN NVDA --strategies discovery_momentum
run_leg discovery_momentum oos "$OOS_START" "$OOS_END" --symbols AAPL MSFT GOOGL AMZN NVDA --strategies discovery_momentum

touch $OUT/ALL_DONE
