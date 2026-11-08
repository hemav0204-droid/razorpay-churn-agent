"""
Evidence for the "results and failures" part of the rubric.
  ablation()        what each design choice is actually worth (switch it off, see what breaks)
  capacity_curve()  revenue covered and value of each extra call, for 1..all at-risk merchants
  guardrail_eval()  rule guardrail on the red-team sets (dev vs held-out vs benign)
  FAILURE_LOG       honest log of what went wrong during the build
"""
from __future__ import annotations
import numpy as np
import pandas as pd

import engine as E
import outreach as O
import redteam as R
import os

BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_pack.xlsx")


def _mx(x):
    return "n/a" if len(x) == 0 or pd.isna(x.max()) else int(x.max())


def _high(s):
    return set(s[s.risk_label == "High"].merchant_id)


def ablation(raw: pd.DataFrame) -> pd.DataFrame:
    f = E.features(raw)
    full = E.prioritise(E.diagnose(E.score(f)))
    decoys = set(full[full.classification.str.startswith("Decoy")].merchant_id)
    at_risk = _high(full)
    val = full.set_index("merchant_id").annual_value_inr
    rows = []

    def add(change, expect, result, verdict):
        rows.append({"What we switched off or changed": change, "What we expected": expect,
                     "What actually happened": result, "Verdict": verdict})

    add("Nothing (full agent)", "-", f"{len(at_risk)} High risk, 0 of {len(decoys)} decoys flagged", "Baseline")

    g = f.copy(); g["seasonal_shape"] = False
    s = E.score(g); hit = _high(s) & decoys
    mx = _mx(s[s.merchant_id.isin(full[full.classification == 'Decoy: seasonal'].merchant_id)].risk_score)
    add("Seasonal-shape guard", "Seasonal decoys flood in",
        f"{len(hit)} decoys flagged; highest seasonal score rises to {mx} (threshold 45)",
        "Guard is NOT needed at this threshold. Decoys stay out because they show only one warning sign.")

    g = f.copy(); g["seasonal_shape"] = g["seasonal_industry"]
    s = E.score(g); missed = sorted(at_risk - _high(s))
    add("Judge seasonality by industry instead of shape", "Same result",
        f"Misses {len(missed)} merchants that are leaving: {', '.join(missed)}",
        "Industry rule is dangerous. Shape-based check is the right one.")

    s = E.score(f)
    eng = np.select([f.logins_last_30d <= 3, f.logins_last_30d <= 10], [12, 6], 0) + np.where(f.products_used == 1, 4, 0)
    alt_score = s.risk_score - s.pts_engagement + eng
    dmask = s.merchant_id.isin(decoys)
    add("Low-volume gate (count low logins even when volume is steady)", "Small merchants get flagged",
        f"{int((alt_score[dmask] > s.risk_score[dmask]).sum())} decoy scores rise, highest reaches {_mx(alt_score[dmask])}",
        "Adds safety margin; not decisive on this data.")

    busy = full[full.classification == "Decoy: busy but healthy"].merchant_id
    tick = np.clip(f.support_tickets_last_90d / 8, 0, 1) * 15 + f.last_csat_1_to_5.map({1: 10, 2: 8, 3: 2}).fillna(0)
    alt_score = s.risk_score - s.pts_service + tick
    bm = s.merchant_id.isin(busy)
    add("Score all tickets, not just open ones", "Busy growing merchants get flagged",
        f"Busy merchants' scores rise from {_mx(s.risk_score[bm])} to at most {_mx(alt_score[bm])}",
        "Adds safety margin; not decisive on this data.")

    g = f.copy(); g["note_points"] = 0
    s = E.score(g); lost = sorted(at_risk - _high(s))
    add("Ignore account-manager notes", "Small effect",
        f"{len(lost)} at-risk merchants drop out: {', '.join(lost)}",
        "Notes are essential: pricing risk is invisible in the numbers alone.")

    s = E.score(f)
    renew = np.select([f.days_to_contract_renewal <= 60, f.days_to_contract_renewal <= 90], [10, 5], 0)
    alt_score = s.risk_score - s.pts_renewal + renew
    risen = int(((alt_score > s.risk_score) & ~s.merchant_id.isin(at_risk)).sum())
    add("Treat renewal date as risk on its own", "More early warnings",
        f"{risen} healthy merchants gain points just for having a renewal coming up",
        "Renewal is an urgency signal, not a churn signal.")

    by_risk = full[full.eligible].sort_values("risk_score", ascending=False).head(E.OUTREACH_CAP).merchant_id
    ours = full[full.outreach_this_month].merchant_id
    add(f"Pick the {E.OUTREACH_CAP} by risk score only (ignore value)", "Similar result",
        f"Covers Rs {val[by_risk].sum()/1e5:.1f} lakh a year vs Rs {val[ours].sum()/1e5:.1f} lakh",
        (f"Value-aware ranking protects {val[ours].sum()/val[by_risk].sum():.1f}x more revenue with the same calls."
         if val[by_risk].sum() > 0 else "No at-risk merchants, so ranking doesn't matter."))
    return pd.DataFrame(rows)


