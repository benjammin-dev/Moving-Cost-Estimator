import { useState } from "react"
import { CircleAlert, DatabaseZap } from "lucide-react"
import api from "../api"
import { Toggle } from "./controls"
import { importSummary } from "../movers"
import { buttonClass, cardClass, errorMessage, eyebrowClass, formatDateTime } from "../ui"

/**
 * The latest FMCSA import, and a button to run one now. Preview (dry run)
 * is on by default, so the first click never changes anything.
 */
function ImportPanel({ latest, onImported }) {
    const [preview, setPreview] = useState(true)
    const [running, setRunning] = useState(false)
    const [error, setError] = useState("")

    const runImport = async () => {
        setRunning(true)
        setError("")
        try {
            const res = await api.post("/api/movers/imports/", { dry_run: preview })
            onImported(res.data)
        } catch (err) {
            setError(errorMessage(err, "The import failed."))
        } finally {
            setRunning(false)
        }
    }

    return (
        <section aria-label="FMCSA import" className={`${cardClass} mb-8 overflow-hidden`}>
            <div className="flex flex-wrap items-start justify-between gap-6 p-5 sm:p-6">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                    <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-text">
                        <DatabaseZap size={16} />
                    </span>
                    <div className="min-w-0">
                        <h2 className="text-[0.9375rem] font-semibold text-ink">FMCSA import</h2>
                        <p className="text-xs text-ink-3">Washington household goods carriers with active federal authority.</p>
                        <LatestRun run={latest} />
                    </div>
                </div>

                <div className="flex w-full flex-col gap-3 sm:w-64">
                    <Toggle
                        name="preview"
                        checked={preview}
                        onChange={(e) => setPreview(e.target.checked)}
                        label="Preview only"
                        description="Show what would change, save nothing"
                    />
                    <button type="button" onClick={runImport} disabled={running} className={`${buttonClass.primary} w-full`}>
                        {running ? "Running…" : preview ? "Preview import" : "Run import"}
                    </button>
                </div>
            </div>
            {error && (
                <p role="alert" className="flex items-start gap-2 border-t border-line bg-danger-soft px-5 py-3 text-sm text-ink sm:px-6">
                    <CircleAlert size={16} className="mt-0.5 shrink-0 text-danger" />
                    {error}
                </p>
            )}
        </section>
    )
}

function LatestRun({ run }) {
    if (!run) {
        return <p className="mt-3 text-sm text-ink-2">No imports yet.</p>
    }
    const who = run.triggered_by ? `by ${run.triggered_by}` : "from the command line"
    return (
        <div className="mt-3 space-y-1.5" data-testid="latest-import">
            <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className={eyebrowClass}>Last {run.dry_run ? "preview" : "import"}</span>
                <span className="text-ink-2">{formatDateTime(run.started_at)} · {who}</span>
                {run.dry_run && <span className="rounded-full bg-subtle px-2 py-0.5 text-xs font-medium text-ink-2">Nothing saved</span>}
            </div>
            {run.succeeded ? (
                <p className="text-sm text-ink">{importSummary(run.stats)}</p>
            ) : (
                <p className="text-sm text-danger">Failed: {run.error || "unknown error"}</p>
            )}
            {run.messages?.length > 0 && (
                <details className="text-sm">
                    <summary className="cursor-pointer text-accent-text hover:underline underline-offset-4">
                        {run.messages.length} {run.messages.length === 1 ? "message" : "messages"} to review
                    </summary>
                    <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto rounded-lg border border-line bg-subtle/60 p-3 text-xs text-ink-2">
                        {run.messages.map((m, i) => <li key={i}>{m}</li>)}
                    </ul>
                </details>
            )}
        </div>
    )
}

export default ImportPanel
