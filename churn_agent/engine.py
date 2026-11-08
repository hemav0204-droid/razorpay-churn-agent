"""
Merchant Retention Decision Agent  -  scoring engine (deterministic layer)
Razorpay Campus AI Build-a-thon, Problem 2

Design principle: anything that can be computed with a formula is computed here,
reproducibly. The LLM layer (llm_layer.py) only interprets free text and drafts
language, and everything it writes is checked by guardrails.py.

Pipeline:
  1. features()      engineer trend / performance / service / engagement signals
  2. classify_note() map the account-manager note to a fixed taxonomy
  3. score()         risk points per driver, with decoy guards, total 0-100
  4. diagnose()      primary + secondary churn driver, plain-language reason
  5. playbook()      choose from PB-1..PB-6 only
  6. prioritise()    expected-value ranking under the 15-outreach cap
"""
from __future__ import annotations
import re
import numpy as np
import pandas as pd

TPV = [f"tpv_m{i}_inr_lakh" for i in range(1, 7)]

# ---------------------------------------------------------------- assumptions
# Taken from P2_Assumptions unless marked "OUR ASSUMPTION".
NET_REVENUE_RATE = 0.01          # 1% of TPV
LAKH = 100_000
MONTHS_VALUE = 12                # value of a saved merchant = 12 months at m6 TPV
FALSE_ALARM_COST = 1_500         # Rs per outreach
OUTREACH_CAP = 15
SEASONAL_INDUSTRIES = {"Gifting & Festive", "Education / Coaching", "Travel & Hospitality"}
SAVE_RATE = 0.25                 # OUR ASSUMPTION: share of contacted true churners retained

# Risk label thresholds (points out of 100). Tuned by inspecting the data, NOT
# against labels (we have none). See README "Honest limitations".
HIGH, MEDIUM = 45, 25

# ---------------------------------------------------------------- note taxonomy
# Ordered: first match wins. Each tuple = (category, regex, risk points, driver)
NOTE_RULES = [
    ("competitive",        r"competitor|comparing quotes|exploring options",           25, "commercial"),
    ("pricing_renewal",    r"rate card|renewal",                                       20, "commercial"),
    ("performance_issue",  r"drop-?offs?|success rate|failures?",                      15, "performance"),
    ("service_issue",      r"take too long|still not closed|escalated",               15, "service"),
    ("disengagement",      r"rarely used|new manager|unclear contact|no response",    15, "disengagement"),
    ("seasonal_context",   r"seasonal|peak season|expects pickup",                      0, None),
    ("growth_context",     r"growing fast|interested in adding",                        0, None),
    ("resolved_neutral",   r"resolved|fixed|no concerns|never raised|low touch",        0, None),
]


def classify_note(note) -> dict:
    """Rule-based note interpretation. Returns category, points, driver."""
    if not isinstance(note, str) or not note.strip():
        return {"note_category": "no_note", "note_points": 0, "note_driver": None}
    low = note.lower()
    for cat, pattern, pts, drv in NOTE_RULES:
        if re.search(pattern, low):
            return {"note_category": cat, "note_points": pts, "note_driver": drv}
    return {"note_category": "unclassified", "note_points": 0, "note_driver": None}


