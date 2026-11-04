"""Python imports this at start-up in each child of the suite, through the PYTHONPATH `suite_guard` sets."""

import audit_guard

audit_guard.install_from_env()
