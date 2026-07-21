# Creating a new CIP service

> **Status:** Placeholder — filled in at M01 Step 7.

The final version of this document walks through creating a new service
by copying `services/reference-service/` (via `scripts/scaffold_service.py`),
including how the new service inherits the tenancy context, correlation IDs,
observability, error envelope, and CI gates from the shared libraries.
