"""
SentinelAI — Interactive Pipeline Tester
=========================================
Run:  .venv/bin/python test_interactive.py

Type your prompt, pick a use_case, and see every stage of the pipeline.

Commands:
  q / quit / exit  — exit the tester
  cls / clear      — clear screen
"""
from __future__ import annotations
import asyncio
import os


# ── Colors ─────────────────────────────────────────────────────────────────────
class C:
    RESET    = "\033[0m"
    BOLD     = "\033[1m"
    DIM      = "\033[2m"
    RED      = "\033[91m"
    GREEN    = "\033[92m"
    YELLOW   = "\033[93m"
    BLUE     = "\033[94m"
    MAGENTA  = "\033[95m"
    CYAN     = "\033[96m"
    WHITE    = "\033[97m"
    BG_RED   = "\033[41m"
    BG_GREEN = "\033[42m"


def header(title: str, color: str = C.CYAN):
    print()
    print(f"{color}{C.BOLD}{'─' * 70}{C.RESET}")
    print(f"{color}{C.BOLD}  {title}{C.RESET}")
    print(f"{color}{C.BOLD}{'─' * 70}{C.RESET}")


def row(label: str, value, color: str = C.WHITE):
    print(f"  {C.DIM}{label:<28}{C.RESET}{color}{value}{C.RESET}")


def sep():
    print(f"  {C.DIM}{'·' * 66}{C.RESET}")


# ── Startup ────────────────────────────────────────────────────────────────────
async def startup():
    print(f"\n{C.CYAN}{C.BOLD}🚀 SentinelAI Interactive Tester{C.RESET}")
    print(f"{C.DIM}   Warming up engines — please wait...\n{C.RESET}")
    from engines.trust.groundedness import initialize_knowledge_base
    from core.injection_detector import init_injection_detector
    await initialize_knowledge_base()
    await init_injection_detector()
    print(f"{C.GREEN}   ✅ All engines ready.\n{C.RESET}")


