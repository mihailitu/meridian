"""IS/OOS comparison: build a side-by-side report from two FullBacktestResults."""

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .types import FullBacktestResult, StrategyResult


@dataclass
class StrategyComparison:
    """Side-by-side IS vs OOS metrics for one strategy."""

    strategy_id: str
    strategy_type: str
    is_trades: int
    is_win_rate: float
    is_profit_factor: Optional[float]
    is_total_pnl: float
    is_sharpe: Optional[float]
    is_max_drawdown: Optional[float]
    oos_trades: int
    oos_win_rate: float
    oos_profit_factor: Optional[float]
    oos_total_pnl: float
    oos_sharpe: Optional[float]
    oos_max_drawdown: Optional[float]
    pnl_delta: float
    pf_delta: Optional[float]
    wr_delta: float
    verdict: str  # is_unprofitable | broken | degraded | holds_up


@dataclass
class OOSComparison:
    """Full IS/OOS comparison covering the portfolio and every strategy."""

    label: Optional[str]
    is_period: tuple[date, date]
    oos_period: tuple[date, date]
    symbols: list[str]
    initial_capital: float
    discovery_enabled: bool
    strategy_overrides: dict[str, dict]
    per_strategy: list[StrategyComparison] = field(default_factory=list)
    is_overall: dict[str, Optional[float]] = field(default_factory=dict)
    oos_overall: dict[str, Optional[float]] = field(default_factory=dict)


VERDICT_IS_UNPROFITABLE = "is_unprofitable"
VERDICT_BROKEN = "broken"
VERDICT_DEGRADED = "degraded"
VERDICT_HOLDS_UP = "holds_up"


def _classify(
    is_pf: Optional[float],
    is_pnl: float,
    is_sharpe: Optional[float],
    oos_pf: Optional[float],
    oos_pnl: float,
    oos_sharpe: Optional[float],
) -> str:
    """Heuristic IS→OOS survival verdict. First-draft thresholds; the underlying
    numbers are the source of truth — verdict is for quick scanning only.

    - is_unprofitable: IS itself failed (PF < 1.0 or PnL <= 0).
    - broken: IS profitable, OOS PF < 1.0 or OOS PnL < 0.
    - degraded: both profitable, OOS PF < 0.75 × IS PF OR OOS Sharpe < 0.50 × IS Sharpe.
    - holds_up: otherwise.
    """
    if is_pnl <= 0 or is_pf is None or is_pf < 1.0:
        return VERDICT_IS_UNPROFITABLE
    if oos_pnl < 0 or oos_pf is None or oos_pf < 1.0:
        return VERDICT_BROKEN
    # Both IS and OOS profitable
    pf_degraded = oos_pf < 0.75 * is_pf
    sharpe_degraded = (
        is_sharpe is not None
        and oos_sharpe is not None
        and is_sharpe > 0
        and oos_sharpe < 0.50 * is_sharpe
    )
    if pf_degraded or sharpe_degraded:
        return VERDICT_DEGRADED
    return VERDICT_HOLDS_UP


def _delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b


def _pair_strategies(
    is_results: list[StrategyResult],
    oos_results: list[StrategyResult],
) -> list[tuple[StrategyResult, StrategyResult]]:
    """Pair strategies across the two runs by strategy_id. Strategies that
    appear in only one run still get paired with a zero-trade placeholder so
    the comparison row exists.
    """
    by_id_is = {s.strategy_id: s for s in is_results}
    by_id_oos = {s.strategy_id: s for s in oos_results}
    all_ids = sorted(set(by_id_is) | set(by_id_oos))
    pairs: list[tuple[StrategyResult, StrategyResult]] = []
    for sid in all_ids:
        is_s = by_id_is.get(sid) or StrategyResult(
            strategy_id=sid,
            strategy_type=by_id_oos[sid].strategy_type,
        )
        oos_s = by_id_oos.get(sid) or StrategyResult(
            strategy_id=sid,
            strategy_type=by_id_is[sid].strategy_type,
        )
        pairs.append((is_s, oos_s))
    return pairs


