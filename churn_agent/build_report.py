"""Builds Churn_Agent_Output.xlsx from the agent results (python build_report.py)."""
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import CellIsRule
import pandas as pd
import sys

sys.argv = ["run_agent.py"]
from run_agent import main
import evaluation as V

p, tests, sens, base, playbooks = main()
OUT = "output/Churn_Agent_Output.xlsx"

F = "Arial"
H_FILL = PatternFill("solid", fgColor="1F3A5F")
H_FONT = Font(name=F, bold=True, color="FFFFFF")
BODY = Font(name=F, size=10)
BLUE = Font(name=F, size=10, color="0000FF")
BOLD = Font(name=F, size=10, bold=True)
TITLE = Font(name=F, size=14, bold=True, color="1F3A5F")
YELLOW = PatternFill("solid", fgColor="FFFF00")
THIN = Border(bottom=Side(style="thin", color="D0D0D0"))
WRAP = Alignment(wrap_text=True, vertical="top")
RED_F = PatternFill("solid", fgColor="F8D7DA"); GRN_F = PatternFill("solid", fgColor="D4EDDA")

wb = Workbook()


def table(ws, df, start_row=1, widths=None, wrap_cols=()):
    for j, c in enumerate(df.columns, 1):
        cell = ws.cell(start_row, j, c); cell.font = H_FONT; cell.fill = H_FILL; cell.alignment = WRAP
    for i, row in enumerate(df.itertuples(index=False), start_row + 1):
        for j, v in enumerate(row, 1):
            if isinstance(v, float) and v != v:
                v = None
            cell = ws.cell(i, j, v); cell.font = BODY; cell.border = THIN
            if df.columns[j - 1] in wrap_cols:
                cell.alignment = WRAP
    for j, c in enumerate(df.columns, 1):
        ws.column_dimensions[get_column_letter(j)].width = (widths or {}).get(c, max(10, min(28, len(str(c)) + 2)))
    ws.freeze_panes = ws.cell(start_row + 1, 3)


# ------------------------------------------------------------ All_Merchants
allm = p.copy()
allm["contacted"] = allm["outreach_this_month"].map({True: "Yes", False: "No"})
cols = ["rank", "merchant_id", "business_name", "segment", "industry", "risk_score", "risk_label",
        "classification", "primary_driver", "secondary_driver", "playbook", "secondary_playbook", "reason",
        "action", "contacted", "tpv_baseline_m1_m3", "tpv_m6_inr_lakh", "tpv_change_pct", "down_months",
        "seasonal_shape", "sr_change_pp", "unresolved_tickets", "last_csat_1_to_5", "logins_last_30d",
        "products_used", "days_to_contract_renewal", "note_category", "pts_volume", "pts_performance",
        "pts_service", "pts_engagement", "pts_note", "pts_renewal", "urgency", "dq_old_open_ticket"]
a = allm[cols].copy()
for c in ["tpv_baseline_m1_m3", "tpv_change_pct", "sr_change_pp", "pts_volume", "pts_performance",
          "pts_service", "pts_engagement", "pts_note", "pts_renewal"]:
    a[c] = a[c].round(1)
ws = wb.active; ws.title = "All_Merchants"
table(ws, a, widths={"reason": 70, "action": 34, "business_name": 20, "industry": 20, "classification": 22,
                     "primary_driver": 20}, wrap_cols=("reason",))
L = {c: get_column_letter(i) for i, c in enumerate(a.columns, 1)}
n = len(a); last = n + 1
# live formula columns
vcol = get_column_letter(len(a.columns) + 1); pcol = get_column_letter(len(a.columns) + 2)
for col, name in ((vcol, "annual_net_revenue_inr"), (pcol, "risk_proxy")):
    c = ws[f"{col}1"]; c.value = name; c.font = H_FONT; c.fill = H_FILL; ws.column_dimensions[col].width = 16
