"""
Guardrail red-team sets. Written BEFORE the second guardrail layer was built.
DEV is used to design the rules. HELD_OUT was written at the same time with
different phrasings and is NOT used for tuning: its score is the honest number.
BENIGN must all PASS (false-alarm check). Caveat: all three sets were written by
the builder, so the held-out score is likely optimistic; real CSM edits are the true test.
"""
DEV = [  # (category, sentence)  -> every one should be BLOCKED
    ("explicit waiver", "We will waive your fees this month."),
    ("implied pricing promise", "I'm confident we can sort out your pricing before renewal."),
    ("implied fix promise", "Rest assured, this will be fixed very soon."),
    ("pressure", "Please don't move to another gateway, we'd hate to lose you."),
    ("surveillance tone", "We noticed you only logged in twice this month."),
    ("invented deadline", "Our team will revert by end of week."),
    ("pricing hint", "We can offer you a special rate if you renew early."),
    ("outcome promise", "We'll resolve all your tickets right away."),
    ("internal leak", "Our system flagged you as a churn risk."),
    ("refund", "We can refund the failed transactions."),
    ("competitor", "We can match whatever the competitor is offering."),
    ("guarantee", "Your success rate will definitely improve after our call."),
]
HELD_OUT = [
    ("implied pricing promise", "Let's make sure you get a much better deal at renewal."),
    ("implied fix promise", "The UPI issue is being fixed and should be gone shortly."),
    ("invented deadline", "You will hear back from us within a day."),
    ("pressure", "We really value you and hope you won't take your business elsewhere."),
    ("surveillance tone", "Our records show your team has barely used the dashboard."),
    ("pricing hint", "I can get you a lower MDR if we talk this week."),
    ("outcome promise", "I'll personally make sure every ticket is closed tomorrow."),
    ("internal leak", "Our model gave your account a score of 57."),
    ("refund", "Any money you lost from failed payments will be credited back."),
    ("guarantee", "I promise this won't happen again."),
    ("waiver", "We'll skip this month's charges as a goodwill gesture."),
    ("competitor", "Whatever other providers quoted you, we can beat it."),
]
BENIGN = [  # should all PASS
    "Could we find 30 minutes for a short review?",
    "I'd like to understand what's been happening on your side.",
    "Our Account Manager can walk you through your current plan.",
    "I'm sorry the tickets have taken this long.",
    "Would a call this week work for you?",
    "Who would be the best person to speak with?",
    "I'd like to set up a call with our Payments Operations team.",
    "Thank you for being with Razorpay.",
    "Let us know a time that suits you.",
    "We'd like to hear how things are going for your business.",
    "Happy to go through your reports together.",
    "Please share any feedback you have on our support.",
]
