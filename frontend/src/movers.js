// Helpers for the staff-only Movers pages.

export const STATUS_OPTIONS = [
    { value: "unverified", label: "Unverified" },
    { value: "verified", label: "Verified" },
    { value: "inactive", label: "Inactive" },
]

export const STATUS_LABELS = Object.fromEntries(STATUS_OPTIONS.map((o) => [o.value, o.label]))

export const SOURCE_LABELS = {
    fmcsa: "FMCSA import",
    utc: "Washington UTC import",
    staff: "Added by staff",
}

// Filters kept in the page URL, so the back button and links keep them.
export const MOVER_FILTERS = ["search", "status", "claimed", "authority", "utc"]

export function moverListQuery(params) {
    const query = new URLSearchParams()
    for (const key of [...MOVER_FILTERS, "page"]) {
        const value = params.get(key)
        if (value) query.set(key, value)
    }
    return query.toString()
}

// FMCSA's public SAFER company snapshot for a USDOT number.
export function saferUrl(usdotNumber) {
    return `https://safer.fmcsa.dot.gov/query.asp?searchtype=ANY&query_type=queryCarrierSnapshot&query_param=USDOT&query_string=${encodeURIComponent(usdotNumber)}`
}

// The company's page on the Washington UTC's regulated companies lookup.
export function utcCompanyUrl(companyId) {
    return `https://www.utc.wa.gov/company/${encodeURIComponent(companyId)}`
}

export function displayName(mover) {
    return mover.dba_name || mover.name
}

// One line describing an import run's results.
export function importSummary(stats = {}, kind = "fmcsa") {
    if (kind === "utc") {
        const parts = [
            `${stats.created ?? 0} new`,
            `${stats.updated ?? 0} updated`,
            `${stats.verified ?? 0} verified with a UTC permit`,
        ]
        if (stats.deactivated) parts.push(`${stats.deactivated} set inactive`)
        if (stats.duplicates_skipped) parts.push(`${stats.duplicates_skipped} duplicate listings skipped`)
        if (stats.conflicts) parts.push(`${stats.conflicts} conflicts`)
        if (stats.errors) parts.push(`${stats.errors} pages couldn't be read`)
        return parts.join(" · ")
    }
    const parts = [
        `${stats.created ?? 0} new`,
        `${stats.updated ?? 0} updated`,
        `${stats.inactive_skipped ?? 0} without active authority`,
        `${stats.forwarders_skipped ?? 0} freight forwarders skipped`,
    ]
    if (stats.deactivated) parts.push(`${stats.deactivated} set inactive`)
    if (stats.conflicts) parts.push(`${stats.conflicts} MC conflicts`)
    return parts.join(" · ")
}
