import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from data import generate
from missions import m1_efficiency_audit, m2_inference_levers, m3_purchasing, m4_allocation, m5_report


def test_data_generates_deterministically():
    generate.main()
    p = os.path.join(ROOT, "data", "gpu_telemetry.csv")
    a = open(p).read()
    generate.main()
    assert open(p).read() == a                 # seeded -> identical


def test_missions_end_to_end():
    generate.main()
    r1 = m1_efficiency_audit.run(verbose=False)
    assert any(l["gpu_id"] == "gpu-h100-4" for l in r1["lies"])
    r2 = m2_inference_levers.run(verbose=False)
    assert 60 <= r2["savings_pct"] <= 95
    r3 = m3_purchasing.run(verbose=False)
    assert r3["savings_pct"] > 0
    r4 = m4_allocation.run(verbose=False)
    assert 0.85 <= r4["tag_coverage"] <= 1.0
    r5 = m5_report.run(verbose=False)
    assert 40 <= r5["total_savings_pct"] <= 95


def test_m2_cache_gate_and_reasoning_budget():
    generate.main()
    r2 = m2_inference_levers.run(verbose=False)
    gate = {p["project"]: p["cache_on"] for p in r2["cache"]["projects"]}
    assert gate["chat"] and not gate["web-search"]          # low-reuse project skips caching
    assert r2["cache"]["gated_daily"] <= r2["cache"]["all_daily"]
    rs = r2["reasoning"]
    assert rs["wh_pct"] > rs["cost_pct"] > rs["traffic_pct"]  # reasoning is an energy bomb
    saved = [s["saved_wh"] for s in rs["sweep"]]
    assert saved == sorted(saved) and saved[0] == 0           # tighter budget -> more Wh saved
    per_m = [s["per_m"] for s in r2["steps"]]
    assert per_m == sorted(per_m, reverse=True)               # every lever lowers $/1M-token
