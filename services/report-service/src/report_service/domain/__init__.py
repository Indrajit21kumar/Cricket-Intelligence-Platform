"""Report domain — pure assembly + scoring + guardrails (M14).

Pure logic with no I/O: turn M13's ``analysis.reasoned`` (+ M10/M11 metrics, M15
benchmarks, M04 history) into the structured report, and ground the LLM
narrative + AI Coach strictly in that evidence. The service layer wraps these
with the sources + the store.
"""
