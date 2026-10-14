"""Final Host tool catalog registrations and owner-pinned durable status."""

from __future__ import annotations

from fastmcp import FastMCP

from android_mcp_host.controlled_build_jobs import ControlledBuildJobs
from android_mcp_host.controlled_build_tool import register_build_tool
from android_mcp_host.durable_job_tool import register_job_status_tool
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.emulator_snapshot_manager import EmulatorSnapshotManager
from android_mcp_host.emulator_snapshot_tool import register_snapshot_tool
from android_mcp_host.synthetic_bugreport import BugreportService
from android_mcp_host.synthetic_bugreport_tool import register_bugreport_tool


def register_host_tail(
    server: FastMCP,
    bugreport: BugreportService | None,
    snapshot_manager: EmulatorSnapshotManager | None,
    build_jobs: ControlledBuildJobs | None,
    durable_jobs: DurableJobStore | None,
    job_owner: str | None,
) -> None:
    """Retains existing catalog ordering and rejects unmatched job owners."""
    if bugreport is not None:
        register_bugreport_tool(server, bugreport)
    if snapshot_manager is not None:
        register_snapshot_tool(server, snapshot_manager)
    if build_jobs is not None:
        register_build_tool(server, build_jobs)
    if (durable_jobs is None) != (job_owner is None):
        raise ValueError("Durable job status needs a trusted store and owner")
    if durable_jobs is not None and job_owner is not None:
        if not durable_jobs.validate_owner(job_owner):
            raise ValueError("Invalid Host job owner")
        register_job_status_tool(server, durable_jobs, job_owner)