# ---------------------------------------------------------------- 1. features
def features(df: pd.DataFrame) -> pd.DataFrame:
    f = df.copy()
    t = f[TPV]
    f["tpv_baseline_m1_m3"] = t.iloc[:, :3].mean(axis=1)
    # Headline decline: latest month vs the first-quarter baseline (smoother than m1 alone)
    f["tpv_change_pct"] = (f["tpv_m6_inr_lakh"] / f["tpv_baseline_m1_m3"] - 1) * 100
    f["tpv_change_m1_m6_pct"] = (f["tpv_m6_inr_lakh"] / f["tpv_m1_inr_lakh"] - 1) * 100
    # How many of the 5 month-on-month moves were down (5 = falls every month)
    f["down_months"] = sum((t.iloc[:, i + 1] < t.iloc[:, i]).astype(int) for i in range(5))
    # Seasonal SHAPE: sharp step-down in m4, then a rebound by m6
    trough = t[["tpv_m4_inr_lakh", "tpv_m5_inr_lakh"]].min(axis=1)
    f["m4_step_pct"] = (f["tpv_m4_inr_lakh"] / f["tpv_baseline_m1_m3"] - 1) * 100
    f["rebound_pct"] = (f["tpv_m6_inr_lakh"] / trough - 1) * 100
    f["seasonal_shape"] = (f["m4_step_pct"] <= -15) & (f["rebound_pct"] >= 10)
    f["seasonal_industry"] = f["industry"].isin(SEASONAL_INDUSTRIES)

    f["sr_change_pp"] = f["success_rate_m4_m6_pct"] - f["success_rate_m1_m3_pct"]
    f["csat_missing"] = f["last_csat_1_to_5"].isna()
    # Data quality: open tickets older than the 90-day window
    f["dq_old_open_ticket"] = f["unresolved_tickets"] > f["support_tickets_last_90d"]

    notes = f["account_manager_note"].apply(classify_note).apply(pd.Series)
    notes["note_driver"] = notes["note_driver"].where(notes["note_driver"].notna(), "")
    f = pd.concat([f, notes], axis=1)
    f["annual_value_inr"] = f["tpv_m6_inr_lakh"] * LAKH * NET_REVENUE_RATE * MONTHS_VALUE
    return f


# ---------------------------------------------------------------- 2. scoring
def _clip01(x):
    return np.clip(x, 0, 1)


DEFAULT_WEIGHTS = {"volume": 1.0, "performance": 1.0, "service": 1.0, "engagement": 1.0, "note": 1.0, "renewal": 1.0}


def score(f: pd.DataFrame, w: dict | None = None) -> pd.DataFrame:
    """w = optional multipliers per component, used only for sensitivity testing."""
    w = {**DEFAULT_WEIGHTS, **(w or {})}
    s = f.copy()
    decline = (-s["tpv_change_pct"]).clip(lower=0)            # % lost vs baseline

    # A. Volume decline (max 35). It is the SYMPTOM, so it raises risk but is
    #    never reported as the driver on its own.
    consistency = np.where(s["down_months"] >= 4, 1.0, 0.7)
    vol = _clip01(decline / 30) * 35 * consistency
    # Decoy guard 1 - seasonal: only when the SHAPE is seasonal (step + rebound).
    # Industry or note alone is not enough to excuse a steady decline.
    s["seasonal_decoy"] = s["seasonal_shape"] & (
        s["seasonal_industry"] | (s["note_category"] == "seasonal_context"))
    vol = np.where(s["seasonal_decoy"], vol * 0.1, vol)
    s["pts_volume"] = vol * w["volume"]

    # B. Payment performance (max 30): -1pp -> 0, -8pp or worse -> 30
    s["pts_performance"] = _clip01((-s["sr_change_pp"] - 1) / 7) * 30 * w["performance"]

    # C. Service (max 25): unresolved tickets + low CSAT. Missing CSAT = neutral.
    #    Decoy guard 2 - busy-but-healthy: total ticket count is NOT scored, only
    #    unresolved ones, so a growing merchant with many resolved tickets scores 0.
    unres = _clip01(s["unresolved_tickets"] / 5) * 15
    csat = s["last_csat_1_to_5"].map({1: 10, 2: 8, 3: 2}).fillna(0)
    s["pts_service"] = (unres + csat) * w["service"]

    # D. Engagement (max 16): low logins, single product.
    #    Decoy guard 3 - low-volume: tiny stable merchants naturally log in rarely,
    #    so engagement only counts when volume is also falling (>=10%).
    eng = np.select([s["logins_last_30d"] <= 3, s["logins_last_30d"] <= 10], [12, 6], 0)
    eng = eng + np.where(s["products_used"] == 1, 4, 0)
    s["pts_engagement"] = np.where(decline >= 10, eng, 0) * w["engagement"]

    # E. Account-manager note (max 25)
    s["pts_note"] = s["note_points"] * w["note"]

    # F. Renewal urgency interaction (max 10): renewal is a natural exit point,
    #    but only adds risk when some other risk signal already exists.
    other = s[["pts_volume", "pts_performance", "pts_service", "pts_engagement", "pts_note"]].sum(axis=1)
    renew = np.select([s["days_to_contract_renewal"] <= 60, s["days_to_contract_renewal"] <= 90], [10, 5], 0)
    s["pts_renewal"] = np.where(other >= 15, renew, 0) * w["renewal"]

    pts_cols = ["pts_volume", "pts_performance", "pts_service", "pts_engagement", "pts_note", "pts_renewal"]
    s["risk_score"] = s[pts_cols].sum(axis=1).clip(upper=100).round(0).astype(int)
    s["risk_label"] = np.select([s["risk_score"] >= HIGH, s["risk_score"] >= MEDIUM], ["High", "Medium"], "Low")
    # Growth flag for PB-5
    s["healthy_growing"] = (s["tpv_change_pct"] >= 10) & (s["sr_change_pp"] > -2) & (s["unresolved_tickets"] <= 1)
    return s