def build_comparison(
    is_result: FullBacktestResult,
    oos_result: FullBacktestResult,
    label: Optional[str] = None,
) -> OOSComparison:
    """Build an OOSComparison from two completed FullBacktestResults."""
    is_cfg = is_result.config
    oos_cfg = oos_result.config

    cmp = OOSComparison(
        label=label,
        is_period=(is_cfg.start, is_cfg.end),
        oos_period=(oos_cfg.start, oos_cfg.end),
        symbols=list(is_cfg.symbols),
        initial_capital=is_cfg.initial_capital,
        discovery_enabled=is_cfg.discovery_enabled,
        strategy_overrides=dict(is_cfg.strategy_overrides),
        is_overall={
            "total_pnl": is_result.total_pnl,
            "profit_factor": is_result.overall_profit_factor,
            "sharpe": is_result.overall_sharpe,
            "max_drawdown": is_result.overall_max_drawdown,
            "win_rate": is_result.overall_win_rate,
            "total_trades": float(is_result.overall_total_trades),
        },
        oos_overall={
            "total_pnl": oos_result.total_pnl,
            "profit_factor": oos_result.overall_profit_factor,
            "sharpe": oos_result.overall_sharpe,
            "max_drawdown": oos_result.overall_max_drawdown,
            "win_rate": oos_result.overall_win_rate,
            "total_trades": float(oos_result.overall_total_trades),
        },
    )

    for is_s, oos_s in _pair_strategies(
        is_result.strategy_results, oos_result.strategy_results
    ):
        verdict = _classify(
            is_pf=is_s.profit_factor,
            is_pnl=is_s.total_pnl,
            is_sharpe=is_s.sharpe_ratio,
            oos_pf=oos_s.profit_factor,
            oos_pnl=oos_s.total_pnl,
            oos_sharpe=oos_s.sharpe_ratio,
        )
        cmp.per_strategy.append(StrategyComparison(
            strategy_id=is_s.strategy_id,
            strategy_type=is_s.strategy_type or oos_s.strategy_type,
            is_trades=is_s.trade_count,
            is_win_rate=is_s.win_rate,
            is_profit_factor=is_s.profit_factor,
            is_total_pnl=is_s.total_pnl,
            is_sharpe=is_s.sharpe_ratio,
            is_max_drawdown=is_s.max_drawdown,
            oos_trades=oos_s.trade_count,
            oos_win_rate=oos_s.win_rate,
            oos_profit_factor=oos_s.profit_factor,
            oos_total_pnl=oos_s.total_pnl,
            oos_sharpe=oos_s.sharpe_ratio,
            oos_max_drawdown=oos_s.max_drawdown,
            pnl_delta=oos_s.total_pnl - is_s.total_pnl,
            pf_delta=_delta(oos_s.profit_factor, is_s.profit_factor),
            wr_delta=oos_s.win_rate - is_s.win_rate,
            verdict=verdict,
        ))

    return cmp


def _fmt_dollar(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"${v:,.2f}"


def _fmt_pf(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v:.2f}"


def _fmt_ratio(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v:+.2f}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:+.1f}%"