for i in range(2, last + 1):
    ws[f"{vcol}{i}"] = f"={L['tpv_m6_inr_lakh']}{i}*100000*Summary!$C$5*Summary!$C$6"
    ws[f"{vcol}{i}"].number_format = "#,##0"; ws[f"{vcol}{i}"].font = BODY
    ws[f"{pcol}{i}"] = f"={L['risk_score']}{i}/100"; ws[f"{pcol}{i}"].number_format = "0.00"; ws[f"{pcol}{i}"].font = BODY
rng = f"{L['risk_label']}2:{L['risk_label']}{last}"
ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"High"'], fill=RED_F))
ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Low"'], fill=GRN_F))
ws.auto_filter.ref = f"A1:{pcol}{last}"

R = lambda c: f"All_Merchants!${L[c]}$2:${L[c]}${last}"
VAL = f"All_Merchants!${vcol}$2:${vcol}${last}"; PRX = f"All_Merchants!${pcol}$2:${pcol}${last}"

# ------------------------------------------------------------ Summary
s = wb.create_sheet("Summary", 0)
s.column_dimensions["A"].width = 2; s.column_dimensions["B"].width = 52; s.column_dimensions["C"].width = 20
for col in "DEFG":
    s.column_dimensions[col].width = 18
s["B1"] = "Merchant Retention Decision Agent: results"; s["B1"].font = TITLE
s["B2"] = "Blue = input from P2_Assumptions. Yellow = our own assumption, edit to test scenarios. Black = formula."
s["B2"].font = Font(name=F, size=9, italic=True)

s["B4"] = "Assumptions"; s["B4"].font = BOLD
assum = [("Net revenue as share of TPV", 0.01, "0.0%", "P2_Assumptions"),
         ("Months of value for a saved merchant", 12, "0", "P2_Assumptions"),
         ("Cost of one outreach (false alarm), Rs", 1500, "#,##0", "P2_Assumptions"),
         ("Outreach cap this month", 15, "0", "P2_Assumptions"),
         ("Save rate: share of contacted churners retained", 0.25, "0%", "OUR ASSUMPTION: not in data pack; test 10%-40%")]
for k, (lab, v, fmt, src) in enumerate(assum, 5):
    s[f"B{k}"] = lab; s[f"C{k}"] = v; s[f"C{k}"].number_format = fmt; s[f"D{k}"] = src
    s[f"C{k}"].font = BLUE; s[f"B{k}"].font = BODY; s[f"D{k}"].font = Font(name=F, size=9, italic=True)
s["C9"].fill = YELLOW

s["B11"] = "Portfolio"; s["B11"].font = BOLD
kpis = [
    ("Merchants analysed", f"=COUNTA({R('merchant_id')})", "0"),
    ("High risk", f'=COUNTIF({R("risk_label")},"High")', "0"),
    ("Decoys correctly not flagged (seasonal, busy-healthy, low-volume)", f'=COUNTIF({R("classification")},"Decoy*")', "0"),
    ("Contacted this month", f'=COUNTIF({R("contacted")},"Yes")', "0"),
    ("High risk but over the cap", "=C13-C15", "0"),
    ("Annual net revenue of all High-risk merchants, Rs", f'=SUMIFS({VAL},{R("risk_label")},"High")', "#,##0"),
    ("Annual net revenue of the 15 contacted, Rs", f'=SUMIFS({VAL},{R("contacted")},"Yes")', "#,##0"),
    ("Share of at-risk revenue covered by 15 calls", "=C18/C17", "0%"),
]
for k, (lab, f_, fmt) in enumerate(kpis, 12):
    s[f"B{k}"] = lab; s[f"C{k}"] = f_; s[f"C{k}"].number_format = fmt; s[f"B{k}"].font = BODY; s[f"C{k}"].font = BODY

