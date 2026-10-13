"""M5 — Optimization Report: combine M1-M4 into baseline-vs-optimized (deck §1/§11).

Run: python missions/m5_report.py   ->  outputs/report.md + outputs/savings.png
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
from missions._common import num, catalog_by_type, ROOT
from finops import report, sustainability
from missions import m1_efficiency_audit, m2_inference_levers, m3_purchasing

DAYS = 30
# one tier down for over-provisioned ("util-lie") GPUs
RIGHTSIZE_MAP = {"H100": "A100", "H200": "H100", "A100": "A10G", "A10G": "L4", "L4": "L4"}


def _inference_md(r2: dict) -> str:
    """$/1M-token theo từng lever + Your Turn #3 (cache gate) và #4 (reasoning budget)."""
    c, rs = r2["cache"], r2["reasoning"]
    keep = next(x for x in rs["sweep"] if x["keep_frac"] == m2_inference_levers.REASONING_KEEP_FRAC)
    out = ["## Unit economics inference ($/1M-token, cộng dồn từng lever)", "",
           "| Lever | $/ngày | $/1M-token |", "|---|---|---|"]
    out += [f"| {s['lever']} | ${s['daily']:,.2f} | ${s['per_m']:.3f} |" for s in r2["steps"]]
    out += ["", "## Your Turn #3 — Prompt cache có đáng không?", "",
            f"Ghi cache = 1.25× giá input, đọc = 0.1× → hòa vốn khi mỗi lần ghi được đọc lại "
            f"**≥ {c['break_even_reads']} lần** ((1.25−1)/(1−0.1)). Giá model triệt tiêu nên ngưỡng giống nhau "
            "cho tier small và large; tier large chỉ tiết kiệm nhiều $ hơn mỗi lần đọc. "
            "Số lần đọc/ghi suy ra từ hit rate: N = hit / (1 − hit).", "",
            "| Project | Hit rate | Đọc/ghi | Cache |", "|---|---|---|---|"]
    out += [f"| {p['project']} | {p['hit_rate']:.1%} | {p['avg_reads']:.2f} | {'BẬT' if p['cache_on'] else 'TẮT'} |"
            for p in c["projects"]]
    out += ["", f"Cache mọi nơi: ${c['all_daily']:,.2f}/ngày; chỉ cache project vượt ngưỡng: ${c['gated_daily']:,.2f}/ngày "
            f"→ tiết kiệm **${c['all_daily'] - c['gated_daily']:,.2f}/ngày**. nightly-eval và web-search gần như không "
            "đọc lại prefix nên cache chỉ làm tăng phí ghi.",
            "", "## Your Turn #4 — Ngân sách Reasoning", "",
            f"Reasoning chiếm **{rs['traffic_pct']}% traffic** nhưng **{rs['cost_pct']}% chi phí inference** và "
            f"**{rs['wh_pct']}% năng lượng** (${rs['daily_usd']:,.2f}/ngày, {rs['daily_wh']:,} Wh/ngày). "
            "Tốn ~80× năng lượng vì model sinh chuỗi suy luận dài (~6× output token ở đây) trước khi trả lời; "
            "decode là pha memory-bound, mỗi token đều đọc lại toàn bộ trọng số + KV-cache, nên Wh tăng theo độ dài chuỗi.", "",
            f"**Quy tắc routing:** chỉ bật reasoning cho {m2_inference_levers.REASONING_KEEP_FRAC:.0%} request reasoning "
            f"có prompt dài nhất (proxy độ phức tạp); phần còn lại trả lời như request thường (tối đa {rs['plain_out']} token output). "
            f"Kết quả: tiết kiệm ${keep['saved_usd']:,.2f}/ngày và {keep['saved_wh']:,} Wh/ngày "
            f"(−{keep['saved_wh'] / rs['wh_before']:.0%} năng lượng inference).", "",
            "| Giữ reasoning | % traffic | $/ngày | $ tiết kiệm | Wh/ngày | Wh tiết kiệm |",
            "|---|---|---|---|---|---|"]
    out += [f"| {s['keep_frac']:.0%} | {s['reasoning_traffic_pct']}% | ${s['daily']:,.2f} | ${s['saved_usd']:,.2f} "
            f"| {s['wh']:,} | {s['saved_wh']:,} |" for s in rs["sweep"]]
    return "\n".join(out)


