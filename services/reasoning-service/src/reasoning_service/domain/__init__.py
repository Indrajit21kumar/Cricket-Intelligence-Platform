"""Reasoning domain — the pure inference pipeline (M13 §5).

Pure logic with no I/O: assemble facts, execute M12 rules, resolve conflicts,
combine confidence, and assemble evidence-linked findings. The service layer
wraps these with the sources + the store.
"""
