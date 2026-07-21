"""Audit-logging helper — one-call recording of sensitive actions.

The full implementation (a single ``record(action, entity, meta)`` call that
writes an ``audit_log`` row keyed by tenant + actor + correlation) lands in
M01 Step 7, once :mod:`cip_data` provides the ``audit_log`` table and session
helpers. This module is intentionally empty in Step 2 so importers of
``cip_core.audit`` in later steps don't need to change import paths.
"""

from __future__ import annotations
