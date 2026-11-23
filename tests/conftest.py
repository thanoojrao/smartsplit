"""Shared pytest setup.

Hypothesis profiles: `dev` (default) for the local loop, `ci` for slow or shared runners,
where timing deadlines would make property tests flaky. Select with HYPOTHESIS_PROFILE=ci.
"""

import os

from hypothesis import settings

settings.register_profile("dev", max_examples=100)
settings.register_profile("ci", max_examples=200, deadline=None, derandomize=True, print_blob=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