s["B21"] = "Cost of false alarms vs value saved"; s["B21"].font = BOLD
cb = [
    ("Outreach cost (cap x cost per outreach), Rs", "=C8*C7", "#,##0"),
    ("Risk-weighted revenue of the 15 (sum of risk proxy x value), Rs",
     f'=SUMPRODUCT(({R("contacted")}="Yes")*{PRX}*{VAL})', "#,##0"),
    ("Expected revenue saved (x save rate), Rs", "=C23*C9", "#,##0"),
    ("Net expected value, Rs", "=C24-C22", "#,##0"),
    ("Return on CSM time (saved / cost)", "=C24/C22", '0.0"x"'),
    ("Break-even save rate (save rate needed to cover cost)", "=C22/C23", "0.0%"),
    ("Worst case: all 15 are false alarms, Rs lost", "=-C22", "#,##0"),
    ("Smallest single merchant contacted, annual value, Rs", f'=MINIFS({VAL},{R("contacted")},"Yes")', "#,##0"),
]
for k, (lab, f_, fmt) in enumerate(cb, 22):
    s[f"B{k}"] = lab; s[f"C{k}"] = f_ if "MINIFS" not in f_ else f_.replace("MINIFS", "_xlfn.MINIFS")
    s[f"C{k}"].number_format = fmt; s[f"B{k}"].font = BODY; s[f"C{k}"].font = BODY
s["B30"] = ("Reading: saving even one contacted merchant covers the whole month's outreach cost, "
            "so the real risk is not false alarms but missing true churners beyond the cap.")
s["B30"].font = Font(name=F, size=9, italic=True); s["B30"].alignment = WRAP; s.merge_cells("B30:G30")
s.row_dimensions[30].height = 28

s["B32"] = "Churn drivers (High-risk merchants)"; s["B32"].font = BOLD
for j, h in enumerate(["Driver", "High risk", "Contacted", "Annual value at risk, Rs", "Share of value", "Playbook"]):
    c = s.cell(33, 2 + j, h); c.font = H_FONT; c.fill = H_FILL
drivers = [("Performance", "PB-1"), ("Service", "PB-2"), ("Pricing / competitive", "PB-3"), ("Disengagement", "PB-4")]
for k, (d, pb) in enumerate(drivers, 34):
    s[f"B{k}"] = d
    s[f"C{k}"] = f'=COUNTIFS({R("primary_driver")},B{k},{R("risk_label")},"High")'
    s[f"D{k}"] = f'=COUNTIFS({R("primary_driver")},B{k},{R("contacted")},"Yes")'
    s[f"E{k}"] = f'=SUMIFS({VAL},{R("primary_driver")},B{k},{R("risk_label")},"High")'; s[f"E{k}"].number_format = "#,##0"
    s[f"F{k}"] = f"=E{k}/SUM($E$34:$E$37)"; s[f"F{k}"].number_format = "0%"
    s[f"G{k}"] = pb
    for col in "BCDEFG":
        s[f"{col}{k}"].font = BODY

hi = p[p.risk_label == "High"]
oc_ = p[p.eligible & ~p.outreach_this_month]
g = hi.groupby("primary_driver").annual_value_inr.sum().sort_values(ascending=False)
s["B39"] = "Engine insights"; s["B39"].font = BOLD
insights = [
    f"Biggest driver by value: {g.index[0]} (Rs {g.iloc[0]/1e5:.1f} lakh/yr). Most of it is the Enterprise account C2004 "
    "comparing quotes 39 days before renewal; a renewal-led commercial review process would protect the most revenue.",
    f"Most common driver by count: Performance ({(hi.primary_driver=='Performance').sum()} merchants), all with a "
    f"{abs(hi[hi.primary_driver=='Performance'].sr_change_pp).min():.1f}-{abs(hi[hi.primary_driver=='Performance'].sr_change_pp).max():.1f} pt "
    "success-rate fall. Product/process fix: an automatic alert to Payments Ops when a merchant's success rate drops "
    ">5 pts quarter-on-quarter, before the merchant has to complain.",
    "Service: 6 merchants each have 4-5 unresolved tickets and CSAT 1-2. A ticket-ageing SLA that auto-escalates any "
    "merchant with 3+ open tickets to the CSM would catch these weeks earlier.",
    "Disengagement: 5 merchants fell every month with 0-3 logins; 3 of them changed owner or manager. A contact-change "
    "trigger (new login identity, bounced emails) should prompt re-onboarding.",
    f"{len(oc_)} High-risk merchants ({', '.join(sorted(oc_.segment.unique()))}) sit beyond the 15-call cap, worth "
    f"Rs {oc_.annual_value_inr.sum()/1e5:.2f} lakh/yr ({oc_.annual_value_inr.sum()/hi.annual_value_inr.sum():.0%} of at-risk revenue). "
    "They get a CSM-reviewed email now (drafts on the Over_Cap_Emails sheet) and the first call slots next month.",
]
for k, t in enumerate(insights, 40):
    s[f"B{k}"] = f"- {t}"; s[f"B{k}"].font = BODY; s[f"B{k}"].alignment = WRAP
    s.merge_cells(f"B{k}:G{k}"); s.row_dimensions[k].height = 42

