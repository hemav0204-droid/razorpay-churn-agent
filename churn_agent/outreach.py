"""
Outreach drafting + guardrails.

Drafts are built ONLY from the merchant's own data and the playbook text.
Every draft (template or LLM-written) passes validate() before a CSM sees it:
  1. Every number in the draft must exist in that merchant's data.
  2. No promises: refunds, waivers, discounts, guaranteed outcomes, invented dates.
  3. No internal leakage: churn, risk scores, AM-note quotes, competitor talk.
  4. Length limit, and only approved placeholders.
A draft that fails is NOT sent; it is marked for the CSM to rewrite.
"""
from __future__ import annotations
import re

MAX_WORDS = 140
ALLOWED_PLACEHOLDERS = {"[CSM name]"}

BANNED_PROMISES = [
    r"\bwaive", r"\bwaiver", r"\brefund", r"\bdiscount", r"\bfree\b", r"\bguarantee",
    r"\bwe will (fix|resolve|reduce|lower|match)", r"\bpromise", r"\bcashback",
    r"\b(by|before|on) (monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
    r"\bwithin \d+ (hours|days)", r"\blower (rate|mdr|price)", r"\bbetter rate",
]
INTERNAL_TERMS = [
    r"\bchurn", r"risk score", r"\bdecoy", r"account manager note", r"\bcompetitor",
    r"comparing quotes", r"exploring options", r"\bat[- ]risk\b", r"\bwatchlist",
]


# Layer 2: implied commitments and tone. Layer 1 catches explicit words ("waive");
# these catch the softer phrasing a CSM might type ("rest assured", "end of week").
# Designed on redteam.DEV only; redteam.HELD_OUT measures how well it generalises.
TONE_RULES = [
    ("implied promise", r"\b(rest assured|i'?m confident|i am confident|definitely|certainly|for sure|without fail)\b"),
    ("implied promise", r"\b(we|i)('ll| will| can) (sort|fix|resolve|match|beat|lower|reduce|improve|close)\b"),
    ("implied promise", r"\bwill be (fixed|resolved|sorted|reduced|lowered|closed|improved)\b"),
    ("invented timing", r"\b(by|before) (the )?(end of|eod|eow|tomorrow|today|monday|next week)"),
    ("invented timing", r"\b(very soon|asap|right away|immediately|in no time|revert by)\b"),
    ("pricing hint", r"\b(special|better|reduced|lower|discounted|custom|exclusive) (rate|price|pricing|deal|offer|mdr)\b"),
    ("pressure", r"\b(don'?t|do not) (move|leave|switch|go)\b|\b(hate|sad) to lose\b|\banother (gateway|provider)\b|\bstay with us\b"),
    ("surveillance tone", r"\bwe (noticed|saw|can see|tracked) (that )?you (only|haven'?t|rarely|barely)\b|\byou (only|barely|rarely) (logged|log in|used)\b"),
]