# ---------------------------------------------------------------- 3. diagnosis
DRIVER_PLAYBOOK = {"performance": "PB-1", "service": "PB-2", "commercial": "PB-3", "disengagement": "PB-4"}
DRIVER_LABEL = {"performance": "Performance", "service": "Service", "commercial": "Pricing / competitive",
                "disengagement": "Disengagement"}


def _driver_strengths(r) -> dict:
    d = {
        "performance": r.pts_performance,
        "service": r.pts_service,
        "commercial": (r.pts_renewal if r.note_driver == "commercial" else 0),
        "disengagement": r.pts_engagement,
    }
    if r.note_driver:
        d[r.note_driver] += r.pts_note
    return d


def _reason(r, primary, secondary) -> str:
    v = f"TPV down {abs(r.tpv_change_pct):.0f}% (Rs {r.tpv_baseline_m1_m3:.1f}L avg in m1-m3 to Rs {r.tpv_m6_inr_lakh:.1f}L in m6)"
    bits = {
        "performance": f"success rate fell {abs(r.sr_change_pp):.1f} pts ({r.success_rate_m1_m3_pct:.1f}% to {r.success_rate_m4_m6_pct:.1f}%)",
        "service": f"{int(r.unresolved_tickets)} unresolved tickets" + (f", last CSAT {int(r.last_csat_1_to_5)}/5" if not r.csat_missing else ""),
        "commercial": f"AM note: \"{r.account_manager_note}\"; renewal in {int(r.days_to_contract_renewal)} days",
        "disengagement": f"{int(r.logins_last_30d)} logins in 30 days, {int(r.products_used)} product(s) used"
                         + (f"; AM note: \"{r.account_manager_note}\"" if r.note_driver == "disengagement" else ""),
    }
    text = f"{DRIVER_LABEL[primary]} risk: {bits[primary]}"
    if secondary:
        text += f"; also {bits[secondary]}"
    if r.tpv_change_pct <= -10:
        text += f". {v}."
    return text


