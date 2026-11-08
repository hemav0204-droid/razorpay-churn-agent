"""
Run the Merchant Retention Decision Agent end to end.

    python run_agent.py --data data_pack.xlsx              # rules + templates (reproducible)
    python run_agent.py --data data_pack.xlsx --llm        # + LLM note check and personalised drafts

Outputs (in ./output):
    agent_results.csv     all 100 merchants, ranked, with drafts for the top 15
    test_results.csv      real-row consistency tests + synthetic edge cases
    sensitivity.csv       stability of each merchant under +/-30% weight changes
    baselines.csv         comparison against naive approaches
"""
from __future__ import annotations
import argparse
import os
import pandas as pd

import engine as E
from engine import run, sensitivity, features, score, diagnose, prioritise
from outreach import draft, validate, csm_checklist

# My own reading of the data (NOT the hidden labels). Used to check the engine does
# what it was designed to do, case by case.
EXPECTED_DRIVER = {
    **dict.fromkeys(["C2001", "C2015", "C2034", "C2045", "C2061", "C2088", "C2100"], "Performance"),
    **dict.fromkeys(["C2027", "C2062", "C2079", "C2084", "C2091", "C2093"], "Service"),
    **dict.fromkeys(["C2004", "C2018", "C2022", "C2036", "C2040", "C2092"], "Pricing / competitive"),
    **dict.fromkeys(["C2008", "C2020", "C2032", "C2090", "C2097"], "Disengagement"),
}
EXPECTED_DECOY = {
    **dict.fromkeys(["C2012", "C2023", "C2048", "C2054", "C2065", "C2066", "C2067", "C2094"], "seasonal"),
    **dict.fromkeys(["C2003", "C2016", "C2043", "C2072", "C2078", "C2083"], "busy but healthy"),
    **dict.fromkeys(["C2002", "C2014", "C2017", "C2025", "C2042", "C2050"], "low-volume stable"),
}


def synthetic_cases(raw: pd.DataFrame) -> pd.DataFrame:
    """Edge cases built by editing a stable merchant (C2009), to stress the rules."""
    base = raw[raw.merchant_id == "C2009"].iloc[0].to_dict()
    steady = dict(zip([f"tpv_m{i}_inr_lakh" for i in range(1, 7)], [20, 18, 16, 14, 12, 10]))
    cases = [
        ("E1", "Seasonal industry but steady decline, no rebound", {"industry": "Education / Coaching", **steady}, "Not Low (must NOT be excused as seasonal)"),
        ("E2", "AM note claims seasonal, but data shows steady decline", {"account_manager_note": "Seasonal dip as per last year pattern", **steady}, "Not Low (data beats note)"),
        ("E3", "12 tickets in 90 days, all resolved, TPV growing", {"support_tickets_last_90d": 12, "unresolved_tickets": 0, "tpv_m6_inr_lakh": 13}, "Low, PB-5"),
        ("E4", "Tiny stable merchant, 1 login, 1 product, no CSAT", {"logins_last_30d": 1, "products_used": 1, "last_csat_1_to_5": None, **dict.fromkeys([f"tpv_m{i}_inr_lakh" for i in range(1, 7)], 1.2)}, "Low, PB-6"),
        ("E5", "Success rate down 10 pts but TPV still growing", {"success_rate_m4_m6_pct": 86.5, "tpv_m6_inr_lakh": 11.5}, "Not Low"),
        ("E6", "Huge healthy enterprise (Rs 900L/month), no risk", {"segment": "Enterprise", **dict.fromkeys([f"tpv_m{i}_inr_lakh" for i in range(1, 7)], 900)}, "Not in top 15"),
        ("E7", "Early churner: TPV down 10%, no note, all else healthy", {"tpv_m4_inr_lakh": 9.6, "tpv_m5_inr_lakh": 9.3, "tpv_m6_inr_lakh": 8.9}, "Not Low (KNOWN BLIND SPOT)"),
        ("E8", "5 unresolved tickets, CSAT missing, TPV stable", {"unresolved_tickets": 5, "support_tickets_last_90d": 5, "last_csat_1_to_5": None}, "Not Low (KNOWN BLIND SPOT)"),
    ]
    rows = []
    for cid, desc, edits, exp in cases:
        r = {**base, **edits, "merchant_id": cid, "business_name": f"Synthetic {cid}"}
        rows.append((cid, desc, exp, r))
    syn = pd.DataFrame([r for *_, r in rows])
    allm = prioritise(diagnose(score(features(pd.concat([raw, syn], ignore_index=True)))))
    out = []
    for cid, desc, exp, _ in rows:
        a = allm[allm.merchant_id == cid].iloc[0]
        got = f"{a.risk_label} ({a.risk_score}), {a.playbook}, rank {a['rank']}"
        if exp.startswith("Not Low"):
            ok = a.risk_label != "Low"
        elif exp == "Not in top 15":
            ok = not a.outreach_this_month
        else:
            lab, pb = [x.strip() for x in exp.split(",")]
            ok = a.risk_label == lab and a.playbook == pb
        out.append({"test_id": cid, "type": "Synthetic edge case", "case": desc, "expected": exp,
                    "engine_output": got, "result": "PASS" if ok else "FAIL"})
    return pd.DataFrame(out)