# ── Run one pipeline call ──────────────────────────────────────────────────────
async def run_one(prompt: str, use_case: str, tenant_id: str, user_id: str):
    from core.pipeline import run_pipeline
    from api.schemas import InterceptRequest

    action, audit = await run_pipeline(InterceptRequest(
        prompt=prompt,
        use_case=use_case,
        tenant_id=tenant_id,
        user_id=user_id,
    ))

    # ── Stage 0: Input ─────────────────────────────────────────────────────
    header("STAGE 0 — INPUT", C.BLUE)
    row("Prompt",           repr(prompt))
    row("Use Case",         str(use_case))
    row("Tenant / User",    f"{tenant_id} / {user_id}")
    row("Request ID",       audit.request_id)

    # ── Stage 1: Injection ─────────────────────────────────────────────────
    header("STAGE 1 — INJECTION DETECTION", C.MAGENTA)
    inj = audit.injection
    dc = C.RED if inj.detected else C.GREEN
    row("Detected",         str(inj.detected),       dc)
    row("Confidence",       f"{inj.confidence:.4f}")
    row("Method",           inj.method)
    if inj.matched_pattern:
        row("Matched Pattern",  inj.matched_pattern, C.RED)
    if inj.flagged_text:
        row("Flagged Text",     inj.flagged_text,    C.RED)

    # ── Stage 2: PII in Prompt ─────────────────────────────────────────────
    header("STAGE 2 — PII IN PROMPT", C.YELLOW)
    pii_p = audit.pii_in_prompt
    row("Found",            str(pii_p.found),        C.RED if pii_p.found else C.GREEN)
    row("Risk Score",       f"{pii_p.risk_score:.4f}")
    row("Entity Count",     str(pii_p.entity_count))
    row("High Risk Types",  str(pii_p.high_risk_entities) if pii_p.high_risk_entities else "none")
    if pii_p.entities:
        sep()
        for e in pii_p.entities:
            row(f"  [{e.entity_type}]",
                f"score={e.score:.2f}  method={e.detection_method}")

    # ── Stage 3: LLM Response ─────────────────────────────────────────────
    header("STAGE 3 — LLM RESPONSE", C.CYAN)
    row("Model Used",       str(audit.model_used))
    row("Tokens In",        str(audit.tokens_input))
    row("Tokens Out",       str(audit.tokens_output))
    row("Tokens Total",     str(audit.tokens_total))
    sep()
    print(f"  {C.WHITE}{audit.llm_response}{C.RESET}")

    # ── Stage 4a: Groundedness ─────────────────────────────────────────────
    header("STAGE 4a — GROUNDEDNESS", C.BLUE)
    g = audit.groundedness
    gc = C.RED if g.score < 0.5 else (C.YELLOW if g.score < 0.8 else C.GREEN)
    row("Score",            f"{g.score:.4f}",        gc)
    row("Total Claims",     str(g.total_claims_checked))
    row("Grounded Claims",  str(g.grounded_claims_count))
    row("KB Used",          str(g.use_case_kb_used))
    if g.flagged_claims:
        sep()
        row("Flagged Claims:", "",                   C.RED)
        for fc in g.flagged_claims:
            print(f"    {C.RED}• {getattr(fc, 'claim', str(fc))}{C.RESET}")

    # ── Stage 4b: PII in Response ──────────────────────────────────────────
    header("STAGE 4b — PII IN RESPONSE", C.YELLOW)
    pii_r = audit.pii_in_response
    row("Found",            str(pii_r.found),        C.RED if pii_r.found else C.GREEN)
    row("Risk Score",       f"{pii_r.risk_score:.4f}")
    row("Entity Count",     str(pii_r.entity_count))
    row("High Risk Types",  str(pii_r.high_risk_entities) if pii_r.high_risk_entities else "none")
    if pii_r.entities:
        sep()
        for e in pii_r.entities:
            row(f"  [{e.entity_type}]",
                f"score={e.score:.2f}  method={e.detection_method}")

    # ── Stage 4c: Bias Detection ───────────────────────────────────────────
    header("STAGE 4c — BIAS DETECTION", C.MAGENTA)
    b = audit.bias
    bc = C.RED if b.detected else C.GREEN
    row("Detected",         str(b.detected),         bc)
    row("Score",            f"{b.score:.4f}",        bc)
    row("Risk Score",       f"{b.risk_score:.4f}")
    row("Detection Method", b.detection_method)
    if b.detected:
        row("Protected Dims",   str(b.protected_dimensions), C.RED)
        row("Behaviors",        str(b.behaviors),            C.RED)
        row("Toxicity Score",   f"{b.toxicity_score:.4f}")
        row("Identity Hate",    f"{b.identity_hate_score:.4f}")
        if b.flagged_segments:
            sep()
            row("Flagged Segments:", "",             C.RED)
            for s in b.flagged_segments:
                print(f"    {C.RED}• {s}{C.RESET}")

    # ── Stage 5: Risk Scoring ──────────────────────────────────────────────
    header("STAGE 5 — RISK SCORING", C.RED)
    rs = audit.risk_score
    level_str = str(rs.level)
    lc = C.RED if "HIGH" in level_str else (C.YELLOW if "MEDIUM" in level_str else C.GREEN)
    row("Overall Score",    f"{rs.overall:.4f}",     lc)
    row("Risk Level",       level_str,               lc)
    row("Use Case",         str(rs.use_case))
    bd = rs.breakdown
    sep()
    row("Score Breakdown:", "")
    signals = {
        "injection_score":    bd.injection_score,
        "pii_prompt_score":   bd.pii_prompt_score,
        "pii_response_score": bd.pii_response_score,
        "groundedness_risk":  bd.groundedness_risk,
        "bias_score":         bd.bias_score,
    }
    for sig, val in signals.items():
        bar_len = int(val * 40)
        bar = "█" * bar_len + "░" * (40 - bar_len)
        bar_color = C.RED if val > 0.5 else (C.YELLOW if val > 0.2 else C.GREEN)
        print(f"    {C.DIM}{sig:<22}{C.RESET}{bar_color}{bar}{C.RESET} {val:.3f}")
    row("Dominant Signal",  bd.dominant_signal,      C.YELLOW)

    # ── Stage 6: Policy Decision ───────────────────────────────────────────
    header("STAGE 6 — POLICY DECISION", C.GREEN)
    pd = audit.policy_decision
    row("Approved",         str(pd.approved),        C.GREEN if pd.approved else C.RED)
    row("Final Action",     str(pd.final_action))
    row("Reason",           pd.reason)
    row("Policy File",      pd.policy_file)
    row("Threshold Applied",f"{pd.threshold_applied:.4f}")
    if pd.policy_rule_ids:
        row("Rule IDs",     str(pd.policy_rule_ids))

    # ── Stage 7: Final Output ─────────────────────────────────────────────
    header("STAGE 7 — FINAL ACTION & RESPONSE", C.GREEN)
    act = str(action.action)
    ac = (C.BG_RED + C.WHITE if act == "BLOCK"
          else C.YELLOW if act in ("REDACT", "REPAIR")
          else C.GREEN)
    row("Action",           act,                     ac + C.BOLD)
    row("Explanation",      action.explanation)
    row("Escalation Req.",  str(action.escalation_required))
    if action.redacted_entity_count:
        row("Entities Redacted", str(action.redacted_entity_count))
    sep()
    fc = C.RED if act == "BLOCK" else C.WHITE
    print(f"  {fc}{action.final_response}{C.RESET}")

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    badges = []
    if inj.detected:           badges.append(f"{C.BG_RED}{C.WHITE} INJECTION {C.RESET}")
    if pii_p.found:            badges.append(f"{C.YELLOW} PII-PROMPT {C.RESET}")
    if pii_r.found:            badges.append(f"{C.YELLOW} PII-RESPONSE {C.RESET}")
    if b.detected:             badges.append(f"{C.MAGENTA} BIAS {C.RESET}")
    if g.score < 0.5:          badges.append(f"{C.RED} UNGROUNDED {C.RESET}")
    if not badges:             badges.append(f"{C.GREEN} CLEAN {C.RESET}")
    print(f"  {C.BOLD}SUMMARY:{C.RESET}  " + "  ".join(badges))
    print(f"  ACTION  → {ac}{C.BOLD}{act}{C.RESET}"
          f"  |  RISK → {lc}{rs.overall:.3f} ({level_str}){C.RESET}")
    print()