def diagnose(s: pd.DataFrame) -> pd.DataFrame:
    out = s.copy()
    prim, sec, reason, pb, pb2, cls = [], [], [], [], [], []
    for r in out.itertuples():
        d = _driver_strengths(r)
        ranked = sorted(d.items(), key=lambda kv: kv[1], reverse=True)
        p_drv, p_val = ranked[0]
        s_drv = ranked[1][0] if ranked[1][1] >= 12 else None

        if r.seasonal_decoy:
            prim.append("None (seasonal dip)"); sec.append(None); pb.append("PB-6"); pb2.append(None)
            cls.append("Decoy: seasonal")
            reason.append(f"Seasonal pattern: TPV stepped down {abs(r.m4_step_pct):.0f}% in m4 and rebounded "
                          f"{r.rebound_pct:.0f}% by m6; success rate stable ({r.sr_change_pp:+.1f} pts). Not churn.")
        elif r.risk_label == "Low" and r.healthy_growing:
            prim.append("None (growing)"); sec.append(None); pb.append("PB-5"); pb2.append(None)
            cls.append("Decoy: busy but healthy" if r.support_tickets_last_90d >= 5 else "Healthy, growing")
            reason.append(f"Healthy and growing: TPV up {r.tpv_change_pct:.0f}%, {int(r.support_tickets_last_90d)} tickets "
                          f"in 90 days with {int(r.unresolved_tickets)} unresolved. Expansion opportunity, not churn risk.")
        elif r.risk_label == "Low":
            prim.append("None"); sec.append(None); pb.append("PB-6"); pb2.append(None)
            small_stable = r.tpv_m6_inr_lakh < 5 and abs(r.tpv_change_pct) < 10
            cls.append("Decoy: low-volume stable" if small_stable else "Stable")
            reason.append(("Low volume by nature but stable" if small_stable else "Stable")
                          + f": TPV {r.tpv_change_pct:+.0f}%, success rate {r.sr_change_pp:+.1f} pts, "
                          f"{int(r.unresolved_tickets)} unresolved tickets. No real risk signal.")
        else:
            if p_val < 8:   # volume falling with no explaining driver
                prim.append("Unexplained decline"); sec.append(None); pb.append("PB-4"); pb2.append(None)
                cls.append("At risk")
                reason.append(f"TPV down {abs(r.tpv_change_pct):.0f}% with no clear driver in the data; needs a discovery call.")
            else:
                prim.append(DRIVER_LABEL[p_drv]); sec.append(DRIVER_LABEL[s_drv] if s_drv else None)
                pb.append(DRIVER_PLAYBOOK[p_drv]); pb2.append(DRIVER_PLAYBOOK[s_drv] if s_drv else None)
                cls.append("At risk")
                reason.append(_reason(r, p_drv, s_drv))
    out["primary_driver"], out["secondary_driver"] = prim, sec
    out["playbook"], out["secondary_playbook"] = pb, pb2
    out["classification"], out["reason"] = cls, reason
    return out


# ---------------------------------------------------------------- 4. prioritise
def prioritise(d: pd.DataFrame, cap: int | None = None) -> pd.DataFrame:
    cap = OUTREACH_CAP if cap is None else cap
    p = d.copy()
    # Risk score used as an UNCALIBRATED likelihood proxy (no labels exist).
    p["risk_proxy"] = p["risk_score"] / 100
    # Urgency: churn horizon is 90 days; a renewal inside it is a natural exit point.
    p["urgency"] = np.select([p["days_to_contract_renewal"] <= 30, p["days_to_contract_renewal"] <= 90], [1.25, 1.1], 1.0)
    p["priority_value"] = p["risk_proxy"] * p["annual_value_inr"] * p["urgency"]
    p["expected_net_value_inr"] = p["risk_proxy"] * SAVE_RATE * p["annual_value_inr"] - FALSE_ALARM_COST

    # Eligibility gate: only High-risk merchants compete for CSM slots. Without the
    # gate, a huge healthy enterprise (risk 5) would outrank a sure small churner.
    eligible = (p["risk_label"] == "High") & (p["playbook"].isin(["PB-1", "PB-2", "PB-3", "PB-4"]))
    p["eligible"] = eligible
    p = p.sort_values(["eligible", "priority_value", "risk_score"], ascending=[False, False, False]).reset_index(drop=True)
    p["rank"] = np.arange(1, len(p) + 1)
    p["outreach_this_month"] = p["eligible"] & (p["rank"] <= cap)

    def action(r):
        if r.outreach_this_month:
            return "CSM outreach this month"
        if r.eligible:
            return "Over the call limit: reviewed email now, first call slot next month"
        if r.playbook == "PB-5":
            return "Growth check-in (not counted against churn cap)"
        if r.risk_label == "Medium":
            return "Watchlist: re-score next month"
        return "Monitor only"
    p["action"] = p.apply(action, axis=1)
    return p


