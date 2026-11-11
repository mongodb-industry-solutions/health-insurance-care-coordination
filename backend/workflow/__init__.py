"""Frontend-facing authorization workflow: start, live progress, human closure.

The member portal's "Start Process" button, the live progress stream, and the medical
director's closure action. This package drives the two agents in turn and reads every
decision off the trace's `workflow.stage`; it never decides a case itself.

Step 0 onwards belongs to the Insurance Agent, and the clinical steps to the
Care-Coordination Agent, so `start` hands the case to them and watches. What this package
*does* write is the clinical record (`clinical_sync.py`): the agents each work in one
database, so the physician's order flipping to `in_progress`, being linked to the trace and
resolved, and `approved_therapy` landing on the care plan, are done here, by the one component
allowed to hold both databases.
"""

from .service import AuthorizationWorkflowService
from .agent_invoker import AgentInvoker

__all__ = ["AuthorizationWorkflowService", "AgentInvoker"]