def format_comparison_text(c: OOSComparison) -> str:
    """Format an OOSComparison as a human-readable text report."""
    lines: list[str] = []
    lines.append("=" * 110)
    lines.append("IS / OOS COMPARISON")
    lines.append("=" * 110)
    lines.append("")
    lines.append(f"Label:            {c.label or '(none)'}")
    is_days = (c.is_period[1] - c.is_period[0]).days
    oos_days = (c.oos_period[1] - c.oos_period[0]).days
    lines.append(f"IS Period:        {c.is_period[0]} → {c.is_period[1]} ({is_days}d)")
    lines.append(f"OOS Period:       {c.oos_period[0]} → {c.oos_period[1]} ({oos_days}d)")
    sym_preview = ", ".join(c.symbols[:10])
    if len(c.symbols) > 10:
        sym_preview += f" ... ({len(c.symbols)} total)"
    lines.append(f"Symbols:          {sym_preview}")
    lines.append(f"Initial Capital:  ${c.initial_capital:,.2f}")
    lines.append(f"Discovery:        {'enabled' if c.discovery_enabled else 'disabled'}")
    if c.strategy_overrides:
        lines.append("Overrides:")
        for stype, patch in c.strategy_overrides.items():
            lines.append(f"                  {stype}: {patch}")
    else:
        lines.append("Overrides:        (none)")
    lines.append("")

    # Overall portfolio table
    lines.append("-" * 110)
    lines.append("Overall Portfolio")
    lines.append("-" * 110)
    is_pnl = c.is_overall.get("total_pnl") or 0.0
    oos_pnl = c.oos_overall.get("total_pnl") or 0.0
    is_pf = c.is_overall.get("profit_factor")
    oos_pf = c.oos_overall.get("profit_factor")
    is_sh = c.is_overall.get("sharpe")
    oos_sh = c.oos_overall.get("sharpe")
    lines.append(f"{'Metric':<20}{'IS':>20}{'OOS':>20}{'Δ':>20}")
    lines.append(
        f"{'Total P&L':<20}"
        f"{_fmt_dollar(is_pnl):>20}"
        f"{_fmt_dollar(oos_pnl):>20}"
        f"{_fmt_dollar(oos_pnl - is_pnl):>20}"
    )
    lines.append(
        f"{'Profit Factor':<20}"
        f"{_fmt_pf(is_pf):>20}"
        f"{_fmt_pf(oos_pf):>20}"
        f"{_fmt_pf(_delta(oos_pf, is_pf)):>20}"
    )
    lines.append(
        f"{'Sharpe(rf=0)':<20}"
        f"{_fmt_pf(is_sh):>20}"
        f"{_fmt_pf(oos_sh):>20}"
        f"{_fmt_pf(_delta(oos_sh, is_sh)):>20}"
    )
    lines.append("")

    # Per-strategy table
    lines.append("-" * 110)
    lines.append("Per Strategy")
    lines.append("-" * 110)
    header = (
        f"{'strategy_id':<26}"
        f"{'IS_Tr':>7}{'IS_WR':>8}{'IS_PF':>7}{'IS_PnL':>13}"
        f"{'OOS_Tr':>7}{'OOS_WR':>8}{'OOS_PF':>7}{'OOS_PnL':>13}"
        f"  {'Verdict':<18}"
    )
    lines.append(header)
    for s in c.per_strategy:
        lines.append(
            f"{s.strategy_id:<26}"
            f"{s.is_trades:>7}{_fmt_pct(s.is_win_rate):>8}"
            f"{_fmt_pf(s.is_profit_factor):>7}{_fmt_dollar(s.is_total_pnl):>13}"
            f"{s.oos_trades:>7}{_fmt_pct(s.oos_win_rate):>8}"
            f"{_fmt_pf(s.oos_profit_factor):>7}{_fmt_dollar(s.oos_total_pnl):>13}"
            f"  {s.verdict.upper():<18}"
        )
    lines.append("")
    lines.append("Verdicts are heuristic (PF<1 IS=unprofitable; OOS PF<1 or PnL<0=broken;")
    lines.append("OOS PF<75% IS or OOS Sharpe<50% IS=degraded; else=holds_up).")
    lines.append("Check the underlying metrics for decisions.")
    lines.append("=" * 110)
    return "\n".join(lines)


def format_comparison_json(c: OOSComparison) -> str:
    """Serialize an OOSComparison to a stable JSON string."""

    def _default(o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        raise TypeError(f"Cannot serialize {type(o).__name__}")

    return json.dumps(asdict(c), indent=2, default=_default)


def write_comparison_report(
    c: OOSComparison,
    output_dir: str = "data/fulltest_results",
) -> tuple[str, str]:
    """Write text and JSON comparison reports to disk. Returns the two paths."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = out / f"oos_comparison_{ts}.txt"
    json_path = out / f"oos_comparison_{ts}.json"
    txt_path.write_text(format_comparison_text(c))
    json_path.write_text(format_comparison_json(c))
    return str(txt_path), str(json_path)