# ---------------------------------------------------------------- data pack I/O
REQUIRED_COLUMNS = ["merchant_id", "segment", "industry"] + TPV + [
    "success_rate_m1_m3_pct", "success_rate_m4_m6_pct", "support_tickets_last_90d", "unresolved_tickets",
    "products_used", "logins_last_30d", "days_to_contract_renewal"]
OPTIONAL_COLUMNS = {"business_name": None, "city": "", "tenure_months": np.nan,
                    "last_csat_1_to_5": np.nan, "account_manager_note": None}
DEFAULT_PLAYBOOKS = pd.DataFrame({
    "playbook_id": ["PB-1", "PB-2", "PB-3", "PB-4", "PB-5", "PB-6"],
    "name": ["Performance deep-dive", "Support recovery", "Commercial review", "Re-engagement and adoption",
             "Growth / expansion check-in", "Monitor only"],
    "what_happens": ["Joint call with merchant and Payments Ops to review success-rate drop by method/bank.",
                     "CSM takes ownership of all open tickets and gives a single point of contact.",
                     "Account Manager reviews rate card, volume tiers and renewal terms before the renewal date.",
                     "Executive-sponsor outreach plus a short workshop on unused products and reports.",
                     "Positive check-in; offer new products or higher-limit plans.",
                     "No outreach; keep on watchlist and re-check next month."],
    "when_it_applies": ["Success rate fell", "Unresolved tickets, low CSAT", "Competitor mention, renewal soon",
                        "Low logins, no response", "Healthy and growing", "No real risk signal"]})
DEFAULTS = {"net_revenue_rate": 0.01, "months_value": 12, "false_alarm_cost": 1500, "cap": 15,
            "seasonal_industries": sorted(SEASONAL_INDUSTRIES)}


class DataPackError(ValueError):
    """A problem with the uploaded file, explained in plain words."""


def read_assumptions(a: pd.DataFrame | None, industries) -> tuple[dict, list[str]]:
    """Parse the free-text P2_Assumptions sheet. Anything unreadable falls back to the
    original data pack's value, and is reported so nobody is misled."""
    out, notes = dict(DEFAULTS), []
    if a is None or a.empty or not {"item", "assumption"} <= set(a.columns):
        return out, ["No readable P2_Assumptions sheet: using the original data pack's assumptions."]
    text = {str(k).strip().lower(): str(v) for k, v in zip(a["item"], a["assumption"])}

    def find(key_words, pattern, conv, field, label):
        row = next((v for k, v in text.items() if any(w in k for w in key_words)), None)
        m = re.search(pattern, row or "", re.I)
        if m:
            out[field] = conv(m.group(1))
        else:
            notes.append(f"Couldn't read {label} from the file: using {DEFAULTS[field]}.")
    find(["net revenue"], r"(\d+(?:\.\d+)?)\s*%", lambda x: float(x) / 100, "net_revenue_rate", "net revenue %")
    find(["false alarm", "cost"], r"(?:rs\.?|₹|inr)\s*([\d,]+)", lambda x: int(x.replace(",", "")), "false_alarm_cost", "cost per outreach")
    find(["capacity"], r"(\d+)\s+(?:proactive\s+)?outreach", int, "cap", "outreach capacity")
    find(["value of a saved", "saved merchant"], r"(\d+)\s*months", int, "months_value", "months of value")
    seas = next((v for k, v in text.items() if "season" in k), "")
    found = sorted(i for i in set(industries) if i.split()[0].lower() in seas.lower())
    if found:
        out["seasonal_industries"] = found
    else:
        notes.append("Couldn't match seasonal industries to the data: using the original list.")
    return out, notes


