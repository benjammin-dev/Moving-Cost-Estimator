import { useState } from "react"
import { CircleAlert, DatabaseZap, Landmark, LoaderCircle } from "lucide-react"
import api from "../api"
import { Toggle } from "./controls"
import { importSummary } from "../movers"
import { buttonClass, cardClass, errorMessage, eyebrowClass, formatDateTime } from "../ui"

const KINDS = {
    fmcsa: {
        icon: DatabaseZap,
        title: "FMCSA import",
        description: "Washington household goods carriers with active federal (interstate) authority.",
    },
    utc: {
        icon: Landmark,
        title: "Washington UTC import",
        description: "Every household goods carrier on the UTC's list. Active permit holders are verified with their permit number.",
    },
}

/**
 * One import (FMCSA or UTC): its latest run, and a button to start one.
 * Imports run in the background, so while one is going the panel shows
 * that and the page keeps checking. Preview is on by default.
 */
function ImportPanel({ kind, latest, onStarted }) {
    const { icon: Icon, title, description } = KINDS[kind]
    const [preview, setPreview] = useState(true)
    const [starting, setStarting] = useState(false)
    const [error, setError] = useState("")
    const running = Boolean(latest && !latest.finished_at)

    const start = async () => {
        setStarting(true)
        setError("")
        try {
            const res = await api.post("/api/movers/imports/", { kind, dry_run: preview })
            onStarted(res.data)
        } catch (err) {
            setError(errorMessage(err, "The import couldn't be started."))
        } finally {
            setStarting(false)
        }
    }

    return (
        <section aria-label={title} className={`${cardClass} flex flex-col overflow-hidden`}>
            <div className="flex flex-1 flex-col gap-5 p-5 sm:p-6">
                <div className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-text">
                        <Icon size={16} />
                    </span>
                    <div className="min-w-0">
                        <h2 className="text-[0.9375rem] font-semibold text-ink">{title}</h2>
                        <p className="text-xs text-ink-3">{description}</p>
                        <LatestRun run={latest} kind={kind} />
                    </div>
                </div>

                <div className="mt-auto flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="sm:w-60">
                        <Toggle
                            name={`${kind}-preview`}
                            checked={preview}
                            onChange={(e) => setPreview(e.target.checked)}
                            label="Preview only"
                            description="Show what would change, save nothing"
                        />
                    </div>
                    <button type="button" onClick={start} disabled={starting || running} className={buttonClass.primary}>
                        {running ? "Running…" : starting ? "Starting…" : preview ? "Preview import" : "Run import"}
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

function LatestRun({ run, kind }) {
    if (!run) {
        return <p className="mt-3 text-sm text-ink-2">No imports yet.</p>
    }
    const who = run.triggered_by ? `by ${run.triggered_by}` : "from the command line"
    const label = run.dry_run ? "preview" : "import"

    if (!run.finished_at) {
        return (
            <p className="mt-3 flex items-center gap-2 text-sm text-ink" data-testid={`${kind}-latest`} role="status">
                <LoaderCircle size={15} className="animate-spin text-accent-text" aria-hidden="true" />
                {run.dry_run ? "Preview" : "Import"} running, started {formatDateTime(run.started_at)} {who}.
                {kind === "utc" && !run.dry_run && " The first one takes about 15 minutes."}
            </p>
        )
    }

    return (
        <div className="mt-3 space-y-1.5" data-testid={`${kind}-latest`}>
            <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className={eyebrowClass}>Last {label}</span>
                <span className="text-ink-2">{formatDateTime(run.started_at)} · {who}</span>
                {run.dry_run && <span className="rounded-full bg-subtle px-2 py-0.5 text-xs font-medium text-ink-2">Nothing saved</span>}
            </div>
            {run.succeeded ? (
                <p className="text-sm text-ink">{importSummary(run.stats, kind)}</p>
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
