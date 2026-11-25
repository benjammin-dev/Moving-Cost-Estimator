import { eyebrowClass } from "../ui"

// A number tile, used in rows of summary stats.
function Stat({ label, value, note }) {
    return (
        <div className="bg-surface p-5 sm:p-6">
            <div className={eyebrowClass}>{label}</div>
            <div className="mt-2 font-display text-4xl leading-none tracking-tight text-ink tabular-nums">{value}</div>
            {note && <div className="mt-2 text-xs text-ink-3">{note}</div>}
        </div>
    )
}

export default Stat
