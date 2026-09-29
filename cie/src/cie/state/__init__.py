"""The live state: the authoritative, versioned model of the business.

Records (orders, invoices, milestones, tasks, contracts, people ...) with stable ids, field-level sources and
authority, allowed status transitions, conflicts that stay open until resolved, and idempotent events applied in
commit order. Analyses such as REM read this state; they do not own it.
"""
