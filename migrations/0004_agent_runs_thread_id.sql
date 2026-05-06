-- Add thread_id correlator to agent_runs.
--
-- thread_id is the LangGraph checkpoint key the FastAPI HITL endpoints already
-- expose (/runs/{thread_id}, /runs/{thread_id}/resume). agent_runs.id is a
-- separate surrogate UUID for the row itself; thread_id is what makes the row
-- joinable back to the workflow state and to the resume API call.
--
-- Nullable to match the existing nullable-by-default treatment of fixture_filename
-- and langsmith_run_id. The application always populates it on insert; the column
-- nullability is intentional headroom, not a permitted shape.

ALTER TABLE procure_agent.agent_runs
    ADD COLUMN thread_id text;

CREATE INDEX idx_agent_runs_thread_id
    ON procure_agent.agent_runs (thread_id);