def real_row_tests(p: pd.DataFrame) -> pd.DataFrame:
    rows = []
    idx = p.set_index("merchant_id")
    for mid, drv in EXPECTED_DRIVER.items():
        r = idx.loc[mid]
        ok = r.risk_label == "High" and r.primary_driver == drv
        rows.append({"test_id": mid, "type": "Real row: at-risk", "case": f"{r.segment}, {r.industry}",
                     "expected": f"High, driver = {drv}",
                     "engine_output": f"{r.risk_label} ({r.risk_score}), {r.primary_driver}, {r.playbook}",
                     "result": "PASS" if ok else "FAIL"})
    for mid, kind in EXPECTED_DECOY.items():
        r = idx.loc[mid]
        ok = r.risk_label == "Low" and not r.outreach_this_month
        rows.append({"test_id": mid, "type": f"Real row: decoy ({kind})", "case": f"{r.segment}, {r.industry}",
                     "expected": "Low, not contacted",
                     "engine_output": f"{r.risk_label} ({r.risk_score}), {r.classification}, {r.playbook}",
                     "result": "PASS" if ok else "FAIL"})
    return pd.DataFrame(rows)


def baselines(p: pd.DataFrame) -> pd.DataFrame:
    """How naive approaches would have done, judged by the same engine classifications."""
    decoys = set(EXPECTED_DECOY)
    at_risk = set(EXPECTED_DRIVER)
    ours = set(p[p.outreach_this_month].merchant_id)
    by_drop = set(p.sort_values("tpv_change_pct").head(E.OUTREACH_CAP).merchant_id)
    by_drop20 = set(p.sort_values("tpv_change_pct").head(20).merchant_id)
    by_risk = set(p.sort_values("risk_score", ascending=False).head(E.OUTREACH_CAP).merchant_id)
    excused_by_industry = sorted(at_risk & set(p[p.industry.isin(E.SEASONAL_INDUSTRIES)].merchant_id))
    val = p.set_index("merchant_id")["annual_value_inr"]

    def row(name, s, note):
        return {"approach": name, "merchants": len(s), "decoys_included": len(s & decoys),
                "at_risk_included": len(s & at_risk),
                "annual_value_covered_inr": round(val[list(s)].sum()), "note": note}
    return pd.DataFrame([
        row("This agent (risk gate + value x urgency)", ours, "Final selection"),
        row("Rank by risk score only", by_risk, "Same precision, but skips big accounts for tiny ones"),
        row("Rank by TPV drop only (top 15)", by_drop, "No decoys at 15, but drivers unknown"),
        row("Rank by TPV drop only (top 20)", by_drop20, "Seasonal decoys start entering at 16+"),
        {"approach": "Excuse all seasonal-industry merchants", "merchants": None, "decoys_included": None,
         "at_risk_included": None, "annual_value_covered_inr": None,
         "note": f"Would wrongly excuse {len(excused_by_industry)} at-risk merchants: {', '.join(excused_by_industry)}"},
    ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_pack.xlsx")
    ap.add_argument("--out", default="output")
    ap.add_argument("--llm", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    p, playbooks = run(a.data)
    drafts, status, checks, source, llm_note = [], [], [], [], []
    for r in p.itertuples():
        if not r.outreach_this_month:
            drafts.append(""); status.append(""); checks.append(""); source.append(""); llm_note.append("")
            continue
        d, src = draft(r), "template"
        if a.llm:
            from llm_layer import personalise, interpret_note
            d, src = personalise(r, d)
            n = interpret_note(r.account_manager_note)
            llm_note.append("agrees" if n["category"] == r.note_category
                            else f"DISAGREES: LLM says {n['category']}; human review")
        else:
            llm_note.append("")
        issues = validate(d, r)
        drafts.append(d if not issues else "")
        status.append("PASS" if not issues else "BLOCKED: " + "; ".join(issues))
        checks.append(csm_checklist(r)); source.append(src)
    p["outreach_draft"], p["guardrail_check"], p["csm_checklist"] = drafts, status, checks
    p["draft_source"], p["llm_note_check"] = source, llm_note

    if set(EXPECTED_DRIVER) <= set(p.merchant_id) and "C2009" in set(p.merchant_id):
        tests = pd.concat([real_row_tests(p), synthetic_cases(E.load_pack(a.data)[0])], ignore_index=True)
    else:  # hand-written tests refer to merchants in the original pack only
        tests = pd.DataFrame(columns=["test_id", "type", "case", "expected", "engine_output", "result"])
    sens = sensitivity(a.data).reset_index()
    base = baselines(p)

    p.to_csv(f"{a.out}/agent_results.csv", index=False)
    tests.to_csv(f"{a.out}/test_results.csv", index=False)
    sens.to_csv(f"{a.out}/sensitivity.csv", index=False)
    base.to_csv(f"{a.out}/baselines.csv", index=False)

    top = p[p.outreach_this_month]
    cost = E.OUTREACH_CAP * E.FALSE_ALARM_COST
    print(f"High risk: {(p.risk_label == 'High').sum()} | contacted: {len(top)} | "
          f"annual net revenue covered: Rs {top.annual_value_inr.sum():,.0f} | outreach cost: Rs {cost:,}")
    print(f"Guardrails: {(top.guardrail_check == 'PASS').sum()}/{len(top)} drafts pass")
    print(f"Tests: {(tests.result == 'PASS').sum()}/{len(tests)} pass")
    print(tests[tests.result == "FAIL"][["test_id", "case", "engine_output"]].to_string(index=False))
    return p, tests, sens, base, playbooks


if __name__ == "__main__":
    main()
