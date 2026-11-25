import { STATUS_LABELS } from "../movers"

const badgeClass = "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium"

const STATUS_STYLES = {
    unverified: "bg-warn-soft text-warn",
    verified: "bg-success-soft text-success",
    inactive: "bg-subtle text-ink-3",
}

export function StatusBadge({ status }) {
    return <span className={`${badgeClass} ${STATUS_STYLES[status] ?? STATUS_STYLES.inactive}`}>{STATUS_LABELS[status] ?? status}</span>
}

export function ClaimedBadge({ claimed }) {
    return claimed
        ? <span className={`${badgeClass} bg-accent-soft text-accent-text`}>Claimed</span>
        : <span className={`${badgeClass} border border-line text-ink-3`}>Unclaimed</span>
}

export function AuthorityBadge({ active }) {
    if (active === null || active === undefined) return <span className={`${badgeClass} bg-subtle text-ink-3`}>Not in FMCSA data</span>
    return active
        ? <span className={`${badgeClass} bg-success-soft text-success`}>Authority active</span>
        : <span className={`${badgeClass} bg-danger-soft text-danger`}>Authority lapsed</span>
}
