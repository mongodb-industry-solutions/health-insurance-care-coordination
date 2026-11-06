"""Composed reads: the only place insurance and clinical data meet for the UI.

The data is split across two databases and the frontend should not have to know. Everything
here joins the two sides into the shape the frontend already reads (`GET /api/members/{id}`
is the combined member document it always was; traces carry their step text). It is the
backend's job, and the backend's alone, because it is the only component allowed to hold
both databases.
"""