s["B46"] = "Comparison with naive approaches"; s["B46"].font = BOLD
b = base.copy(); b.columns = ["Approach", "Merchants", "Decoys included", "At-risk included",
                              "Annual value covered, Rs", "Note"]
for j, h in enumerate(b.columns):
    c = s.cell(47, 2 + j, h); c.font = H_FONT; c.fill = H_FILL; c.alignment = WRAP
for i, row in enumerate(b.itertuples(index=False), 48):
    for j, v in enumerate(row):
        c = s.cell(i, 2 + j, None if (isinstance(v, float) and v != v) else v); c.font = BODY; c.alignment = WRAP
        if j == 4:
            c.number_format = "#,##0"
s.column_dimensions["G"].width = 44
s.cell(53, 2, "Decoy and at-risk counts use my own reading of the data, not the hidden labels.").font = Font(name=F, size=9, italic=True)

# ------------------------------------------------------------ Top15_Outreach
t = p[p.outreach_this_month].copy()
t["annual_net_revenue_inr"] = (t.annual_value_inr).round(0)
t15 = t[["rank", "merchant_id", "business_name", "segment", "risk_score", "primary_driver", "secondary_driver",
         "reason", "playbook", "secondary_playbook", "annual_net_revenue_inr", "days_to_contract_renewal",
         "outreach_draft", "guardrail_check", "csm_checklist"]].copy()
t15["csm_decision"] = ""; t15["csm_edits_or_notes"] = ""
ws2 = wb.create_sheet("Top15_Outreach", 1)
table(ws2, t15, widths={"reason": 50, "outreach_draft": 70, "csm_checklist": 45, "business_name": 20,
                        "primary_driver": 18, "csm_decision": 16, "csm_edits_or_notes": 30},
      wrap_cols=("reason", "outreach_draft", "csm_checklist"))
for i in range(2, len(t15) + 2):
    ws2.row_dimensions[i].height = 190
    ws2[f"K{i}"].number_format = "#,##0"
    for col in ("P", "Q"):
        ws2[f"{col}{i}"].fill = YELLOW
ws2.cell(len(t15) + 3, 1, "Yellow cells: CSM fills Approve / Edit / Reject. Nothing is sent without a human decision.").font = Font(name=F, size=9, italic=True)

# ------------------------------------------------------------ Over cap list
oc = p[p.eligible & ~p.outreach_this_month][["rank", "merchant_id", "business_name", "segment", "risk_score",
                                             "primary_driver", "playbook", "annual_value_inr", "days_to_contract_renewal", "reason"]].copy()
