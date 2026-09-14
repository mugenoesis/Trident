import { gcodeDownloadUrl, thumbnailUrl } from '../api'
import type { JobRecord } from '../types'

interface JobPanelProps {
  canSlice: boolean
  alreadySliced: boolean
  onSlice: () => void
  slicing: boolean
  currentJob: JobRecord | null
  history: JobRecord[]
  onPreview: (jobId: string) => void
  onDelete: (jobId: string) => void
}

function StatusBadge({ status }: { status: JobRecord['status'] }) {
  return <span className={`status-badge status-${status}`}>{status}</span>
}

function JobProgressBar({ job }: { job: JobRecord }) {
  const percent = job.progress?.total_percent ?? job.progress?.plate_percent ?? 0
  return (
    <div className="job-progress">
      <div className="job-progress-bar" style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
      {job.progress?.message && <div className="job-progress-message">{job.progress.message}</div>}
    </div>
  )
}

export default function JobPanel({
  canSlice,
  alreadySliced,
  onSlice,
  slicing,
  currentJob,
  history,
  onPreview,
  onDelete,
}: JobPanelProps) {
  return (
    <div className="job-panel">
      <button className="slice-button" type="button" disabled={!canSlice || slicing} onClick={onSlice}>
        {slicing ? 'Slicing…' : 'Slice'}
      </button>
      {alreadySliced && !slicing && (
        <div className="job-hint">Nothing changed since the last slice.</div>
      )}

      {currentJob && (
        <div className="current-job">
          <StatusBadge status={currentJob.status} />
          {(currentJob.status === 'queued' || currentJob.status === 'running') && (
            <JobProgressBar job={currentJob} />
          )}
          {currentJob.status === 'succeeded' && (
            <div className="job-result">
              <button
                type="button"
                className="preview-button"
                onClick={() => onPreview(currentJob.id)}
              >
                View G-code
              </button>
              <a className="download-button" href={gcodeDownloadUrl(currentJob.id)} download>
                Download G-code
              </a>
              <img
                className="job-thumbnail"
                src={thumbnailUrl(currentJob.id)}
                alt="Slice thumbnail"
                onError={(e) => {
                  ;(e.target as HTMLImageElement).style.display = 'none'
                }}
              />
            </div>
          )}
          {currentJob.status === 'failed' && (
            <div className="job-error">{currentJob.error ?? 'Slicing failed'}</div>
          )}
        </div>
      )}

      {history.length > 0 && (
        <details className="job-history">
          <summary>Job history ({history.length})</summary>
          <ul>
            {history.map((job) => (
              <li key={job.id}>
                <StatusBadge status={job.status} />
                <span className="job-history-time">{new Date(job.created_at).toLocaleString()}</span>
                {job.status === 'succeeded' && (
                  <>
                    <button type="button" className="link-button" onClick={() => onPreview(job.id)}>
                      Preview
                    </button>
                    <a href={gcodeDownloadUrl(job.id)} download>
                      G-code
                    </a>
                  </>
                )}
                <button
                  type="button"
                  className="link-button job-delete"
                  onClick={() => onDelete(job.id)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
