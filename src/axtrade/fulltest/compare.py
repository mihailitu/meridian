"""Compare two fulltest JSON result files side-by-side."""

import json
from pathlib import Path
from typing import Optional


def _fmt_int(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{int(v)}"


def _fmt_dollar(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"${v:,.2f}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v:+.2f}%"


def _fmt_ratio(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v:.2f}"


def _delta_str(
    baseline: Optional[float],
    current: Optional[float],
    fmt_fn=_fmt_dollar,
) -> str:
    """Format 'baseline -> current (delta)' string."""
    b_str = fmt_fn(baseline)
    c_str = fmt_fn(current)
    if baseline is not None and current is not None:
        delta = current - baseline
        d_str = fmt_fn(delta)
        return f"{b_str} -> {c_str} ({d_str})"
    return f"{b_str} -> {c_str}"


def compare_results(baseline_path: str, current_path: str) -> str:
    """Load two JSON result files and return a comparison report."""
    with open(baseline_path) as f:
        baseline = json.load(f)
    with open(current_path) as f:
        current = json.load(f)

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("FULLTEST COMPARISON")
    lines.append("=" * 70)
    lines.append(f"  Baseline: {Path(baseline_path).name}")
    lines.append(f"  Current:  {Path(current_path).name}")
    lines.append("")

    # Portfolio-level comparison
    lines.append("-" * 70)
    lines.append("PORTFOLIO")
    lines.append("-" * 70)

    ba = baseline.get("analytics", {})
    ca = current.get("analytics", {})
    br = baseline.get("results", {})
    cr = current.get("results", {})

    metrics = [
        ("Total P&L", br.get("total_pnl"), cr.get("total_pnl"), _fmt_dollar),
        ("Return %", br.get("return_pct"), cr.get("return_pct"), _fmt_pct),
        ("Sharpe Ratio", ba.get("sharpe_ratio"), ca.get("sharpe_ratio"), _fmt_ratio),
        ("Max Drawdown", ba.get("max_drawdown"), ca.get("max_drawdown"), _fmt_pct),
        ("Win Rate", ba.get("win_rate"), ca.get("win_rate"), _fmt_pct),
        ("Total Trades", ba.get("total_trades"), ca.get("total_trades"), _fmt_int),
        ("Profit Factor", ba.get("profit_factor"), ca.get("profit_factor"), _fmt_ratio),
        ("Avg Trade P&L", ba.get("avg_trade_pnl"), ca.get("avg_trade_pnl"), _fmt_dollar),
        ("Total Commission", ba.get("total_commission"), ca.get("total_commission"), _fmt_dollar),
    ]

    for label, bv, cv, fmt_fn in metrics:
        lines.append(f"  {label:20s} {_delta_str(bv, cv, fmt_fn)}")

    lines.append("")

    # Per-strategy comparison
    b_strats = {s["strategy_id"]: s for s in baseline.get("strategies", [])}
    c_strats = {s["strategy_id"]: s for s in current.get("strategies", [])}
    all_ids = sorted(set(b_strats.keys()) | set(c_strats.keys()))

    if all_ids:
        lines.append("-" * 70)
        lines.append("PER-STRATEGY")
        lines.append("-" * 70)

        for sid in all_ids:
            bs = b_strats.get(sid, {})
            cs = c_strats.get(sid, {})
            stype = cs.get("strategy_type") or bs.get("strategy_type", "unknown")
            lines.append("")
            lines.append(f"  {sid} ({stype})")
            lines.append(f"  {'~' * 40}")

            strat_metrics = [
                ("Total P&L", bs.get("total_pnl"), cs.get("total_pnl"), _fmt_dollar),
                ("Trades", bs.get("trade_count"), cs.get("trade_count"), _fmt_int),
                ("Win Rate", bs.get("win_rate"), cs.get("win_rate"), _fmt_pct),
                ("Sharpe", bs.get("sharpe_ratio"), cs.get("sharpe_ratio"), _fmt_ratio),
                ("Profit Factor", bs.get("profit_factor"), cs.get("profit_factor"), _fmt_ratio),
                ("Avg Trade P&L", bs.get("avg_trade_pnl"), cs.get("avg_trade_pnl"), _fmt_dollar),
                ("Commission", bs.get("total_commission"), cs.get("total_commission"), _fmt_dollar),
            ]

            for label, bv, cv, fmt_fn in strat_metrics:
                lines.append(f"    {label:20s} {_delta_str(bv, cv, fmt_fn)}")

    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines)