def _fmt(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def facts(r) -> dict:
    """The only facts a draft may use."""
    return {
        "name": r.business_name,
        "tpv_base": _fmt(round(r.tpv_baseline_m1_m3, 1)),
        "tpv_m6": _fmt(round(r.tpv_m6_inr_lakh, 1)),
        "sr_before": _fmt(round(r.success_rate_m1_m3_pct, 1)),
        "sr_after": _fmt(round(r.success_rate_m4_m6_pct, 1)),
        "unresolved": int(r.unresolved_tickets),
        "renewal_days": int(r.days_to_contract_renewal),
        "products": int(r.products_used),
        "ufail": "upi" in str(r.account_manager_note).lower(),
    }


def allowed_numbers(r) -> set[str]:
    nums = set()
    vals = r._asdict().values() if hasattr(r, "_asdict") else r.to_dict().values()
    for v in vals:
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
            nums |= {_fmt(round(float(v), 1)), str(int(round(v))) if float(v).is_integer() else _fmt(round(float(v), 1))}
    nums |= {_fmt(round(r.tpv_baseline_m1_m3, 1)), "30"}   # "30-minute call" is a fixed phrase
    return nums


SECONDARY_LINE = {
    "PB-1": "Separately, I'd also like our Payments Operations team to look at your recent payment success rates.",
    "PB-2": "I've also noticed you have {unresolved} support tickets still open, and I'll make sure those get proper ownership too.",
    "PB-3": "Since your renewal is coming up in {renewal_days} days, we can also walk through your current plan on the same call.",
    "PB-4": "I'd also like to confirm we have the right contact person on your team.",
}


EMAIL_ASK = {
    # Over-cap merchants get a reviewed email instead of a call, so the ask is a reply, not a meeting.
    "PB-1": "If you reply with the payment methods or banks where you see the most failures, I'll pass them "
            "to our Payments Operations team for review.",
    "PB-2": "Please reply with the ticket that matters most to you, and I'll start there.",
    "PB-3": "Please reply with a time that suits you before the renewal date.",
    "PB-4": "Who would be the best person on your team to send this to?",
}


def contact_plan(r, channel: str = "call") -> dict:
    """How to reach the merchant and who joins, by size and playbook.
    Large merchants get senior people; small ones get the CSM alone; over-cap ones get an email."""
    seg, pb = str(r.segment), r.playbook
    specialist = {"PB-1": "Payments Ops", "PB-2": "Support lead", "PB-3": "Account Manager",
                  "PB-4": "Account Manager"}.get(pb, "")
    if channel == "email":
        how = "Reviewed email from the CSM (no call this month)"
        who = "CSM"
        if pb == "PB-3":
            who = "CSM; Account Manager runs the renewal review"
        nxt = "First call slot next month if no reply"
        if int(r.days_to_contract_renewal) <= 30:
            nxt = f"Renews in {int(r.days_to_contract_renewal)} days: Account Manager should follow up before then"
        return {"how": how, "who": who, "next": nxt}
    if seg == "Enterprise":
        how, who = "Phone call, then a written summary", f"CSM + {specialist} + a senior leader as sponsor"
    elif seg == "Mid":
        how, who = "Phone call, then a written summary", f"CSM + {specialist}"
    else:
        how, who = "Phone call or email, whichever the merchant prefers", "CSM" + (
            " (Account Manager for pricing)" if pb == "PB-3" else "")
    return {"how": how, "who": who, "next": "Re-check the merchant's numbers next month"}


def draft(r, channel: str = "call") -> str:
    f = facts(r)
    n = f["name"]
    pb = r.playbook
    if pb == "PB-1":
        body = (f"Your payment success rate averaged {f['sr_after']}% over the last three months, compared with "
                f"{f['sr_before']}% in the three months before. "
                + ("You mentioned UPI drop-offs on our last call, so we'd start there. " if f["ufail"] else "")
                + "I'd like to set up a joint call with our Payments Operations team to review failures by payment "
                  "method and bank, and agree a fix plan with you.")
        ask = "Would a 30-minute call this week work for you?"
    elif pb == "PB-2":
        body = (f"I can see you have {f['unresolved']} support tickets that are still open with us, and I'm sorry "
                "that they've taken this long. I'm taking ownership of all of them and will be your single point "
                "of contact until each one is closed. I'd also like a senior colleague to call you to go through them.")
        ask = "When is a good time for that call?"
    elif pb == "PB-3":
        body = (f"Your contract renewal is coming up in {f['renewal_days']} days, and I want to make sure your plan "
                "still fits how your business runs today. Our Account Manager can walk you through your current "
                "rate card, volume tiers and renewal terms before the renewal date.")
        ask = "Could we find 30 minutes for a short review?"
    else:  # PB-4 or unexplained decline
        body = (f"Your monthly payment volume has moved from about Rs {f['tpv_base']} lakh to Rs {f['tpv_m6']} lakh "
                "recently, and we haven't connected in a while. I'd like to make sure we're speaking with the right "
                "person on your team, and offer a short session on reports and products you may not be using yet.")
        ask = "Who would be the best person to speak with?"
    if channel == "email":
        ask = EMAIL_ASK.get(pb, EMAIL_ASK["PB-4"])
        if pb == "PB-2":   # no senior call promised when there's no call slot
            body = body.replace(" I'd also like a senior colleague to call you to go through them.", "")
        body = body.replace("I'd like to set up a joint call with our Payments Operations team to review",
                            "I'd like our Payments Operations team to review")
    extra = ""
    if r.secondary_playbook in SECONDARY_LINE:
        extra = " " + SECONDARY_LINE[r.secondary_playbook].format(**f)
    return f"Hi {n} team,\n\n{body}{extra}\n\n{ask}\n\nRegards,\n[CSM name]"


def validate(text: str, r) -> list[str]:
    """Returns a list of guardrail failures (empty list = pass)."""
    issues = []
    low = text.lower()
    for pat in BANNED_PROMISES:
        if re.search(pat, low):
            issues.append(f"promise/commitment: '{re.search(pat, low).group(0)}'")
    for pat in INTERNAL_TERMS:
        if re.search(pat, low):
            issues.append(f"internal term leaked: '{re.search(pat, low).group(0)}'")
    for label, pat in TONE_RULES:
        m = re.search(pat, low)
        if m:
            issues.append(f"{label}: '{m.group(0)}'")
    ok = allowed_numbers(r)
    for num in re.findall(r"\d+(?:\.\d+)?", text):
        if num not in ok:
            issues.append(f"number not in merchant data: {num}")
    for ph in re.findall(r"\[[^\]]+\]", text):
        if ph not in ALLOWED_PLACEHOLDERS:
            issues.append(f"unknown placeholder: {ph}")
    if len(text.split()) > MAX_WORDS:
        issues.append(f"too long: {len(text.split())} words")
    return issues


def csm_checklist(r) -> str:
    """What the human must verify before sending."""
    items = ["Confirm the contact person and channel"]
    if r.playbook == "PB-1":
        items.append("Pull success rate by method/bank from Payments Ops before the call")
    if r.playbook == "PB-2" or r.secondary_playbook == "PB-2":
        items.append("Check each open ticket's latest status; do not quote a closure date until the owning team confirms")
    if r.playbook == "PB-3" or r.secondary_playbook == "PB-3":
        items.append("Any pricing change needs AM + finance approval; the email offers a review only")
    if r.playbook == "PB-4":
        items.append("Ask whether the decline is seasonal or a business change before pitching products")
    if r.dq_old_open_ticket:
        items.append("Data check: open ticket older than 90 days")
    if r.seasonal_industry:
        items.append("Seasonal industry: confirm this is not a normal yearly dip")
    return "; ".join(items)