def capacity_curve(p: pd.DataFrame, save_rate: float = E.SAVE_RATE) -> pd.DataFrame:
    """p = output of engine.run(). Eligible merchants in priority order, with cumulative value."""
    e = p[p.eligible].sort_values("priority_value", ascending=False).reset_index(drop=True)
    total = e.annual_value_inr.sum()
    e["call_no"] = np.arange(1, len(e) + 1)
    e["expected_value_of_call"] = e.risk_score / 100 * save_rate * e.annual_value_inr - E.FALSE_ALARM_COST
    e["revenue_covered"] = e.annual_value_inr.cumsum()
    e["share_covered"] = e.revenue_covered / total if total else 0.0
    return e[["call_no", "merchant_id", "business_name", "annual_value_inr", "risk_score",
              "expected_value_of_call", "revenue_covered", "share_covered"]]


def reference_merchant():
    """Guardrail tests always use the same reference merchant (C2004 from the bundled
    original data pack), so their score doesn't change with whichever pack is loaded."""
    raw, _, a, _ = E.load_pack(BUNDLED)
    saved = (E.NET_REVENUE_RATE, E.MONTHS_VALUE, E.FALSE_ALARM_COST, E.OUTREACH_CAP, set(E.SEASONAL_INDUSTRIES))
    E.apply_assumptions(a)
    q = E.prioritise(E.diagnose(E.score(E.features(raw))))
    E.NET_REVENUE_RATE, E.MONTHS_VALUE, E.FALSE_ALARM_COST, E.OUTREACH_CAP, E.SEASONAL_INDUSTRIES = saved
    return next(q[q.merchant_id == "C2004"].itertuples())


def guardrail_eval(p: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    r = reference_merchant()
    saved = O.TONE_RULES
    rows = []
    for name, data, want in [("Development (tuned on)", R.DEV, True), ("Held-out (never tuned on)", R.HELD_OUT, True),
                             ("Normal sentences", [("normal", t) for t in R.BENIGN], False)]:
        for c, t in data:
            O.TONE_RULES = []
            l1 = bool(O.validate(t, r))
            O.TONE_RULES = saved
            l12 = bool(O.validate(t, r))
            rows.append({"Set": name, "Type": c, "Sentence": t, "Should block": want,
                         "Layer 1 blocks": l1, "Layers 1+2 block": l12, "Correct": l12 == want})
    O.TONE_RULES = saved
    d = pd.DataFrame(rows)
    summ = d.groupby("Set", sort=False).agg(
        sentences=("Sentence", "count"),
        layer1_correct=("Layer 1 blocks", lambda x: int((x == d.loc[x.index, "Should block"]).sum())),
        layers12_correct=("Correct", "sum")).reset_index()
    return d, summ


FAILURE_LOG = [
    ("Guardrail", "Keyword rules scored 12/12 on sentences I tuned them on, but only 4/12 on new phrasings "
     "(e.g. 'any money you lost will be credited back' is a refund promise without the word refund).",
     "Kept the honest number. Added an AI reviewer (layer 3) and kept human approval mandatory."),
    ("My assumption", "I expected the seasonal-shape guard to be what keeps seasonal merchants out. "
     "Switching it off changed nothing: they never had a second warning sign.",
     "Reframed the logic: churners show 2+ signals together; one signal alone is not enough."),
    ("Bug caught by guardrail", "A template printed 'Rs 73.0 lakh' while the data said 73, so the number check blocked it.",
     "Fixed number formatting; showed the guardrail works on our own mistakes too."),
    ("Bug caught by tests", "An apostrophe inside a text string broke the dashboard during the redesign.",
     "Automated app test runs every merchant view before anything is shipped."),
    ("Wrong claim caught on review", "A summary sentence said over-cap merchants were 'under Rs 5 lakh'; the real figure was Rs 5.65 lakh.",
     "All insight text is now computed from the data, never typed by hand."),
    ("Known blind spot", "An early churner with only a 10% drop and no account-manager note scores Low (test E7).",
     "Next step: add a trend-acceleration signal; flag for watchlist rather than call."),
    ("Known blind spot", "Five open tickets with steady volume scores Low (test E8): service pain before volume moves.",
     "Next step: a service-only floor that puts such merchants on a watchlist."),
    ("Fragile picks", "C2097 (no note) and C2040 (small, competitor mention) drop out of the plan in 20-23% of weight shuffles.",
     "Flagged as borderline in the call list; CSM judgment decides."),
    ("Self-graded tests", "My 52 tests compare the agent with my own reading of the data, not Razorpay's hidden labels.",
     "Stated openly; the real accuracy is only known once the labels are checked."),
]
