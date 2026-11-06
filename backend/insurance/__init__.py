"""The insurance side of the backend: members, policies, plans and claims.

Everything here reads and writes the **insurance database** only. It never imports from
`clinical/` and never touches clinical data. The one place insurance and clinical data meet
is `views/` (composed reads) and `workflow/` (the clinical sync); `tests/test_boundaries.py`
enforces the rule.
"""
