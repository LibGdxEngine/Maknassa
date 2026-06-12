// Shared types mirroring the backend serialization contract (reactions/api.py).
// Job envelope: { id, kind, state, progress, result, error }.

export type JobState = 'running' | 'done' | 'error' | 'cancelled'

export interface Job<R = unknown, P = JobProgress> {
  id: string
  kind: string
  state: JobState
  progress: P
  result: R | null
  error: string | null
}

// Live progress pushed by jobs as they run. Block/unblock stream done/total/outcomes
// (api._run_block); fetch streams done/total/phase (the active reaction tab, or null
// before the first tab — api._run_fetch); login leaves it empty.
export interface JobProgress {
  done?: number
  total?: number
  outcomes?: BlockOutcome[]
  phase?: string | null
}

// reactions/ui_fetch.py :: UIReactor
export interface UIReactor {
  name: string | null
  profile_url: string | null
  profile_key: string
  reaction_type: string
  avatar_url: string | null
}

// reactions/ui_fetch.py :: FetchResult
export interface FetchResult {
  reactors: UIReactor[]
  expected_total: number
}

// reactions/models.py :: BlockOutcome (status: blocked/unblocked/failed/skipped/dry_run)
export interface BlockOutcome {
  profile_key: string
  name: string | null
  profile_url: string | null
  status: string
  detail: string | null
}

// reactions/api.py :: GET /api/session
export interface SessionInfo {
  connected: boolean
  account_id: string | null
  default_profile_dir: string
  data_dir: string
}

// reactions/api.py :: GET/PUT /api/settings
export interface Settings {
  profile_dir: string
  headless: boolean
  min_delay: number
  max_delay: number
  stop_after: number
}

export interface HealthResponse {
  status: string
  version?: string
}

// 202 response from POST /api/{login,fetch,block,unblock}
export interface JobAccepted {
  job_id: string
}