def apply_assumptions(a: dict) -> None:
    global NET_REVENUE_RATE, MONTHS_VALUE, FALSE_ALARM_COST, OUTREACH_CAP, SEASONAL_INDUSTRIES
    NET_REVENUE_RATE, MONTHS_VALUE = a["net_revenue_rate"], a["months_value"]
    FALSE_ALARM_COST, OUTREACH_CAP = a["false_alarm_cost"], a["cap"]
    SEASONAL_INDUSTRIES = set(a["seasonal_industries"])


def load_pack(path) -> tuple[pd.DataFrame, pd.DataFrame, dict, list[str]]:
    """Read and check a data pack. Raises DataPackError with a plain-language message."""
    try:
        sheets = pd.read_excel(path, sheet_name=None)
    except Exception:
        raise DataPackError("This file couldn't be opened as an Excel workbook (.xlsx).")
    if "P2_Merchants" not in sheets:
        raise DataPackError("The file has no sheet called P2_Merchants. Found: " + ", ".join(sheets) + ".")
    raw = sheets["P2_Merchants"].copy()
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise DataPackError("P2_Merchants is missing these columns: " + ", ".join(missing) + ".")
    raw = raw.dropna(subset=["merchant_id"])
    if raw.empty:
        raise DataPackError("P2_Merchants has no merchant rows.")
    if raw["merchant_id"].duplicated().any():
        raise DataPackError("Some merchant_id values appear more than once.")
    num = [c for c in REQUIRED_COLUMNS if c not in ("merchant_id", "segment", "industry")]
    bad = [c for c in num if pd.to_numeric(raw[c], errors="coerce").isna().any()]
    if bad:
        raise DataPackError("These columns have empty or non-numeric values: " + ", ".join(bad) + ".")
    raw[num] = raw[num].apply(pd.to_numeric)
    if (raw[TPV] <= 0).any().any():
        raise DataPackError("Monthly TPV must be above zero for every merchant and month.")
    notes = []
    for c, default in OPTIONAL_COLUMNS.items():
        if c not in raw.columns:
            raw[c] = raw["merchant_id"] if c == "business_name" else default
            notes.append(f"No {c} column: filled with a default.")
    raw["business_name"] = raw["business_name"].fillna(raw["merchant_id"])
    raw["merchant_id"] = raw["merchant_id"].astype(str)
    pb = sheets.get("P2_Playbooks")
    if pb is None or not {"playbook_id", "name", "what_happens"} <= set(pb.columns):
        pb = DEFAULT_PLAYBOOKS.copy(); notes.append("No readable P2_Playbooks sheet: using the original six playbooks.")
    elif not {"PB-1", "PB-2", "PB-3", "PB-4", "PB-5", "PB-6"} <= set(pb.playbook_id):
        pb = DEFAULT_PLAYBOOKS.copy(); notes.append("P2_Playbooks doesn't have PB-1 to PB-6: using the original six.")
    a, an = read_assumptions(sheets.get("P2_Assumptions"), raw["industry"].unique())
    return raw, pb, a, notes + an


def run(path, w: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw, playbooks, a, _ = load_pack(path)
    apply_assumptions(a)
    return prioritise(diagnose(score(features(raw), w))), playbooks


def sensitivity(path: str, n: int = 500, spread: float = 0.3, seed: int = 7) -> pd.DataFrame:
    """Randomly scale every component weight by +/-spread, n times.
    Returns per-merchant share of runs in which it was High risk / in the top 15."""
    rng = np.random.default_rng(seed)
    raw, _, a, _ = load_pack(path)
    apply_assumptions(a)
    base = features(raw)
    hi = pd.Series(0, index=raw["merchant_id"]); top = hi.copy()
    for _ in range(n):
        w = {k: float(rng.uniform(1 - spread, 1 + spread)) for k in DEFAULT_WEIGHTS}
        p = prioritise(diagnose(score(base, w))).set_index("merchant_id")
        hi += (p["risk_label"] == "High").reindex(hi.index).astype(int)
        top += p["outreach_this_month"].reindex(top.index).astype(int)
    return pd.DataFrame({"pct_runs_high": hi / n, "pct_runs_top15": top / n})
