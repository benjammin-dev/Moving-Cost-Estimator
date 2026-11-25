import { useEffect, useState } from "react"
import { Link, useLocation, useSearchParams } from "react-router-dom"
import { ChevronLeft, ChevronRight, Search } from "lucide-react"
import api from "../api"
import ImportPanel from "../components/ImportPanel"
import { AuthorityBadge, ClaimedBadge, StatusBadge } from "../components/MoverBadges"
import NavBar from "../components/NavBar"
import Notice from "../components/Notice"
import PageHeader from "../components/PageHeader"
import StaffOnly from "../components/StaffOnly"
import Stat from "../components/Stat"
import { Segmented } from "../components/controls"
import { MOVER_FILTERS, STATUS_OPTIONS, displayName, importSummary, moverListQuery } from "../movers"
import { buttonClass, cardClass, errorMessage, inputClass } from "../ui"

const PAGE_SIZE = 25
const STATUS_FILTERS = [{ value: "", label: "All" }, ...STATUS_OPTIONS]

// Staff-only directory of mover profiles, with the FMCSA import controls.
function Movers() {
    const [params, setParams] = useSearchParams()
    const query = moverListQuery(params)
    const [reload, setReload] = useState(0)
    const [summary, setSummary] = useState(null)
    const [list, setList] = useState({ key: null, data: null })
    const [error, setError] = useState("")
    const [success, setSuccess] = useState("")
    const [forbidden, setForbidden] = useState(false)
    // Remounting the filter bar resets its search box. Clearing filters
    // passes "" explicitly: the URL only catches up a moment later.
    const [filterBar, setFilterBar] = useState(() => ({ key: 0, search: params.get("search") ?? "" }))

    const handleError = (err, fallback) => {
        if (err?.response?.status === 403) setForbidden(true)
        else setError(errorMessage(err, fallback))
    }

    useEffect(() => {
        api.get("/api/movers/summary/")
            .then((res) => setSummary(res.data))
            .catch((err) => handleError(err, "Couldn't load the movers summary."))
    }, [reload])

    const listKey = `${query}#${reload}`
    useEffect(() => {
        let cancelled = false
        api.get(`/api/movers/${query ? `?${query}` : ""}`)
            .then((res) => { if (!cancelled) setList({ key: listKey, data: res.data }) })
            .catch((err) => {
                if (cancelled) return
                setList({ key: listKey, data: null })
                handleError(err, "Couldn't load movers.")
            })
        return () => { cancelled = true }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [listKey])

    const loading = list.key !== listKey
    const data = list.data

    // Change filters in the URL; any filter change goes back to page 1.
    const setFilter = (key, value) => {
        const next = new URLSearchParams(params)
        if (value) next.set(key, value)
        else next.delete(key)
        if (key !== "page") next.delete("page")
        setParams(next, { replace: key === "search" })
    }
    const clearFilters = () => {
        setParams(new URLSearchParams())
        setFilterBar((bar) => ({ key: bar.key + 1, search: "" }))
    }
    const filtered = MOVER_FILTERS.some((key) => params.get(key))

    const onImported = (run) => {
        setReload((n) => n + 1)
        setSuccess(run.dry_run ? `Preview finished, nothing saved: ${importSummary(run.stats)}.` : `Import finished: ${importSummary(run.stats)}.`)
    }

    const counts = summary?.counts
    const page = Number(params.get("page")) || 1
    const pages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1

    return (
        <>
            <NavBar />
            <main className="mx-auto max-w-6xl px-4 pb-24 pt-10 sm:px-6 sm:pt-14">
                <PageHeader
                    eyebrow="Staff"
                    title="Movers"
                    description="Moving companies imported from FMCSA or listed by movers. Profiles can't be booked until they're verified with a UTC permit number."
                />

                {forbidden ? (
                    <StaffOnly />
                ) : (
                    <>
                        <Notice message={error} onDismiss={() => setError("")} />
                        <Notice message={success} kind="success" onDismiss={() => setSuccess("")} />

                        {counts && (
                            <section aria-label="Mover counts" className="mb-8 grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-line bg-line shadow-card lg:grid-cols-5">
                                <Stat label="Profiles" value={counts.total} note={`${counts.claimed} claimed`} />
                                <Stat label="Unverified" value={counts.unverified} />
                                <Stat label="Verified" value={counts.verified} />
                                <Stat label="Bookable" value={counts.bookable} note="Verified with a UTC permit" />
                                <Stat label="Inactive" value={counts.inactive} />
                            </section>
                        )}

                        {summary && <ImportPanel latest={summary.latest_import} onImported={onImported} />}

                        <Filters key={filterBar.key} initialSearch={filterBar.search} params={params} setFilter={setFilter} />

                        <MoverResults
                            data={data}
                            loading={loading}
                            filtered={filtered}
                            onClear={clearFilters}
                        />

                        {data && data.count > PAGE_SIZE && (
                            <nav aria-label="Pages" className="mt-5 flex flex-wrap items-center justify-between gap-3 text-sm text-ink-2">
                                <span className="tabular-nums">
                                    {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, data.count)} of {data.count}
                                </span>
                                <div className="flex gap-2">
                                    <button type="button" className={buttonClass.secondary} disabled={page <= 1} onClick={() => setFilter("page", page - 1 > 1 ? String(page - 1) : "")}>
                                        <ChevronLeft size={15} /> Previous
                                    </button>
                                    <button type="button" className={buttonClass.secondary} disabled={page >= pages} onClick={() => setFilter("page", String(page + 1))}>
                                        Next <ChevronRight size={15} />
                                    </button>
                                </div>
                            </nav>
                        )}
                    </>
                )}
            </main>
        </>
    )
}