oc["annual_value_inr"] = oc.annual_value_inr.round(0)
from outreach import draft as _draft, validate as _validate, contact_plan as _plan
_rows = {r.merchant_id: r for r in p[p.eligible & ~p.outreach_this_month].itertuples()}
oc["channel"] = "Reviewed email (no call this month)"
oc["follow_up"] = [_plan(_rows[m], "email")["next"] for m in oc.merchant_id]
oc["email_draft"] = [_draft(_rows[m], "email") for m in oc.merchant_id]
oc["guardrail_check"] = ["PASS" if not _validate(t, _rows[m]) else "FAIL" for m, t in zip(oc.merchant_id, oc.email_draft)]
ws3 = wb.create_sheet("Over_Cap_Emails", 2)
table(ws3, oc, widths={"reason": 50, "business_name": 20, "primary_driver": 20, "email_draft": 70, "follow_up": 34},
      wrap_cols=("reason", "email_draft", "follow_up"))

# ------------------------------------------------------------ Tests, sensitivity
ws4 = wb.create_sheet("Tests")
table(ws4, tests, widths={"case": 46, "expected": 36, "engine_output": 44, "type": 30})
ws4.conditional_formatting.add(f"F2:F{len(tests)+1}", CellIsRule(operator="equal", formula=['"FAIL"'], fill=RED_F))
ws4.conditional_formatting.add(f"F2:F{len(tests)+1}", CellIsRule(operator="equal", formula=['"PASS"'], fill=GRN_F))
r0 = len(tests) + 3
ws4.cell(r0, 1, f'=COUNTIF(F2:F{len(tests)+1},"PASS")&" of "&COUNTA(F2:F{len(tests)+1})&" tests pass"').font = BOLD
ws4.cell(r0 + 1, 1, "Real-row tests check the engine against my own reading of the data, not the hidden labels. "
         "E7 and E8 are deliberate blind-spot tests and are expected to fail.").font = Font(name=F, size=9, italic=True)

sv = sens.merge(p[["merchant_id", "classification", "outreach_this_month"]], on="merchant_id")
sv = sv[(sv.pct_runs_high > 0) | (sv.pct_runs_top15 > 0)].sort_values("pct_runs_top15", ascending=False)
ws5 = wb.create_sheet("Sensitivity")
table(ws5, sv, widths={"classification": 20})
for i in range(2, len(sv) + 2):
    ws5[f"B{i}"].number_format = "0%"; ws5[f"C{i}"].number_format = "0%"
ws5.cell(len(sv) + 3, 1, "500 runs, each component weight scaled randomly by +/-30%. Merchants never High in any run are omitted "
         "(no decoy ever became High).").font = Font(name=F, size=9, italic=True)

# ------------------------------------------------------------ Method
m = wb.create_sheet("Method")
m.column_dimensions["A"].width = 30; m.column_dimensions["B"].width = 110
rows = [
    ("Step", "What happens (and who does it)"),
    ("1. Features (rules)", "TPV change = m6 vs average of m1-m3; months of decline out of 5; seasonal shape = m4 at least 15% below baseline AND m6 rebounds 10%+ from the m4/m5 trough; success-rate change in points; unresolved tickets; CSAT (missing = neutral, never zero); logins; products; renewal days."),
    ("2. Note reading (rules, LLM check)", "AM note mapped to a fixed taxonomy: competitive, pricing_renewal, performance_issue, service_issue, disengagement, seasonal_context, growth_context, resolved_neutral. Optional LLM classifies the same note; disagreement goes to a human."),
    ("3. Risk points (rules)", "Volume decline up to 35 (x0.7 if not consistent; x0.1 if seasonal shape in a seasonal industry or with seasonal note). Success-rate fall up to 30 (-1 pt = 0, -8 pts = 30). Service up to 25 (unresolved tickets 15 + CSAT 1-3). Engagement up to 16, only if TPV fell 10%+. Note up to 25. Renewal within 60/90 days adds 10/5, only if other risk exists. High >= 45, Medium 25-44, Low < 25."),
    ("4. Decoy guards", "Seasonal: excused only when the DATA shows a step-and-rebound, not on industry or note alone. Busy-but-healthy: total tickets are never scored, only unresolved ones. Low-volume: low logins only count when volume is also falling."),
    ("5. Driver and playbook (rules)", "Volume decline is treated as the symptom. The driver is the strongest of performance, service, commercial, disengagement, mapped to PB-1..PB-4. Second driver adds a secondary playbook if strong enough. Seasonal and stable go to PB-6; healthy growing goes to PB-5."),
    ("6. Prioritisation (rules)", "Only High-risk merchants are eligible for the 15 CSM calls. Among them, rank by risk proxy x annual net revenue (m6 TPV x 1% x 12) x urgency (1.25 if renewal within 30 days, 1.1 within 90)."),
    ("7. Outreach (template or LLM, then guardrails)", "Drafts use only the merchant's own numbers. Validator blocks any number not in the data, refunds, waivers, discounts, guarantees, invented deadlines, and internal words (churn, risk score, competitor). Failing LLM drafts fall back to the safe template."),
    ("8. Human in the loop", "CSM approves, edits or rejects every draft; any pricing change needs AM + finance approval; nothing is sent automatically."),
    ("Honest limitations", "No churn labels, so the risk score is a ranking, not a probability. Thresholds and weights were set by reading this data. Known blind spots: early churners with a small drop and no note (E7), and service pain before volume falls (E8). Tenure and city are not used."),
]
for i, (k, v) in enumerate(rows, 1):
    m.cell(i, 1, k).font = H_FONT if i == 1 else BOLD
    m.cell(i, 2, v).font = H_FONT if i == 1 else BODY
    if i == 1:
        m.cell(i, 1).fill = H_FILL; m.cell(i, 2).fill = H_FILL
    m.cell(i, 2).alignment = WRAP; m.cell(i, 1).alignment = WRAP

