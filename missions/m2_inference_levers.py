"""M2 — Inference Cost Levers: $/1M-token, batch x cache x cascade (deck §7).

Your Turn #3: prompt caching only where reuse clears the write-premium break-even.
Your Turn #4: reasoning budget — split $ / Wh of reasoning traffic and cap it.

Run: python missions/m2_inference_levers.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from collections import defaultdict
from missions._common import load_csv, num
from finops import pricing, sustainability

# $/1M tokens (input, output) — illustrative 2026.
MODEL_PRICES = {"small": (0.20, 0.40), "large": (3.00, 15.00)}
CACHE_WRITE_COST = 1.25     # Anthropic 5-min TTL: cache write = 1.25x input price
REASONING_KEEP_FRAC = 0.25  # budget: only the hardest 25% of reasoning asks keep thinking
SWEEP_KEEP_FRACS = (1.0, 0.5, 0.25, 0.10, 0.0)


def _budget(rows: list, keep_frac: float, plain_out: int) -> list:
    """(output_tokens, is_reasoning) per row after the reasoning budget.

    Routing rule: reasoning stays on only for the longest-prompt `keep_frac` of
    reasoning requests; the rest are answered like plain requests (output capped
    at the plain-traffic mean, no 80x energy multiplier).
    """
    # ponytail: input length is the complexity proxy; swap for a router/classifier score when one exists
    reasoning = sorted((r for r in rows if r["is_reasoning"]), key=lambda r: r["input_tokens"], reverse=True)
    keep = {id(r) for r in reasoning[:round(len(reasoning) * keep_frac)]}
    return [(r["output_tokens"], True) if id(r) in keep
            else (min(r["output_tokens"], plain_out), False) if r["is_reasoning"]
            else (r["output_tokens"], False)
            for r in rows]


def _wh(rows: list, outs: list) -> float:
    return sum(sustainability.wh_per_query(r["input_tokens"] + o, is_reasoning=reas)
               for r, (o, reas) in zip(rows, outs))


def run(verbose: bool = True) -> dict:
    rows = load_csv("token_usage.csv")
    for r in rows:
        for k in ("input_tokens", "output_tokens", "cached_input_tokens", "is_batch", "is_reasoning"):
            r[k] = int(num(r[k]))
    total_tokens = sum(r["input_tokens"] + r["output_tokens"] for r in rows)

    # --- Your Turn #3: is caching worth the write premium, per project? ---
    # A prefix written once and read N times gives hit rate N/(N+1)  ->  N = hit/(1-hit).
    tok = defaultdict(lambda: [0, 0])
    for r in rows:
        tok[r["project"]][0] += r["cached_input_tokens"]
        tok[r["project"]][1] += r["input_tokens"]
    break_even = pricing.cache_break_even_reads(CACHE_WRITE_COST)
    cache_on, cache_rows = {}, []
    for proj, (cached, inp) in sorted(tok.items()):
        hit = cached / inp if inp else 0.0
        reads = hit / (1 - hit) if hit < 1 else float("inf")
        cache_on[proj] = pricing.cache_is_worth_it(reads, CACHE_WRITE_COST)
        cache_rows.append({"project": proj or "(untagged)", "hit_rate": round(hit, 3), "avg_reads": round(reads, 2),
                           "cache_on": cache_on[proj]})

    plain_out = round(sum(r["output_tokens"] for r in rows if not r["is_reasoning"])
                      / max(1, sum(1 for r in rows if not r["is_reasoning"])))
    raw_outs = [(r["output_tokens"], bool(r["is_reasoning"])) for r in rows]

    def cost(r, out, cascade=False, batch=False, cache=None) -> float:
        pin, pout = MODEL_PRICES[r["route_tier"] if cascade else "large"]
        use_cache = cache == "all" or (cache == "gated" and cache_on[r["project"]])
        return pricing.request_cost(
            r["input_tokens"], out, pin, pout,
            cached_in=r["cached_input_tokens"] if use_cache else 0,
            cache_write_cost=CACHE_WRITE_COST if use_cache else 1.0,
            batch=batch and bool(r["is_batch"]))

    def bill(outs=raw_outs, **lever) -> float:
        return sum(cost(r, out, **lever) for r, (out, _) in zip(rows, outs))

    # Cumulative levers. Denominator stays the requested workload's tokens so steps compare.
    budget_outs = _budget(rows, REASONING_KEEP_FRAC, plain_out)
    steps = [
        ("Baseline: all on large, no cache/batch", bill()),
        ("+ Cascade (route_tier)", bill(cascade=True)),
        ("+ Batch API", bill(cascade=True, batch=True)),
        ("+ Prompt cache (gated by break-even)", bill(cascade=True, batch=True, cache="gated")),
        (f"+ Reasoning budget (keep {REASONING_KEEP_FRAC:.0%})",
         bill(cascade=True, batch=True, cache="gated", outs=budget_outs)),
    ]
    steps = [{"lever": n, "daily": round(c, 2),
              "per_m": round(pricing.dollars_per_million(c, total_tokens), 3)} for n, c in steps]
    base_cost = bill()
    opt_cost = bill(cascade=True, batch=True, cache="gated", outs=budget_outs)
    cache_all = round(bill(cascade=True, batch=True, cache="all"), 2)
    cache_gated = round(bill(cascade=True, batch=True, cache="gated"), 2)

    # --- Your Turn #4: reasoning share of $ and Wh, and the budget sweep ---
    pre_budget = bill(cascade=True, batch=True, cache="gated")
    reas_rows = [r for r in rows if r["is_reasoning"]]
    reas_cost = sum(cost(r, r["output_tokens"], cascade=True, batch=True, cache="gated") for r in reas_rows)
    wh_total = _wh(rows, raw_outs)
    wh_reas = _wh(reas_rows, [(r["output_tokens"], True) for r in reas_rows])
    sweep = []
    for k in SWEEP_KEEP_FRACS:
        outs = _budget(rows, k, plain_out)
        c, wh = bill(cascade=True, batch=True, cache="gated", outs=outs), _wh(rows, outs)
        sweep.append({"keep_frac": k, "reasoning_traffic_pct": round(sum(x for _, x in outs) / len(rows) * 100, 1),
                      "daily": round(c, 2), "saved_usd": round(pre_budget - c, 2),
                      "wh": round(wh), "saved_wh": round(wh_total - wh)})
    reasoning = {
        "traffic_pct": round(len(reas_rows) / len(rows) * 100, 1),
        "cost_pct": round(reas_cost / pre_budget * 100, 1),
        "wh_pct": round(wh_reas / wh_total * 100, 1),
        "daily_usd": round(reas_cost, 2), "daily_wh": round(wh_reas),
        "plain_out": plain_out, "sweep": sweep,
        "wh_before": round(wh_total), "wh_after": round(_wh(rows, budget_outs)),
    }

    base_pm = pricing.dollars_per_million(base_cost, total_tokens)
    opt_pm = pricing.dollars_per_million(opt_cost, total_tokens)
    savings_pct = (1 - opt_cost / base_cost) * 100 if base_cost else 0.0

    if verbose:
        print("== M2 Inference Cost Levers ==")
        print(f"requests={len(rows)}  tokens={total_tokens:,}")
        for s in steps:
            print(f"  {s['lever']:<42} ${s['daily']:>8,.2f}/day   ${s['per_m']:.3f}/1M-token")
        print(f"savings   : {savings_pct:.1f}%  (cascade + batch + gated cache + reasoning budget)")
        print(f"discount stack (batch + 100% cache): {pricing.discount_stack(batch=True, cache_hit_frac=1.0):.3f} of naive")
        print(f"\n-- Cache economics (write {CACHE_WRITE_COST}x, read 0.1x): break-even = {break_even:.2f} reads/write --")
        for c in cache_rows:
            print(f"  {c['project']:<13} hit={c['hit_rate']:.1%}  reads/write={c['avg_reads']:.2f}  cache={'ON' if c['cache_on'] else 'OFF'}")
        print(f"  cache everywhere ${cache_all:,.2f}/day  vs gated ${cache_gated:,.2f}/day  -> gate saves ${cache_all - cache_gated:,.2f}/day")
        print(f"\n-- Reasoning budget --")
        print(f"  reasoning = {reasoning['traffic_pct']}% of traffic, {reasoning['cost_pct']}% of $, {reasoning['wh_pct']}% of Wh")
        for s in sweep:
            print(f"  keep {s['keep_frac']:>4.0%} ({s['reasoning_traffic_pct']:>4}% traffic): "
                  f"${s['daily']:,.2f}/day (-${s['saved_usd']:,.2f})  {s['wh']:,} Wh (-{s['saved_wh']:,} Wh)")

    return {
        "baseline_daily": round(base_cost, 2), "optimized_daily": round(opt_cost, 2),
        "baseline_per_m": round(base_pm, 3), "optimized_per_m": round(opt_pm, 3),
        "savings_pct": round(savings_pct, 1), "total_tokens": total_tokens,
        "steps": steps, "reasoning": reasoning,
        "cache": {"break_even_reads": round(break_even, 2), "projects": cache_rows,
                  "all_daily": round(cache_all, 2), "gated_daily": round(cache_gated, 2)},
    }


if __name__ == "__main__":
    run()