function Filters({ initialSearch, params, setFilter }) {
    // The search box updates the URL shortly after typing stops.
    const [search, setSearch] = useState(initialSearch)
    const urlSearch = params.get("search") ?? ""
    useEffect(() => {
        if (search.trim() === urlSearch) return
        const timer = setTimeout(() => setFilter("search", search.trim()), 300)
        return () => clearTimeout(timer)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [search])

    const selectClass = `${inputClass} py-1.5 text-sm`
    return (
        <div className="mb-5 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_auto_auto] md:items-end">
            <div className="relative">
                <Search size={15} className="pointer-events-none absolute inset-y-0 left-3 my-auto text-ink-3" aria-hidden="true" />
                <input
                    type="search"
                    aria-label="Search movers"
                    placeholder="Name, city, USDOT or MC number"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className={`${inputClass} py-1.5 pl-9 text-sm`}
                />
            </div>
            <div className="md:w-80">
                <Segmented name="status-filter" value={params.get("status") ?? ""} options={STATUS_FILTERS} onChange={(v) => setFilter("status", v)} />
            </div>
            <select aria-label="Claimed" value={params.get("claimed") ?? ""} onChange={(e) => setFilter("claimed", e.target.value)} className={selectClass}>
                <option value="">Claimed or not</option>
                <option value="true">Claimed</option>
                <option value="false">Unclaimed</option>
            </select>
            <select aria-label="Federal authority" value={params.get("authority") ?? ""} onChange={(e) => setFilter("authority", e.target.value)} className={selectClass}>
                <option value="">Any authority</option>
                <option value="active">Authority active</option>
                <option value="lapsed">Authority lapsed</option>
            </select>
        </div>
    )
}

function MoverResults({ data, loading, filtered, onClear }) {
    const location = useLocation()
    const linkState = { from: location.search }

    if (loading && !data) {
        return (
            <div className="space-y-2" aria-hidden="true">
                {[0, 1, 2].map((i) => <div key={i} className="h-14 animate-pulse rounded-xl border border-line bg-surface" />)}
            </div>
        )
    }
    if (!data) return null

    if (data.count === 0) {
        return (
            <div className="rounded-2xl border border-dashed border-line-strong px-6 py-12 text-center">
                {filtered ? (
                    <>
                        <p className="text-sm text-ink-2">No movers match these filters.</p>
                        <button type="button" onClick={onClear} className={`${buttonClass.secondary} mt-4`}>Clear filters</button>
                    </>
                ) : (
                    <p className="text-sm text-ink-2">No movers yet. Turn off “Preview only” and run an import to load carriers from FMCSA.</p>
                )}
            </div>
        )
    }

    return (
        <div className={loading ? "opacity-60 transition-opacity" : "transition-opacity"} aria-busy={loading}>
            {/* Table on wider screens */}
            <div className={`${cardClass} hidden overflow-hidden md:block`}>
                <table className="w-full text-left text-sm">
                    <thead className="border-b border-line bg-subtle/60 text-[0.6875rem] uppercase tracking-[0.08em] text-ink-3">
                        <tr>
                            <th scope="col" className="px-5 py-3 font-semibold">Mover</th>
                            <th scope="col" className="px-3 py-3 font-semibold">Location</th>
                            <th scope="col" className="px-3 py-3 font-semibold">USDOT / MC</th>
                            <th scope="col" className="px-3 py-3 font-semibold">Profile</th>
                            <th scope="col" className="px-5 py-3 font-semibold">Federal authority</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                        {data.results.map((m) => (
                            <tr key={m.id} className="transition-colors hover:bg-subtle/50">
                                <td className="px-5 py-3">
                                    <Link to={`/movers/${m.id}`} state={linkState} className="font-medium text-ink hover:text-accent-text hover:underline underline-offset-4">
                                        {displayName(m)}
                                    </Link>
                                    {m.dba_name && <div className="text-xs text-ink-3">{m.name}</div>}
                                </td>
                                <td className="px-3 py-3 text-ink-2">{[m.city, m.state].filter(Boolean).join(", ") || "-"}</td>
                                <td className="px-3 py-3 tabular-nums text-ink-2">
                                    {m.usdot_number}
                                    {m.mc_number && <div className="text-xs text-ink-3">MC {m.mc_number}</div>}
                                </td>
                                <td className="px-3 py-3">
                                    <div className="flex flex-wrap gap-1.5"><StatusBadge status={m.status} /><ClaimedBadge claimed={m.claimed} /></div>
                                </td>
                                <td className="px-5 py-3"><AuthorityBadge active={m.fmcsa_authority_active} /></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Cards on phones */}
            <ul className="space-y-3 md:hidden">
                {data.results.map((m) => (
                    <li key={m.id}>
                        <Link to={`/movers/${m.id}`} state={linkState} className={`${cardClass} block p-4 transition-colors hover:border-line-strong`}>
                            <div className="font-medium text-ink">{displayName(m)}</div>
                            <div className="mt-0.5 text-xs text-ink-3">
                                {[m.city, m.state].filter(Boolean).join(", ")} · USDOT {m.usdot_number}{m.mc_number && ` · MC ${m.mc_number}`}
                            </div>
                            <div className="mt-3 flex flex-wrap gap-1.5">
                                <StatusBadge status={m.status} />
                                <ClaimedBadge claimed={m.claimed} />
                                <AuthorityBadge active={m.fmcsa_authority_active} />
                            </div>
                        </Link>
                    </li>
                ))}
            </ul>
        </div>
    )
}

export default Movers