ws6 = wb.create_sheet("Playbooks")
table(ws6, playbooks, widths={"what_happens": 70, "when_it_applies": 50, "name": 26}, wrap_cols=("what_happens", "when_it_applies"))

# ------------------------------------------------------------ evidence sheets
raw_m = pd.read_excel("data_pack.xlsx", "P2_Merchants")
ws7 = wb.create_sheet("Ablation")
table(ws7, V.ablation(raw_m), widths={"What we switched off or changed": 40, "What we expected": 28,
                                      "What actually happened": 60, "Verdict": 60},
      wrap_cols=("What actually happened", "Verdict", "What we switched off or changed"))
gr_rows, gr_sum = V.guardrail_eval(p)
ws8 = wb.create_sheet("Guardrail_Test")
table(ws8, gr_sum, widths={"Set": 30})
r0 = len(gr_sum) + 3
ws8.cell(r0, 1, "Tone rules were designed on the Development set only. The Held-out score is the honest one.").font = Font(name=F, size=9, italic=True)
for j, c in enumerate(gr_rows.columns, 1):
    cell = ws8.cell(r0 + 2, j, c); cell.font = H_FONT; cell.fill = H_FILL
for i, row in enumerate(gr_rows.itertuples(index=False), r0 + 3):
    for j, v in enumerate(row, 1):
        ws8.cell(i, j, v).font = BODY
ws8.column_dimensions["C"].width = 70
cap_df = V.capacity_curve(p).round(3)
ws9 = wb.create_sheet("Capacity")
table(ws9, cap_df, widths={"business_name": 22})
for i in range(2, len(cap_df) + 2):
    for col in "DFG":
        ws9[f"{col}{i}"].number_format = "#,##0"
    ws9[f"H{i}"].number_format = "0%"
ws9.cell(len(cap_df) + 3, 1, "Expected value of a call = risk proxy x 25% save rate x yearly value - Rs 1,500. "
         "Every call up to the last at-risk merchant has positive expected value.").font = Font(name=F, size=9, italic=True)
ws10 = wb.create_sheet("Failure_Log")
table(ws10, pd.DataFrame(V.FAILURE_LOG, columns=["Type", "What went wrong", "What I did"]),
      widths={"Type": 24, "What went wrong": 75, "What I did": 60}, wrap_cols=("What went wrong", "What I did"))

wb.save(OUT)
print("saved", OUT)
