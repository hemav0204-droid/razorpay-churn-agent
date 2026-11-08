"""
Measure the message guardrails on the red-team sets.

    python evaluate_guardrails.py          # layers 1+2 (rules), runs anywhere
    python evaluate_guardrails.py --llm    # + layer 3 AI reviewer (needs ANTHROPIC_API_KEY)

Report the HELD_OUT number: it is the honest one.
"""
import argparse, json
import engine as E, outreach as O, redteam as R

ap = argparse.ArgumentParser(); ap.add_argument("--llm", action="store_true"); a = ap.parse_args()
p, _ = E.run("data_pack.xlsx")
r = next(p[p.merchant_id == "C2004"].itertuples())
if a.llm:
    from llm_layer import review_message
facts = json.dumps(O.facts(r), default=str)


def blocked(t):
    rules = bool(O.validate(t, r))
    ai = review_message(t, facts) if a.llm else None
    if ai and not ai["available"]:
        raise SystemExit(f"AI reviewer not reachable: {ai['reasons'][0]}. Set ANTHROPIC_API_KEY and retry.")
    return rules, (ai["block"] if ai else None)


for name, rows, want in [("DEV", R.DEV, True), ("HELD_OUT", R.HELD_OUT, True),
                         ("BENIGN", [("ok", t) for t in R.BENIGN], False)]:
    res = [(c, t, *blocked(t)) for c, t in rows]
    rules_ok = sum(x[2] == want for x in res)
    line = f"{name:9s} rules: {rules_ok}/{len(res)} correct"
    if a.llm:
        both_ok = sum(((x[2] or x[3]) == want) for x in res)
        line += f"   rules + AI reviewer: {both_ok}/{len(res)} correct"
    print(line)
    for c, t, rb, ab in res:
        final = rb or bool(ab)
        if final != want:
            print(f"   {'MISSED' if want else 'FALSE ALARM'}: {t}")
