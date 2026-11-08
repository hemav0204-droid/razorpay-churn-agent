"""
Merchant Retention Agent - CSM workspace.   Run:  python -m streamlit run app.py

Built as a tool, not a page: a fixed top bar switches between six views, each view
does one job, and long explanations sit behind click-to-open panels. Every message is
re-checked by the guardrails when edited; nothing is sent automatically.
"""
import hashlib
import json
import os
import tempfile

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import engine as E
import evaluation as V
from outreach import draft, validate, csm_checklist, facts, contact_plan

st.set_page_config(page_title="Merchant Retention Agent", page_icon="📞", layout="wide",
                   initial_sidebar_state="collapsed")

NAVY, BLUE, BTN = "#012652", "#0D94FB", "#0A7BE0"
INK, MUTED, LINE, TINT, TINT2 = "#0F1F3D", "#5B6B86", "#E4EAF2", "#EEF6FF", "#F7FAFE"
RED, AMBER, GREEN = "#E5484D", "#F2A516", "#12B76A"
DRIVER = {
    "Performance": ("Payments failing", BLUE),
    "Service": ("Support problems", AMBER),
    "Pricing / competitive": ("Pricing / other providers", NAVY),
    "Disengagement": ("Going quiet", "#8A97AD"),
    "Unexplained decline": ("Volume falling", "#8A97AD"),
}

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
@import url('https://fonts.googleapis.com/css2?family=TASA+Orbiter:wght@500;600;700;800&display=swap');
html, body, .stMarkdown, p, li, label, input, textarea, button, .rp, .rp * {{
  font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; color: {INK}; }}
[data-testid="stIconMaterial"] {{ font-family: 'Material Symbols Rounded' !important; }}
h1, h2, h3, h4, .disp {{ font-family: 'TASA Orbiter', 'Inter', 'Segoe UI', sans-serif !important; color: {NAVY}; }}
header[data-testid="stHeader"] {{ display: none; }}
.block-container {{ padding-top: 80px !important; max-width: 1240px; }}

/* fixed top bar: always visible, whatever you scroll */
.st-key-topbar {{ position: fixed; top: 0; left: 0; right: 0; z-index: 999991; background: rgba(255,255,255,0.97);
  border-bottom: 1px solid {LINE}; backdrop-filter: blur(6px);
  padding: 12px max(24px, calc((100vw - 1240px) / 2 + 16px)) 10px; }}
.st-key-topbar [data-testid="stHorizontalBlock"] {{ align-items: center; }}
.brand {{ display: flex; align-items: center; gap: 10px; font-weight: 800; font-size: 1.05rem; color: {NAVY};
  white-space: nowrap; }}
.brand .mark {{ flex: none; width: 24px; height: 24px; border-radius: 7px; background: {BLUE}; transform: skew(-12deg); }}
.st-key-topbar [data-testid="stButtonGroup"] button {{ border-radius: 999px !important; font-weight: 600;
  padding-left: 10px !important; padding-right: 10px !important; }}
