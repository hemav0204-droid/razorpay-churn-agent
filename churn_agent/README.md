# Merchant Retention Decision Agent
Razorpay Campus AI Build-a-thon, Problem 2: churn early-warning and proactive outreach.

For each of 100 merchants the agent gives a risk score and label, the likely reason in plain
language, a playbook (PB-1 to PB-6), and, for the 15 merchants the CSM team should call
first, a fact-checked outreach draft for a human to approve.

## Run it
```bash
pip install -r requirements.txt
python run_agent.py                 # rules + templates, fully reproducible
python build_report.py              # writes output/Churn_Agent_Output.xlsx
python -m streamlit run app.py      # CSM workspace (Razorpay-styled)
ANTHROPIC_API_KEY=... python run_agent.py --llm   # optional LLM layer
```
For a shareable link: push this folder to GitHub and deploy `app.py` on Streamlit Community Cloud.

## Files
| File | Role |
|---|---|
| `engine.py` | Features, risk points, decoy guards, driver, playbook, prioritisation |
| `outreach.py` | Fact-grounded drafts, guardrail validator, CSM checklist |
| `llm_layer.py` | Optional: LLM reads AM notes and personalises drafts; always re-validated |
| `run_agent.py` | Runs everything, tests, baselines, sensitivity |
| `build_report.py` | Formatted Excel output with live cost-benefit formulas |
| `evaluation.py` | Ablation study, capacity curve, guardrail scoring, failure log |
| `redteam.py` | Guardrail test sentences: development, held-out, normal |
| `evaluate_guardrails.py` | Measures guardrails; `--llm` adds the AI reviewer (needs API key) |
| `app.py` | CSM tool. Opens on **Home** (what needs doing, with four choices: My actions, Big picture, Look up a merchant, Upload new data). Top bar: Home, My actions, Big picture (Is 15 enough? / Why they leave / False alarms), All merchants, Testing, plus Upload data and Help |
| `.streamlit/config.toml` | Razorpay colour theme |

## How outreach differs by merchant size
| Size | Channel | Who is involved |
|---|---|---|
| Enterprise | Phone call, then written summary | CSM + specialist for the playbook (Payments Ops, Support lead or Account Manager) + a senior leader as sponsor |
| Mid | Phone call, then written summary | CSM + specialist for the playbook |
| Small | Call or email, as the merchant prefers | CSM (Account Manager for pricing) |
| Over the 15-call limit | Reviewed email asking for a reply | CSM; Account Manager follows up first if renewal is within 30 days |

My actions has two lanes, Calls (15) and Emails (9). Every message is guardrail-checked and needs CSM approval.
"Download hand-off sheet" exports all 24 with channel, who is involved, status, the CSM's note and the approved text.

## Who decides what
| Rules (deterministic) | AI (LLM, optional) | Human (CSM) |
|---|---|---|
| All maths, scores, ranking, top-15, playbook choice | Reading free-text notes (cross-checked against rules) | Approve / edit / reject every message |
| Decoy detection | Warmer wording of drafts | Any pricing or commercial change |
| Guardrail checks on every draft | | Ambiguous cases flagged by the checklist |

## Results on the data pack
- 24 High risk, 76 Low; all 33 decoys (8 seasonal, 6 busy-but-healthy, 19 low-volume) cleared.
- 15 calls cover Rs 84.1 lakh/yr of net revenue (94% of the at-risk total). Ranking by risk alone would cover Rs 39.9 lakh.
- Outreach cost Rs 22,500. Break-even save rate 0.4%: saving one merchant pays for the month.
- 15/15 drafts pass guardrails. 50/52 tests pass; the 2 failures are deliberate blind-spot tests.
- Under +/-30% random weight changes (500 runs) no decoy ever becomes High; 13 of 15 picks hold in 90%+ of runs.

## Using a different data pack
In the app: **Upload data** (top bar or the Home card). The page lists what the file needs and offers the original as a template; after loading, the app returns to Home with the new month's summary. The file must have a P2_Merchants sheet with the same columns;
P2_Playbooks and P2_Assumptions are read if present (falling back to the original's, with a visible note).
Assumptions (net revenue %, cost per call, call cap, months of value, seasonal industries) are read from the
file's text. A banner shows which pack and assumptions are in use; "Back to original" restores the default.
Broken files are rejected with a plain explanation and the previous pack stays loaded.
The 52 hand-written rule tests apply to the original pack only; the Excel report is built for the original pack.
Command line: `python run_agent.py --data other_pack.xlsx`.

## Stand-out evidence
- Guardrail: keyword + tone rules catch 12/12 risky phrasings they were tuned on but only 4/12 new ones, with 0/12 false alarms on normal sentences. So a human approves every message, and an AI reviewer (layer 3) can add blocks but never approvals.
- Ablation: switching off the seasonal-shape guard changes nothing at this threshold; what keeps decoys out is that churners show 2+ warning signs together. Ignoring account-manager notes loses 6 at-risk merchants, including the most valuable one (C2004).
- Capacity: 5 calls cover 68% of at-risk revenue, 15 cover 94%. We keep the 15-call limit; the other 9 at-risk merchants (Rs 5.65 lakh/yr together) get a CSM-reviewed email now and the first call slots next month, so nobody at risk goes uncontacted.
- False alarms vs saves: a wrong call costs Rs 1,500; all 15 wrong would cost Rs 22,500. Saving the smallest merchant on the list (Rs 1.14 lakh/yr) pays for the month 5x over.

## Honest limitations
- No churn labels: the score ranks merchants; it is not a probability. Weights and thresholds were set by reading this data.
- Test "expected" answers are my reading of the data, not the hidden labels.
- Blind spots: an early churner with a small drop and no note (E7); service pain before volume falls (E8).
- Save rate (25%) is my assumption; the Excel lets you change it.
- The LLM layer was written but not run here (no API key in the build environment); the template path is what produced the numbers above.
