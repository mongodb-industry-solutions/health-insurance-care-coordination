"""The clinical side of the backend: profiles and the care agent's reasoning text.

Everything here reads and writes the **clinical database** only. It never imports from
`insurance/` and never touches policies, plans, claims or eligibility. The one place the
two meet is `views/` (composed reads) and `workflow/` (the clinical sync); the import
rules are enforced by `tests/test_boundaries.py`.
"""
