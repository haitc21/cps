"""Legacy persistence seam for the provider aggregate vertical slice."""

from __future__ import annotations

# SYSTEM-scope aggregate connections use a sentinel project identity until the
# provider table owns connection metadata directly.
AGGREGATE_SYSTEM_PROJECT_NAME = "__system__"
AGGREGATE_SYSTEM_PROJECT_DOMAIN = "Default"