.st-key-topbar [data-testid="stPopover"] button {{ padding-left: 8px !important; padding-right: 8px !important; white-space: nowrap; }}
.st-key-topbar [data-testid="stButtonGroup"] button[aria-checked="true"],
.st-key-topbar [data-testid="stButtonGroup"] button[kind="segmented_controlActive"] {{
  background: {NAVY} !important; color: #fff !important; border-color: {NAVY} !important; }}
.st-key-topbar [data-testid="stButtonGroup"] button[kind="segmented_controlActive"] * {{ color: #fff !important; }}

.title {{ font-size: 1.85rem !important; font-weight: 800; margin: 4px 0 14px; color: {NAVY}; line-height: 1.2; }}
.tiles {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 0 0 22px; }}
.tile {{ background: {TINT2}; border-radius: 16px; padding: 16px 18px; }}
.tile .v {{ font-family: 'TASA Orbiter','Inter',sans-serif; font-size: 1.9rem; font-weight: 800; color: {NAVY}; line-height: 1.1; }}
.tile .l {{ color: {MUTED}; font-size: 0.86rem; margin-top: 4px; }}
.tile.hero {{ background: {NAVY}; }} .tile.hero .v {{ color: #fff; }} .tile.hero .l {{ color: #B9D3F2; }}
.meter {{ height: 6px; background: {LINE}; border-radius: 9px; margin-top: 10px; overflow: hidden; }}
.meter i {{ display: block; height: 100%; background: {GREEN}; border-radius: 9px; }}

[class*="st-key-card_"] {{ background: #fff; border: 1px solid {LINE}; border-radius: 14px; padding: 12px 14px 8px; }}
[class*="st-key-card_"][class*="_sel"] {{ border: 2px solid {BLUE}; background: {TINT2}; }}
.ctop {{ display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }}
.cname {{ font-weight: 700; color: {NAVY}; }}
.cval {{ font-weight: 800; color: {NAVY}; white-space: nowrap; }}
.cwhy {{ color: {MUTED}; font-size: 0.86rem; margin: 4px 0 0; line-height: 1.35; }}
.chip {{ display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.76rem; font-weight: 600;
  color: #fff !important; margin-top: 6px; }}
.status {{ display: inline-block; font-size: 0.76rem; font-weight: 700; margin-left: 6px; }}

.dhead {{ font-size: 1.75rem !important; font-weight: 800; margin: 0; color: {NAVY}; line-height: 1.15; }}
.dmeta {{ color: {MUTED}; margin: 4px 0 14px; font-size: 0.92rem; }}
.kfacts {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 0 0 12px; }}
.kf {{ background: {TINT2}; border-radius: 14px; padding: 12px 14px; }}
.kf .v {{ font-family: 'TASA Orbiter','Inter',sans-serif; font-size: 1.45rem; font-weight: 800; color: {NAVY}; }}
.kf .l {{ color: {MUTED}; font-size: 0.82rem; margin-top: 2px; line-height: 1.3; }}
.oneline {{ font-size: 1rem; line-height: 1.5; margin: 0 0 6px; }}
.todo {{ background: {NAVY}; border-radius: 14px; padding: 14px 18px; margin: 4px 0 12px; }}
.todo, .todo * {{ color: #fff !important; }}
.todo .k {{ color: #9CC9F5 !important; font-size: 0.8rem; font-weight: 600; }}
.todo .pb {{ font-family: 'TASA Orbiter','Inter',sans-serif; font-weight: 700; font-size: 1.1rem; }}
.todo .plan {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 10px; padding-top: 10px;
  border-top: 1px solid rgba(255,255,255,0.18); font-size: 0.88rem; line-height: 1.4; }}
.sig {{ display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid {LINE}; font-size: 0.9rem; }}
.sig:last-child {{ border-bottom: 0; }}
.dot {{ width: 10px; height: 10px; border-radius: 50%; margin-top: 6px; flex: none; }}
.sig .t {{ font-weight: 600; }} .sig .d {{ color: {MUTED}; }}

.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 0 0 16px; }}
.cards.three {{ grid-template-columns: repeat(3, 1fr); }}
.card {{ border-radius: 16px; padding: 18px; background: #fff; border: 1px solid {LINE}; }}
.card .big {{ font-family: 'TASA Orbiter','Inter',sans-serif; font-size: 1.9rem; font-weight: 800; color: {NAVY}; margin: 8px 0 0; }}
.card .l {{ color: {MUTED}; font-size: 0.86rem; }}
.card .fix {{ margin-top: 10px; font-size: 0.88rem; line-height: 1.45; padding-top: 10px; border-top: 1px solid {LINE}; }}
.small {{ color: {MUTED}; font-size: 0.85rem; }}

.stButton button {{ border-radius: 999px; font-weight: 600; }}
.stButton button[kind="primary"] *, .stDownloadButton button[kind="primary"] * {{ color: #fff !important; }}
.st-key-topbar [data-testid="stButtonGroup"] button[aria-checked="true"] *,
.st-key-topbar [data-testid="stButtonGroup"] button[aria-pressed="true"] *,
.st-key-topbar [data-testid="stButtonGroup"] button[kind*="Active"] * {{ color: #fff !important; }}
.st-key-topbar [data-testid="stButtonGroup"] button[aria-pressed="true"],
.st-key-topbar [data-testid="stButtonGroup"] button[kind*="Active"] {{ background: {NAVY} !important; border-color: {NAVY} !important; }}
.stButton button[kind="primary"] {{ background: {BTN}; border-color: {BTN}; color: #fff; }}
.stButton button[kind="primary"]:hover {{ background: {NAVY}; border-color: {NAVY}; }}
[data-testid="stExpander"] details {{ border-radius: 12px; }}

@media (max-width: 900px) {{
  .tiles, .cards, .cards.three, .kfacts {{ grid-template-columns: 1fr 1fr; }}
  .block-container {{ padding-top: 150px !important; }}
}}
</style>
""", unsafe_allow_html=True)


BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_pack.xlsx")


@st.cache_data
def load(path):
    raw, pb, a, notes = E.load_pack(path)
    E.apply_assumptions(a)
    p = E.prioritise(E.diagnose(E.score(E.features(raw))))
    p["draft"] = [draft(r) if r.eligible else "" for r in p.itertuples()]
    p["draft_email"] = [draft(r, "email") if r.eligible else "" for r in p.itertuples()]
    p["checklist"] = [csm_checklist(r) if r.eligible else "" for r in p.itertuples()]
    p["reason_plain"] = p["primary_driver"].map(lambda d: DRIVER.get(d, ("No risk", MUTED))[0])
    p["short_why"] = [short_why(r) for r in p.itertuples()]
    return p, pb, a, notes


@st.cache_data
def evidence(path):
    raw, _, a, _ = E.load_pack(path)
    E.apply_assumptions(a)
    abl = V.ablation(raw)
    sens = E.sensitivity(path, n=150)
    E.apply_assumptions(a)
    return abl, V.guardrail_eval(), sens


@st.cache_data
def rule_tests():
    """The 52 hand-written tests only make sense for the original data pack."""
    import run_agent as RA
    q = load(BUNDLED)[0]
    raw, _, a, _ = E.load_pack(BUNDLED)
    t = pd.concat([RA.real_row_tests(q), RA.synthetic_cases(raw)], ignore_index=True)
    return int((t.result == "PASS").sum()), len(t)


@st.cache_resource
def ref_merchant():
    return V.reference_merchant()


def file_hash(path):
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def on_upload():
    up = st.session_state.get("uploader")
    if up is None:
        return
    tmp = os.path.join(tempfile.gettempdir(), "retention_" + hashlib.md5(up.getvalue()).hexdigest()[:12] + ".xlsx")
    with open(tmp, "wb") as fh:
        fh.write(up.getvalue())
    try:
        E.load_pack(tmp)
    except E.DataPackError as e:
        st.session_state.upload_error = f"{up.name}: {e}"
        return
    reset_workspace()
    st.session_state.data_path, st.session_state.data_name = tmp, up.name
    st.session_state.upload_error = None


def reset_workspace():
    for k in list(st.session_state.keys()):
        if k in ("decisions", "pick", "pick_call", "pick_email", "lane", "notes", "cap_saved", "save_saved") \
                or str(k).startswith(("approved_text_", "msg_", "note_")):
            del st.session_state[k]


def back_to_original():
    reset_workspace()
    st.session_state.data_path, st.session_state.data_name = BUNDLED, "data_pack.xlsx (original)"
    st.session_state.upload_error = None


def ai_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
            return True
    except Exception:
        pass
    return False


@st.cache_data(show_spinner=False)
def ai_review(text, facts_json):
    from llm_layer import review_message
    return review_message(text, facts_json)


def short_why(r) -> str:
    d = r.primary_driver
    if d == "Performance":
        return f"Payment success fell {abs(r.sr_change_pp):.1f} pts; volume down {abs(r.tpv_change_pct):.0f}%"
    if d == "Service":
        rating = f", last rating {int(r.last_csat_1_to_5)}/5" if r.last_csat_1_to_5 == r.last_csat_1_to_5 else ""
        return f"{int(r.unresolved_tickets)} tickets still open{rating}"
    if d == "Pricing / competitive":
        what = "Asked for rate card" if r.note_category == "pricing_renewal" else "Looking at other providers"
        return f"{what}; renews in {int(r.days_to_contract_renewal)} days"
    if d in ("Disengagement", "Unexplained decline"):
        lg = int(r.logins_last_30d)
        return f"{lg} login{'' if lg == 1 else 's'} in 30 days; volume down {abs(r.tpv_change_pct):.0f}%"
    return ""


def plain_reason(r) -> str:
    """The engine's reason, rewritten without jargon for the CSM."""
    vol = (f" Monthly payments fell {abs(r.tpv_change_pct):.0f}%, from about ₹{r.tpv_baseline_m1_m3:.1f} lakh "
           f"to ₹{r.tpv_m6_inr_lakh:.1f} lakh.") if r.tpv_change_pct <= -10 else ""
    note = f" The account manager noted: “{r.account_manager_note}”." if isinstance(r.account_manager_note, str) else ""
    d = r.primary_driver
    if d == "Performance":
        main = (f"Fewer of this merchant's customer payments are going through: success fell from "
                f"{r.success_rate_m1_m3_pct:.1f}% to {r.success_rate_m4_m6_pct:.1f}%.")
    elif d == "Service":
        main = f"{int(r.unresolved_tickets)} support tickets are still open and the merchant is unhappy with support."
    elif d == "Pricing / competitive":
        main = f"The merchant is weighing its options ahead of a renewal in {int(r.days_to_contract_renewal)} days."
    elif d == "Disengagement":
        main = (f"The merchant has almost stopped using Razorpay's dashboard "
                f"({int(r.logins_last_30d)} logins in 30 days) and volume is falling every month.")
    else:
        main = "Volume is falling without a clear cause in the data."
    extra = ""
    if isinstance(r.secondary_driver, str):
        extra = {"Service": f" There are also {int(r.unresolved_tickets)} open support tickets.",
                 "Performance": " Payment success is also slipping.",
                 "Pricing / competitive": f" The contract also renews in {int(r.days_to_contract_renewal)} days.",
                 "Disengagement": " Dashboard use is also low."}.get(r.secondary_driver, "")
    return main + extra + vol + note


def plain_cleared(r) -> str:
    """Why a merchant is NOT on the call list, in plain words."""
    c = r.classification
    if "seasonal" in c:
        return (f"Dropped {abs(r.m4_step_pct):.0f}% in month 4, then bounced back {r.rebound_pct:.0f}% by month 6, "
                f"like a normal post-festive dip. Payment success steady.")
    if "busy" in c or "growing" in c.lower():
        return (f"Growing: volume up {r.tpv_change_pct:.0f}%. {int(r.support_tickets_last_90d)} tickets in 90 days, "
                f"{int(r.unresolved_tickets)} still open. Busy, not unhappy.")
    if "low-volume" in c:
        return f"Small and steady: volume {r.tpv_change_pct:+.0f}%, payment success steady. Small is normal for them."
    return "No warning signs: volume, payments and support all steady."


def signals(r):
    """Plain-language evidence with a traffic light: (colour, title, detail)."""
    out = []
    chg = r.tpv_change_pct
    if r.seasonal_decoy:
        c, t = AMBER, "Payment volume: seasonal dip"
    elif chg <= -15:
        c, t = RED, f"Payment volume down {abs(chg):.0f}%"
    elif chg <= -5:
        c, t = AMBER, f"Payment volume down {abs(chg):.0f}%"
    else:
        c, t = GREEN, f"Payment volume {'up' if chg > 0 else 'steady'} ({chg:+.0f}%)"
    months = ", ".join(f"{r[f'tpv_m{i}_inr_lakh']:.1f}" for i in range(1, 7))
    out.append((c, t, f"₹ lakh per month, oldest to newest: {months}"))

    sr = r.sr_change_pp
    c = RED if sr <= -5 else AMBER if sr <= -2 else GREEN
    out.append((c, "Payment success " + ("fell sharply" if sr <= -5 else "slipped" if sr <= -2 else "steady"),
                f"{r.success_rate_m1_m3_pct:.1f}% before, {r.success_rate_m4_m6_pct:.1f}% in the last 3 months"))

    u, cs = int(r.unresolved_tickets), r.last_csat_1_to_5
    low = cs == cs and cs <= 2
    c = RED if (u >= 3 or low) else AMBER if u >= 1 else GREEN
    rating = f"last rating {int(cs)}/5" if cs == cs else "no rating given"
    out.append((c, "Support " + ("needs attention" if c == RED else "mostly fine" if c == AMBER else "healthy"),
                f"{u} open of {int(r.support_tickets_last_90d)} tickets in 90 days, {rating}"))

    lg = int(r.logins_last_30d)
    c = RED if lg <= 3 else AMBER if lg <= 10 else GREEN
    out.append((c, "Dashboard use " + ("very low" if lg <= 3 else "low" if lg <= 10 else "active"),
                f"{lg} login{'' if lg == 1 else 's'} in 30 days, uses {int(r.products_used)} product{'' if int(r.products_used) == 1 else 's'}"))

    note = r.account_manager_note if isinstance(r.account_manager_note, str) else ""
    risky = r.note_category in ("competitive", "pricing_renewal", "performance_issue", "service_issue", "disengagement")
    out.append((RED if risky else GREEN if note else LINE, "Account manager says",
                f"“{note}”" if note else "No note"))

    dr = int(r.days_to_contract_renewal)
    out.append((AMBER if dr <= 60 else GREEN, f"Contract renews in {dr} days",
                "Inside the 90-day window: a natural moment to switch" if dr <= 90 else "Not urgent"))
    return out


def chip(driver):
    name, col = DRIVER.get(driver, ("No risk", MUTED))
    return f'<span class="chip" style="background:{col}">{name}</span>'


def tiles(items, hero_first=True):
    out = ""
    for k, (v, l, extra) in enumerate(items):
        cls = "tile hero" if (hero_first and k == 0) else "tile"
        out += f'<div class="{cls}"><div class="v">{v}</div><div class="l">{l}</div>{extra}</div>'
    return f'<div class="rp tiles">{out}</div>'


def title(text):
    st.markdown(f'<div class="title disp">{text}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- state & data
ss = st.session_state
ss.setdefault("data_path", BUNDLED); ss.setdefault("data_name", "data_pack.xlsx (original)")
path = ss.data_path
try:
    p0, playbooks, A, pack_notes = load(path)
except E.DataPackError as e:      # a file that was fine earlier but no longer loads
    back_to_original(); st.error(str(e)); st.stop()
E.apply_assumptions(A)
OUTREACH_CAP, FALSE_ALARM_COST = A["cap"], A["false_alarm_cost"]
is_original = file_hash(path) == file_hash(BUNDLED)
pbk = playbooks.set_index("playbook_id")
n_eligible = int(p0.eligible.sum())
ss.setdefault("decisions", {}); ss.setdefault("notes", {})
ss.setdefault("lane", "call"); ss.setdefault("pick_call", 0); ss.setdefault("pick_email", 0)
ss.setdefault("cap_saved", OUTREACH_CAP); ss.setdefault("save_saved", 25); ss.setdefault("view_saved", "Call list")
cap = int(min(ss.cap_saved, n_eligible))
save_rate = ss.save_saved / 100
p = E.prioritise(p0, cap=cap)
for col in ("draft", "draft_email", "checklist", "reason_plain", "short_why"):
    p[col] = p0.set_index("merchant_id").loc[p.merchant_id, col].values

call = p[p.outreach_this_month].reset_index(drop=True)
over = p[p.eligible & ~p.outreach_this_month].reset_index(drop=True)
hi = p[p.risk_label == "High"]
dec = p[p.classification.str.startswith("Decoy")]
covered = call.annual_value_inr.sum()

# ---------------------------------------------------------------- fixed top bar
PLAN = f"Is {OUTREACH_CAP} enough?"
VIEWS = {"Call list": ":material/call:", PLAN: ":material/tune:", "Why they leave": ":material/insights:",
         "False alarms": ":material/notifications_off:", "Testing": ":material/fact_check:",
         "All merchants": ":material/table_rows:"}


def _keep_view():
    if ss.view_w:
        ss.view_saved = ss.view_w


if ss.view_saved not in VIEWS:          # e.g. the old "Plan" name, or a new pack with a different cap
    ss.view_saved = "Call list"

with st.container(key="topbar"):
    b1, b2, b3, b4 = st.columns([0.95, 4.6, 0.8, 0.62], vertical_alignment="center")
    b1.markdown('<div class="rp brand"><span class="mark"></span>Retention Agent</div>', unsafe_allow_html=True)
    b2.segmented_control("View", list(VIEWS), default=ss.view_saved, key="view_w", on_change=_keep_view,
                         format_func=lambda v: f"{VIEWS[v]} {v}", label_visibility="collapsed")
    with b3.popover("Data pack", icon=":material/upload_file:", width="stretch"):
        st.markdown(f"**In use:** {ss.data_name}  \n{len(p0)} merchants, {A['cap']} calls a month, "
                    f"₹{A['false_alarm_cost']:,} per call")
        st.file_uploader("Upload a new data pack (.xlsx)", type="xlsx", key="uploader", on_change=on_upload,
                         help="Needs a P2_Merchants sheet with the same columns as the original. "
                              "P2_Playbooks and P2_Assumptions are read if present.")
        st.caption("Everything recalculates for the new file. Your approvals start fresh.")
        if not is_original:
            st.button("Back to the original data pack", on_click=back_to_original, icon=":material/undo:")
    with b4.popover("Help", icon=":material/help:"):
        st.markdown(
            "**Monthly payments**: money a merchant collects through Razorpay each month (₹ lakh).  \n"
            "**Payment success**: share of customer payments that go through.  \n"
            "**Risk score 0-100**: a ranking of warning signs, not a % chance. There's no history of who left.  \n"
            "**Yearly revenue**: what Razorpay earns from the merchant, 1% of monthly payments x 12.  \n"
            f"**Cost of a call**: about ₹{FALSE_ALARM_COST:,} of CSM time.")
        st.divider()
        st.markdown(
            f"**Call list**: your work for the month: {OUTREACH_CAP} calls, plus a reviewed email for every other "
            "at-risk merchant.  \n"
            f"**{PLAN}**: what the call limit protects, and what it costs.  \n"
            "**Why they leave**: the causes, and the fix that would stop them next month.  \n"
            "**False alarms**: merchants that look risky but aren't, and why.  \n"
            "**Testing**: how it was checked, including what fails.  \n"
            "**All merchants**: all merchants, ranked, with the reason for each.")
view = ss.view_saved
if ss.get("upload_error"):
    st.error(f"That file wasn't loaded. {ss.upload_error} The previous data pack is still in use.",
             icon=":material/error:")
if not is_original:
    bn1, bn2 = st.columns([5, 1.2], vertical_alignment="center")
    a_txt = (f"{A['cap']} calls, ₹{A['false_alarm_cost']:,} per call, {A['net_revenue_rate']:.1%} net revenue, "
             f"{A['months_value']} months of value")
    bn1.info(f"Using **{ss.data_name}**: {len(p0)} merchants. Assumptions read from the file: {a_txt}."
             + ("  \n" + " ".join(pack_notes) if pack_notes else ""), icon=":material/upload_file:")
    bn2.button("Back to original", on_click=back_to_original, icon=":material/undo:", width="stretch")

done = ss.decisions
work = pd.concat([call.assign(lane="call"), over.assign(lane="email")], ignore_index=True)
n_ok = sum(done.get(m) == "Approved" for m in work.merchant_id)


def handoff_sheet():
    """Everything the CSM decided, one row per at-risk merchant, ready to hand to the team."""
    rows = []
    for w in work.itertuples():
        cp = contact_plan(w, w.lane)
        rows.append({"priority": w.rank, "merchant_id": w.merchant_id, "business_name": w.business_name,
                     "size": w.segment, "channel": "Call" if w.lane == "call" else "Email",
                     "how": cp["how"], "who_is_involved": cp["who"], "follow_up": cp["next"],
                     "reason": w.reason_plain, "playbook": w.playbook,
                     "yearly_revenue_inr": int(w.annual_value_inr),
                     "checks_before_sending": w.checklist, "status": done.get(w.merchant_id, "Not reviewed"),
                     "csm_note": ss.notes.get(w.merchant_id, ""),
                     "approved_message": ss.get(f"approved_text_{w.merchant_id}", "")})
    return pd.DataFrame(rows)


# ================================================================ CALL LIST
if view == "Call list" and len(work) == 0:
    title("No merchant needs a call this month")
    st.markdown(tiles([("0 calls", "to make this month", ""), (f"{len(p)}", "merchants checked", ""),
                       (f"{len(dec)}", "false alarms skipped", ""), (f"{int((p.risk_label == 'Low').sum())}", "low risk", "")]),
                unsafe_allow_html=True)
    st.info("No merchant shows two or more warning signs together. Check again next month, or open "
            "All merchants to see the full list.", icon=":material/task_alt:")

elif view == "Call list":
    email_txt = f" + {len(over)} emails" if len(over) else ""
    st.markdown(tiles([
        (f"{len(call)} calls{email_txt}", "every at-risk merchant gets contacted", ""),
        (f"₹{covered/1e5:.1f} L", f"yearly revenue in the {len(call)} calls ({covered/max(hi.annual_value_inr.sum(), 1):.0%} of at-risk)", ""),
        (f"{len(dec)}", "false alarms skipped", ""),
        (f"{n_ok} of {len(work)}", "messages approved",
         f'<div class="meter"><i style="width:{n_ok/len(work)*100:.0f}%"></i></div>'),
    ]), unsafe_allow_html=True)

    STATUS_COL = {"Approved": GREEN, "Need more info": AMBER, "Skipped": MUTED}
    left, right = st.columns([0.9, 1.65], gap="large")
    with left:
        if len(over):
            lanes = {"call": f"Calls ({len(call)})", "email": f"Emails ({len(over)})"}
            ln = st.segmented_control("List", list(lanes), default=ss.lane, format_func=lanes.get,
                                      key=f"lane_w_{ss.lane}", label_visibility="collapsed")
            if ln and ln != ss.lane:
                ss.lane = ln; st.rerun()
        else:
            ss.lane = "call"
        lst = call if ss.lane == "call" else over
        pk = f"pick_{ss.lane}"
        if ss[pk] >= len(lst):
            ss[pk] = 0
        if ss.lane == "email":
            st.caption(f"Over this month's limit of {len(call)} calls. Each gets a reviewed email now and "
                       "the first call slots next month.")
        with st.container(height=720, border=False):
            for i, c in lst.iterrows():
                sel = i == ss[pk]
                with st.container(key=f"card_{c.merchant_id}{'_sel' if sel else ''}"):
                    stt = done.get(c.merchant_id)
                    badge = f'<span class="status" style="color:{STATUS_COL[stt]}">● {stt}</span>' if stt else ""
                    renew = (f'<span class="status" style="color:{RED}">● Renews in {int(c.days_to_contract_renewal)} days</span>'
                             if ss.lane == "email" and c.days_to_contract_renewal <= 30 else "")
                    st.markdown(f'<div class="rp"><div class="ctop"><span class="cname">{c["rank"]}. {c.business_name}</span>'
                                f'<span class="cval">₹{c.annual_value_inr/1e5:.1f} L</span></div>'
                                f'<div class="cwhy">{c.segment} · {c.short_why}</div>{chip(c.primary_driver)}{badge}{renew}</div>',
                                unsafe_allow_html=True)
                    if not sel and st.button("Open", key=f"open_{c.merchant_id}", width="stretch"):
                        ss[pk] = i; st.rerun()

    r = lst.iloc[ss[pk]]
    lane = ss.lane
    with right:
        kf = [(f"{r.tpv_change_pct:+.0f}%", "monthly payments")]
        d = r.primary_driver
        kf.append((f"{r.sr_change_pp:+.1f} pts", "payment success") if d == "Performance" else
                  (f"{int(r.unresolved_tickets)} open", "support tickets") if d == "Service" else
                  (f"{int(r.days_to_contract_renewal)} days", "to renewal") if d == "Pricing / competitive" else
                  (f"{int(r.logins_last_30d)}", "logins in 30 days"))
        kf.append((f"₹{r.annual_value_inr/1e5:.1f} L", "yearly revenue"))
        first = plain_reason(r).split(". ")[0].rstrip(".") + "."
        st.markdown(f'<div class="rp"><div class="dhead disp">{r.business_name}</div>'
                    f'<div class="dmeta">{r.segment}, {r.industry}, {r.city} {chip(r.primary_driver)}</div>'
                    '<div class="kfacts">' + "".join(f'<div class="kf"><div class="v">{v}</div><div class="l">{l}</div></div>'
                                                     for v, l in kf) +
                    f'</div><p class="oneline">{first}</p></div>', unsafe_allow_html=True)

        tpv = pd.DataFrame({"Month": [f"M{k}" for k in range(1, 7)],
                            "₹ lakh": [r[f"tpv_m{k}_inr_lakh"] for k in range(1, 7)]})
        ch = alt.Chart(tpv).mark_line(color=BLUE, strokeWidth=3.5,
                                      point=alt.OverlayMarkDef(color=BLUE, size=80, filled=True)).encode(
            x=alt.X("Month:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("₹ lakh:Q", scale=alt.Scale(zero=False, padding=12), title="₹ lakh / month"),
            tooltip=["Month", "₹ lakh"])
        st.altair_chart(ch.properties(height=150).configure_view(strokeWidth=0)
                        .configure_axis(gridColor=LINE, domain=False), width="stretch")
        with st.expander("Full story and all signals"):
            st.markdown(f'<div class="rp"><p class="oneline">{plain_reason(r)}</p>' + "".join(
                f'<div class="sig"><span class="dot" style="background:{c}"></span><div><span class="t">{t}</span>'
                f'<br><span class="d">{dd}</span></div></div>' for c, t, dd in signals(r)) + "</div>", unsafe_allow_html=True)

        pb = pbk.loc[r.playbook]
        also = f" + {r.secondary_playbook}" if isinstance(r.secondary_playbook, str) else ""
        cp = contact_plan(r, lane)
        st.markdown(f'<div class="rp todo"><div class="k">What to do</div><div class="pb">{pb["name"]} ({r.playbook}{also})</div>'
                    f'<div class="plan"><div><span class="k">How</span><br>{cp["how"]}</div>'
                    f'<div><span class="k">Who</span><br>{cp["who"]}</div>'
                    f'<div><span class="k">Then</span><br>{cp["next"]}</div></div></div>',
                    unsafe_allow_html=True)
        with st.expander(f"How, and {len(r.checklist.split('; '))} checks before sending"):
            st.markdown(pb["what_happens"])
            st.markdown("\n".join(f"- {c[0].upper() + c[1:]}" for c in r.checklist.split("; ")))

        base = r.draft if lane == "call" else r.draft_email
        text = st.text_area("Message" if lane == "call" else "Email (no call this month)", base, height=220,
                            key=f"msg_{lane}_{r.merchant_id}")
        issues = validate(text, r)
        if not issues and ai_key():
            rv = ai_review(text, json.dumps(facts(r), default=str))
            if rv["available"] and rv["block"]:
                issues = ["AI reviewer: " + "; ".join(rv["reasons"])]
        if issues:
            st.error("Can't approve: " + "; ".join(issues), icon=":material/block:")
        else:
            st.success("Ready to send", icon=":material/check_circle:")
        note = st.text_input("Note for the team (optional)", ss.notes.get(r.merchant_id, ""),
                             placeholder="e.g. owner changed, call back after Diwali", key=f"note_{r.merchant_id}")
        ss.notes[r.merchant_id] = note
        c1, c2, c3 = st.columns([1.3, 1, 1])

        def _next():
            ss[pk] = min(ss[pk] + 1, len(lst) - 1)
        if c1.button("Approve", type="primary", icon=":material/check:", disabled=bool(issues),
                     key=f"ok_{r.merchant_id}", width="stretch"):
            done[r.merchant_id] = "Approved"; ss[f"approved_text_{r.merchant_id}"] = text; _next(); st.rerun()
        if c2.button("Need info", key=f"info_{r.merchant_id}", width="stretch"):
            done[r.merchant_id] = "Need more info"; ss.pop(f"approved_text_{r.merchant_id}", None); st.rerun()
        if c3.button("Skip", key=f"skip_{r.merchant_id}", width="stretch"):
            done[r.merchant_id] = "Skipped"; ss.pop(f"approved_text_{r.merchant_id}", None); st.rerun()

    n_rev = sum(m in done for m in work.merchant_id)
    st.download_button(f"Download hand-off sheet ({n_rev} of {len(work)} reviewed)", handoff_sheet().to_csv(index=False),
                       "csm_handoff.csv", icon=":material/download:",
                       help="One row per at-risk merchant: channel, who's involved, status, your note and the approved message.")

# ================================================================ IS 15 ENOUGH?
elif view == PLAN and n_eligible == 0:
    title(PLAN)
    st.info("No merchant is at risk in this data pack, so there's nothing to plan.", icon=":material/task_alt:")

elif view == PLAN:
    curve = V.capacity_curve(p0, save_rate)
    sel = curve[curve.call_no <= cap]
    rest = curve[curve.call_no > cap]
    share = sel.share_covered.iloc[-1]
    exp_saved = (sel.risk_score / 100 * save_rate * sel.annual_value_inr).sum()
    cost = cap * FALSE_ALARM_COST
    smallest = sel.loc[sel.annual_value_inr.idxmin()]
    pos = int((curve.expected_value_of_call > 0).sum())
    if len(rest):
        title(f"{'Yes' if share >= 0.9 else 'Mostly'}: {cap} calls protect {share:.0%} of the revenue at risk")
        st.markdown(f'<p class="oneline">The other {len(rest)} at-risk merchants are worth ₹{rest.annual_value_inr.sum()/1e5:.2f} L '
                    f'a year together. They get a reviewed email now and the first call slots next month, '
                    f'so no at-risk merchant goes uncontacted.</p>', unsafe_allow_html=True)
    else:
        title(f"Yes: {cap} calls reach every at-risk merchant")
    st.markdown(tiles([
        (f"₹{sel.annual_value_inr.sum()/1e5:.1f} L", f"yearly revenue in the {cap} calls ({share:.0%})", ""),
        (f"₹{cost:,}", f"cost of {cap} calls; also the most a month of false alarms can cost", ""),
        (f"₹{exp_saved/1e5:.1f} L", f"expected revenue kept, if {save_rate:.0%} of called merchants stay", ""),
        (f"{exp_saved/max(cost, 1):,.0f}x", "expected return on CSM time (rough: treats the risk score as a chance of leaving)", ""),
    ]), unsafe_allow_html=True)

    st.markdown("**False alarms vs merchants saved**")
    st.markdown(
        f"- A wrong call (a merchant who wasn't leaving) costs ₹{FALSE_ALARM_COST:,} of CSM time. "
        f"Even if all {cap} were wrong, the loss is ₹{cost:,}.\n"
        f"- Keeping just **one** merchant pays for the whole month: the smallest on the list, "
        f"{smallest.business_name}, is worth ₹{smallest.annual_value_inr/1e5:.2f} L a year, "
        f"{smallest.annual_value_inr/max(cost,1):.0f}x the cost of all {cap} calls.\n"
        f"- So a missed churner is far more expensive than a false alarm. That's why the agent picks "
        f"the biggest at-risk merchants first, and keeps decoys out with the two-or-more-signs rule "
        f"({len(dec)} false alarms avoided, ₹{len(dec)*FALSE_ALARM_COST:,} of CSM time saved).")

    st.markdown("**What if the team had more or fewer calls?**")

    def _keep_cap(): ss.cap_saved = ss.cap_w
    def _keep_save(): ss.save_saved = ss.save_w

    def _reset_cap(): ss.cap_saved = OUTREACH_CAP; ss.pop("cap_w", None)

    g1, g2 = st.columns([1.7, 1], gap="large")
    with g2:
        if n_eligible > 1:
            st.slider("Calls this month", 1, n_eligible, value=max(cap, 1), key="cap_w", on_change=_keep_cap,
                      help="Changes the Call list too. The data pack's limit is " + str(OUTREACH_CAP) + ".")
            if cap != min(OUTREACH_CAP, n_eligible):
                st.button(f"Back to the limit of {OUTREACH_CAP}", on_click=_reset_cap, icon=":material/undo:")
        else:
            st.markdown("Only one merchant is at risk, so the plan is one call.")
        st.select_slider("Save rate: of the leaving merchants we call, how many stay?", options=[10, 15, 20, 25, 30, 40, 50],
                         value=ss.save_saved, key="save_w", on_change=_keep_save, format_func=lambda v: f"{v}%",
                         help="Not in the data pack: 25% is our assumption. Try 10% to see the plan still holds.")
        st.caption(f"{pos} of {n_eligible} possible calls are worth more than they cost at this save rate. "
                   "The line flattens because the biggest merchants come first.")
    with g1:
        cv = curve.assign(Calls=curve.call_no, Covered=curve.revenue_covered / 1e5,
                          Pays=np.where(curve.expected_value_of_call > 0, "Yes", "No"))
        line = alt.Chart(cv).mark_line(color=NAVY, strokeWidth=3).encode(
            x=alt.X("Calls:Q", scale=alt.Scale(domain=[0, n_eligible]), title="Calls this month, biggest first"),
            y=alt.Y("Covered:Q", title="Yearly revenue covered (₹ lakh)"))
        dots = alt.Chart(cv).mark_circle(size=90).encode(
            x="Calls:Q", y="Covered:Q",
            color=alt.Color("Pays:N", scale=alt.Scale(domain=["Yes", "No"], range=[BLUE, RED]),
                            legend=alt.Legend(orient="bottom", title="Worth more than it costs?")),
            tooltip=["Calls", alt.Tooltip("business_name", title="Merchant"),
                     alt.Tooltip("Covered:Q", title="₹ lakh covered", format=".1f"),
                     alt.Tooltip("expected_value_of_call:Q", title="Value of call (₹)", format=",.0f")])
        rule = alt.Chart(pd.DataFrame({"x": [cap]})).mark_rule(color=BLUE, strokeDash=[6, 4], strokeWidth=2).encode(x="x:Q")
        st.altair_chart((line + dots + rule).properties(height=320).configure_view(strokeWidth=0)
                        .configure_axis(gridColor=LINE, domain=False), width="stretch")

# ================================================================ WHY THEY LEAVE
elif view == "Why they leave" and len(hi) == 0:
    title("No merchant is at risk")
    st.info("There are no churn drivers to show for this data pack.", icon=":material/task_alt:")

elif view == "Why they leave":
    g = (hi.groupby("primary_driver").agg(n=("merchant_id", "count"), called=("outreach_this_month", "sum"),
                                          value=("annual_value_inr", "sum")).reset_index().sort_values("value", ascending=False))
    title(f"{DRIVER[g.iloc[0].primary_driver][0]} puts the most revenue at risk")
    FIX = {"Payments failing": "Alert Payments Ops when success drops 5+ pts",
           "Support problems": "Auto-escalate merchants with 3+ open tickets",
           "Pricing / other providers": "Start pricing reviews 60 days before renewal",
           "Going quiet": "Re-onboard when the owner or manager changes"}
    st.markdown('<div class="rp cards">' + "".join(
        f'<div class="card">{chip(x.primary_driver)}<div class="big">₹{x.value/1e5:.1f} L</div>'
        f'<div class="l">{x.n} merchants, {x.called} called</div>'
        f'<div class="fix"><b>Fix:</b> {FIX[DRIVER[x.primary_driver][0]]}</div></div>' for x in g.itertuples()) + "</div>",
        unsafe_allow_html=True)
    g["Reason"] = g.primary_driver.map(lambda d: DRIVER[d][0]); g["₹ L"] = (g.value / 1e5).round(1)
    order = g.Reason.tolist()
    bars = alt.Chart(g).mark_bar(cornerRadiusEnd=5, height=30).encode(
        y=alt.Y("Reason:N", sort=order, title=None, axis=alt.Axis(labelLimit=260, labelFontSize=13)),
        x=alt.X("₹ L:Q", title="Yearly revenue at risk (₹ lakh)", scale=alt.Scale(domain=[0, float(g["₹ L"].max()) * 1.15])),
        color=alt.Color("Reason:N", legend=None, scale=alt.Scale(domain=[DRIVER[k][0] for k in DRIVER], range=[DRIVER[k][1] for k in DRIVER])))
    lab = alt.Chart(g).mark_text(align="left", dx=6, fontSize=13, color=INK).encode(
        y=alt.Y("Reason:N", sort=order), x="₹ L:Q", text=alt.Text("₹ L:Q", format=".1f"))
    st.altair_chart((bars + lab).properties(height=200).configure_view(strokeWidth=0)
                    .configure_axis(gridColor=LINE, domain=False), width="stretch")

# ================================================================ FALSE ALARMS
elif view == "False alarms" and len(dec) == 0:
    title("No false alarms in this data pack")
    st.info("No merchant shows a single warning sign that turned out to be harmless.", icon=":material/task_alt:")

elif view == "False alarms":
    title(f"{len(dec)} merchants look risky but aren't leaving")
    kinds = dec.classification.str.replace("Decoy: ", "")
    fa = [("seasonal", ":material/calendar_month:", "Seasonal dip", "Drops after the festive season, bounces back"),
          ("busy but healthy", ":material/trending_up:", "Busy and growing", "Many tickets, almost all resolved"),
          ("low-volume stable", ":material/storefront:", "Small and steady", "Always small, not falling")]
    st.markdown('<div class="rp cards three">' + "".join(
        f'<div class="card"><div class="big">{(kinds == k).sum()}</div><b>{t}</b><div class="l">{d}</div></div>'
        for k, ic, t, d in fa) + "</div>", unsafe_allow_html=True)
    st.markdown(f'<p class="small">Calling them would have used ₹{len(dec)*FALSE_ALARM_COST:,} of CSM time.</p>',
                unsafe_allow_html=True)
    pick = st.segmented_control("Show", ["All", "Seasonal dip", "Busy and growing", "Small and steady"], default="All",
                                key="fa_filter", label_visibility="collapsed")
    mapk = {"Seasonal dip": "seasonal", "Busy and growing": "busy but healthy", "Small and steady": "low-volume stable"}
    dd = dec if pick in (None, "All") else dec[kinds == mapk[pick]]
    st.dataframe(pd.DataFrame({"Merchant": dd.business_name, "Industry": dd.industry,
                               "Volume": dd.tpv_change_pct.round(0).astype(int).astype(str) + "%",
                               "Why we're not calling": [plain_cleared(x) for x in dd.itertuples()]}),
                 hide_index=True, height=420, width="stretch",
                 column_config={"Why we're not calling": st.column_config.TextColumn(width=560)})

# ================================================================ TESTING
elif view == "Testing":
    title("How we tested it, including what failed")
    with st.spinner("Running 150 random weight changes..."):
        abl, (gr_rows, gr_sum), sens = evidence(path)
    held = gr_sum.set_index("Set").loc["Held-out (never tuned on)"]
    dev_ = gr_sum.set_index("Set").loc["Development (tuned on)"]
    sv = sens.reindex(p.merchant_id)
    ever = int((sv.loc[sv.index.isin(set(dec.merchant_id)), "pct_runs_high"] > 0).sum())
    if is_original:
        n_pass, n_tests = rule_tests()
        rule_tile = (f"{n_pass} of {n_tests}", f"rule tests pass ({n_tests - n_pass} are known blind spots)", "")
    else:
        rule_tile = ("Not run", "rule tests are written for the original data pack", "")
    st.markdown(tiles([
        rule_tile,
        (f"{ever} of {len(dec)}" if len(dec) else "None", "false alarms ever flagged, 150 weight changes", ""),
        (f"{int(held.layers12_correct)} of 12", f"new risky phrasings caught ({int(dev_.layers12_correct)}/12 on tuned ones)", ""),
        (f"{len(V.FAILURE_LOG)}", "mistakes and blind spots logged", ""),
    ], hero_first=False), unsafe_allow_html=True)

    t1, t2 = st.columns(2, gap="large")
    with t1:
        st.markdown("**Try to break the guardrail**")
        probe = st.text_input("Type a sentence a CSM might write",
                              "Any money you lost from failed payments will be credited back.")
        ref = ref_merchant()
        found = validate(probe, ref)
        if found:
            st.error("Blocked: " + "; ".join(found), icon=":material/block:")
        else:
            st.warning("Not caught by the rules. That's why a person approves every message.", icon=":material/person:")
        if ai_key() and probe.strip():
            rv = ai_review(probe, json.dumps(facts(ref), default=str))
            if rv["available"]:
                (st.error if rv["block"] else st.success)("AI reviewer: " + ("blocks it: " + "; ".join(rv["reasons"]) if rv["block"] else "no issue"))
    with t2:
        st.markdown("**Guardrail score**")
        st.dataframe(gr_sum.rename(columns={"sentences": "Sentences", "layer1_correct": "Keyword rules",
                                            "layers12_correct": "+ tone rules"}), hide_index=True, width="stretch")
        st.caption("Tone rules were tuned on the first set only; the held-out row is the honest number. "
                   "These message tests don't depend on the data pack.")
    with st.expander("Switch each design choice off: what breaks?"):
        st.dataframe(abl, hide_index=True, width="stretch",
                     column_config={"What actually happened": st.column_config.TextColumn(width=330),
                                    "Verdict": st.column_config.TextColumn(width=360)})
    with st.expander(f"What went wrong while building this ({len(V.FAILURE_LOG)})"):
        for kind, what, fix in V.FAILURE_LOG:
            st.markdown(f"**{kind}.** {what}  \n*Fix:* {fix}")
    with st.expander("How stable is each pick?"):
        st.dataframe(pd.DataFrame({"Merchant": call.business_name.values,
                                   "In the plan, share of runs": sv.reindex(call.merchant_id)["pct_runs_top15"].values}),
                     hide_index=True, width="stretch",
                     column_config={"In the plan, share of runs": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent")})
    with st.expander("All 36 guardrail test sentences"):
        st.dataframe(gr_rows, hide_index=True, width="stretch")

# ================================================================ ALL MERCHANTS
else:
    title("All merchants")
    f1, f2, f3 = st.columns([1, 1, 2])
    lab = f1.segmented_control("Risk", ["High", "Low"], default=["High", "Low"], selection_mode="multi", key="f_risk")
    seg_ = f2.segmented_control("Size", sorted(p.segment.unique()), default=sorted(p.segment.unique()),
                                selection_mode="multi", key="f_seg")
    q = f3.text_input("Search", placeholder="Merchant name or ID", key="f_q")
    v = p[p.risk_label.isin(lab or []) & p.segment.isin(seg_ or [])]
    if q:
        v = v[v.business_name.str.contains(q, case=False) | v.merchant_id.str.contains(q, case=False)]
    st.dataframe(pd.DataFrame({
        "#": v["rank"], "Merchant": v.business_name, "ID": v.merchant_id, "Size": v.segment,
        "Risk": v.risk_score, "Reason": v.reason_plain, "₹ L / yr": (v.annual_value_inr / 1e5).round(1),
        "Next step": v.action, "Detail": [plain_reason(x) if x.eligible else plain_cleared(x) for x in v.itertuples()]}),
        hide_index=True, height=520, width="stretch",
        column_config={"Risk": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d", width=110),
                       "Detail": st.column_config.TextColumn(width=380)})
    st.download_button("Download all results (CSV)", p.drop(columns=["draft"]).to_csv(index=False), "agent_results.csv",
                       icon=":material/download:")
