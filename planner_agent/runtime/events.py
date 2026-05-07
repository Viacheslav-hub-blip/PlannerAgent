"""Runtime event names used by lineage and audit layers."""

LINEAGE_EVENT_TYPES = {
    "run_started",
    "context_snapshot",
    "plan_created",
    "task_scheduled",
    "worker_started",
    "tool_called",
    "artifact_created",
    "task_completed",
    "validation_completed",
    "evidence_checked",
    "replan_created",
    "final_report",
    "branch_started",
    "feedback_received",
    "learning_applied",
}

__all__ = ["LINEAGE_EVENT_TYPES"]