def _analysis_md(r1: dict, r2: dict, levers: dict, cat: dict) -> str:
    """Phân tích + khuyến nghị theo ROI (rubric C.2)."""
    lie = r1["lies"][0]
    hr = num(cat[lie["gpu_type"]]["on_demand_hr"])
    rs = r2["reasoning"]
    kwh = rs["wh_after"] / 1000
    regions = ["us-east-1", "europe-north1", "us-east-wa"]
    reg = " · ".join(f"{g}: ${sustainability.energy_cost_usd(rs['wh_after'], g):.2f} / "
                     f"{sustainability.carbon_g(rs['wh_after'], g) / 1000:.1f} kg CO2e" for g in regions)
    C, P, st = sustainability.REGION_CARBON, sustainability.REGION_PRICE_KWH, r2["steps"]
    inf = levers["Inference (cascade/batch/cache/reasoning)"]
    return "\n".join([
        "## Phân tích", "",
        f"**GPU-Util \"lie\".** `{lie['gpu_id']}` báo {lie['gpu_util_pct']}% GPU-Util nhưng MFU chỉ {lie['mfu']}. "
        "`nvidia-smi` chỉ đo % thời gian có ít nhất một kernel đang chạy, không đo SM/Tensor Core có làm việc hay không. "
        "Memory stall, batch nhỏ, kernel launch overhead hoặc data-loader chậm vẫn giữ GPU \"bận\" mà gần như không ra FLOPs. "
        f"Hệ quả: trả ${hr:.2f}/giờ nhưng chi phí thực trên mỗi giờ tính toán hữu ích là ${hr / lie['mfu']:.2f} "
        f"(~{1 / lie['mfu']:.0f}×). Hạ tier các GPU bị \"lie\" tiết kiệm ${levers['Right-size util-lies']:,}/tháng.", "",
        f"**Bền vững.** Sau reasoning budget, inference dùng {kwh:.1f} kWh/ngày. {reg}. "
        f"europe-north1 sạch nhất (−{1 - C['europe-north1'] / C['us-east-1']:.0%} carbon so với us-east-1) và rẻ hơn "
        f"{1 - P['europe-north1'] / P['us-east-1']:.0%} tiền điện; us-east-wa rẻ nhất về $. "
        "Chọn vùng giảm cả $ và carbon cùng lúc, nhưng phải cân nhắc latency tới người dùng — "
        "phù hợp nhất cho job batch/training có thể gián đoạn.", "",
        "## Khuyến nghị (theo thứ tự ROI)", "",
        f"1. **Purchasing — ${levers['Purchasing (spot/reserved)']:,}/tháng.** Không đổi code, chỉ đổi cách mua: "
        "spot + checkpoint cho training, reserved cho inference chạy 24/7 (vượt ngưỡng hòa vốn 55% duty).",
        f"2. **Tắt GPU idle + hạ tier GPU bị \"lie\" — ${levers['Kill idle GPUs'] + levers['Right-size util-lies']:,}/tháng.** "
        "Đo MFU thay vì GPU-Util trước khi mua thêm GPU.",
        f"3. **Inference — ${inf:,}/tháng.** Cascade routing là bước lớn nhất "
        f"($/1M-token −{1 - st[1]['per_m'] / st[0]['per_m']:.0%}), sau đó batch API cho job không cần real-time.",
        "4. **Reasoning budget + cache gate.** $ nhỏ nhưng cắt phần lớn năng lượng; "
        "áp dụng sau khi gắn tag đủ để chargeback cho team eval.",
    ])


def run(verbose: bool = True) -> dict:
    r1 = m1_efficiency_audit.run(verbose=False)
    r2 = m2_inference_levers.run(verbose=False)
    r3 = m3_purchasing.run(verbose=False)
    cat = catalog_by_type()

    # --- buckets ---
    infer_savings = (r2["baseline_daily"] - r2["optimized_daily"]) * DAYS
    purchasing_savings = r3["on_demand_monthly"] - r3["optimized_monthly"]

    idle_savings = r1["idle_waste_daily"] * DAYS
    rightsize_savings = 0.0
    for lie in r1["lies"]:
        cur = lie["gpu_type"]
        tgt = RIGHTSIZE_MAP.get(cur, cur)
        delta = num(cat[cur]["on_demand_hr"]) - num(cat[tgt]["on_demand_hr"])
        rightsize_savings += max(0.0, delta) * 24 * DAYS

    levers = {
        "Inference (cascade/batch/cache/reasoning)": round(infer_savings),
        "Purchasing (spot/reserved)": round(purchasing_savings),
        "Right-size util-lies": round(rightsize_savings),
        "Kill idle GPUs": round(idle_savings),
    }
    baseline = r2["baseline_daily"] * DAYS + r3["on_demand_monthly"]
    optimized = baseline - sum(levers.values())
    total_pct = sum(levers.values()) / baseline * 100 if baseline else 0.0

    # --- sustainability snapshot ---
    median_tokens = 800
    wh = sustainability.wh_per_query(median_tokens)
    sust = {
        "wh_per_query": wh,
        "carbon_g": sustainability.carbon_g(wh, "us-east-1"),
        "best_region": min(sustainability.REGION_CARBON, key=sustainability.REGION_CARBON.get),
    }

    md = report.build_report(baseline, optimized, levers, sustainability=sust, extra_md=_analysis_md(r1, r2, levers, cat) + "\n\n" + _inference_md(r2))
    out_md = os.path.join(ROOT, "outputs", "report.md")
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, "w") as f:
        f.write(md)
    png = report.savings_waterfall(levers, os.path.join(ROOT, "outputs", "savings.png"))

    if verbose:
        print("== M5 Optimization Report ==")
        print(md)
        print(f"\nWritten: outputs/report.md" + (f" + outputs/savings.png" if png else " (matplotlib absent: PNG skipped)"))

    return {"baseline_monthly": round(baseline), "optimized_monthly": round(optimized),
            "levers": levers, "total_savings_pct": round(total_pct, 1)}


if __name__ == "__main__":
    run()