# ── Interactive loop ───────────────────────────────────────────────────────────
USE_CASES = ["hr_copilot", "customer_chatbot", "finance_tool"]


def pick_use_case() -> str:
    print()
    for i, uc in enumerate(USE_CASES, 1):
        print(f"  {C.CYAN}{i}{C.RESET}. {uc}")
    while True:
        choice = input(f"\n  {C.BOLD}Use case [1-3, default=1]: {C.RESET}").strip()
        if not choice:
            return USE_CASES[0]
        if choice.isdigit() and 1 <= int(choice) <= len(USE_CASES):
            return USE_CASES[int(choice) - 1]
        print(f"  {C.RED}Enter 1, 2 or 3.{C.RESET}")


async def main():
    await startup()
    print(f"{C.DIM}  Commands: q=quit  cls=clear{C.RESET}")

    while True:
        try:
            print()
            prompt = input(f"{C.BOLD}{C.CYAN}▶ Prompt: {C.RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            print(f"{C.DIM}  Bye!{C.RESET}")
            break

        if not prompt:
            continue
        if prompt.lower() in ("q", "quit", "exit"):
            print(f"{C.DIM}  Bye!{C.RESET}")
            break
        if prompt.lower() in ("cls", "clear"):
            os.system("clear")
            continue

        use_case = pick_use_case()
        try:
            await run_one(prompt, use_case, "acme_corp", "test_user")
        except Exception as exc:
            print(f"\n  {C.RED}❌ Pipeline error: {exc}{C.RESET}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    import logging
    for noisy in ["sentinelai", "presidio-analyzer", "httpx",
                  "sentence_transformers", "transformers", "torch"]:
        logging.getLogger(noisy).setLevel(logging.ERROR)

    asyncio.run(main())
