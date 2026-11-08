"""
Optional LLM layer (run with --llm and ANTHROPIC_API_KEY set).

What the LLM is allowed to do:
  1. interpret_note(): read the free-text account-manager note and pick ONE category
     from our fixed taxonomy. If it disagrees with the rule-based category, the
     merchant is flagged for human review; the rules are NOT silently overridden.
  2. personalise(): rewrite the template draft in a warmer voice using ONLY the
     facts we pass in. The result must pass outreach.validate(); one retry with the
     validator's feedback, otherwise we fall back to the safe template.

What the LLM is NOT allowed to do: compute scores, rank merchants, choose who gets
contacted, or send anything. Those stay with rules and the CSM.
"""
from __future__ import annotations
import json
import os
import requests

from engine import NOTE_RULES
from outreach import facts, validate

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
CATEGORIES = [c for c, *_ in NOTE_RULES] + ["no_note", "unclassified"]


def _call(system: str, user: str, max_tokens: int = 600) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    resp = requests.post(
        API_URL,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": max_tokens, "system": system,
              "messages": [{"role": "user", "content": user}]},
        timeout=60,
    )
    resp.raise_for_status()
    return "".join(b.get("text", "") for b in resp.json()["content"])


NOTE_SYSTEM = f"""You classify a short note written by a payments company's account manager about a merchant.
Choose exactly one category from: {CATEGORIES}.
Definitions: competitive = merchant mentions or evaluates other providers; pricing_renewal = asks about
pricing/rate card/renewal terms; performance_issue = complains about payment failures or success rates;
service_issue = slow or unresolved support; disengagement = contact unclear, not responding, not using
the product; seasonal_context = says the dip is seasonal; growth_context = growing or wants more products;
resolved_neutral = past issue fixed or no concern.
Do not infer anything that is not written in the note.
Reply with JSON only: {{"category": "...", "evidence": "<exact words from the note>"}}"""


def interpret_note(note: str) -> dict:
    if not isinstance(note, str) or not note.strip():
        return {"category": "no_note", "evidence": ""}
    raw = _call(NOTE_SYSTEM, f"Note: {note}", 200)
    try:
        out = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
    except json.JSONDecodeError:
        return {"category": "unclassified", "evidence": "LLM returned non-JSON"}
    if out.get("category") not in CATEGORIES:
        out["category"] = "unclassified"
    return out


DRAFT_SYSTEM = """You help a Customer Success Manager at a payments company write a short outreach email.
Rules you must follow:
- Use ONLY the facts provided. Do not add any other number, date or deadline.
- Never offer refunds, fee waivers, discounts, better rates, or guaranteed outcomes.
- Never mention churn, risk scores, competitors, or internal notes.
- Keep it under 120 words, warm, plain English, and end with one clear question.
- Sign off with exactly: [CSM name]
Return only the email text."""


def personalise(r, template: str) -> tuple[str, str]:
    """Returns (draft, source) where source is 'llm', 'llm_retry' or 'template_fallback'."""
    f = facts(r)
    user = (f"Merchant facts: {json.dumps(f)}\nPlaybook: {r.playbook}\n"
            f"Template draft to improve:\n{template}")
    text = _call(DRAFT_SYSTEM, user)
    issues = validate(text, r)
    if not issues:
        return text, "llm"
    text = _call(DRAFT_SYSTEM, user + f"\n\nYour previous draft broke these rules: {issues}. Fix them.")
    if not validate(text, r):
        return text, "llm_retry"
    return template, "template_fallback"


# ---------------------------------------------------------------- Layer 3: AI reviewer
REVIEW_SYSTEM = """You review an outreach message a Customer Success Manager at a payments company
wants to send to a merchant. Block it if it does ANY of the following, even if phrased indirectly:
- promises or implies an outcome (a fix, closure, improvement, better price, retention)
- commits to a time or deadline (e.g. "within a day", "tomorrow", "shortly")
- offers or implies money back, credits, waived or skipped charges, discounts, or better rates
- pressures the merchant to stay or mentions other providers
- reveals internal information (risk scores, models, internal notes) or sounds like surveillance
- states a number that is not in the facts provided
Asking for a call, apologising, and describing the merchant's own numbers are fine.
Reply with JSON only: {"block": true|false, "reasons": ["short reason", ...]}"""


def review_message(text: str, facts_json: str) -> dict:
    """Layer 3. Can only ADD a block; it can never approve a message the rules blocked.
    Returns {"block": bool, "reasons": [...], "available": bool}."""
    try:
        raw = _call(REVIEW_SYSTEM, f"Facts: {facts_json}\n\nMessage:\n{text}", 300)
        out = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        return {"block": bool(out.get("block")), "reasons": out.get("reasons", []), "available": True}
    except Exception as e:  # no key, network, bad JSON: say so, never silently pass
        return {"block": False, "reasons": [f"AI review unavailable: {type(e).__name__}"], "available": False}
