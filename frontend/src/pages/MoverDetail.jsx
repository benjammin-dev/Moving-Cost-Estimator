import { useEffect, useState } from "react"
import { Link, useLocation, useParams } from "react-router-dom"
import { ArrowLeft, Building2, DatabaseZap, ExternalLink, Landmark, ShieldCheck } from "lucide-react"
import api from "../api"
import { AuthorityBadge, ClaimedBadge, StatusBadge, UtcBadge } from "../components/MoverBadges"
import NavBar from "../components/NavBar"
import Notice from "../components/Notice"
import StaffOnly from "../components/StaffOnly"
import { Field, Segmented } from "../components/controls"
import { SOURCE_LABELS, STATUS_OPTIONS, displayName, saferUrl, utcCompanyUrl } from "../movers"
import { buttonClass, cardClass, errorMessage, formatDateTime, formatPhone, inputClass } from "../ui"

// One mover's profile, with the staff verification controls.
function MoverDetail() {
    const { id } = useParams()
    const location = useLocation()
    const backTo = `/movers${location.state?.from ?? ""}`
    const [result, setResult] = useState({ id: null, mover: null, problem: null })
    const [error, setError] = useState("")
    const [success, setSuccess] = useState(() => location.state?.created ? "Mover added. Verify it once you've checked its UTC permit." : "")

    useEffect(() => {
        let cancelled = false
        api.get(`/api/movers/${id}/`)
            .then((res) => { if (!cancelled) setResult({ id, mover: res.data, problem: null }) })
            .catch((err) => {
                if (cancelled) return
                const status = err?.response?.status
                const problem = status === 403 ? "forbidden" : status === 404 ? "missing" : "error"
                setResult({ id, mover: null, problem })
                if (problem === "error") setError(errorMessage(err, "Couldn't load this mover."))
            })
        return () => { cancelled = true }
    }, [id])

    const loading = result.id !== id
    const { mover, problem } = result

    return (
        <>
            <NavBar />
            <main className="mx-auto max-w-6xl px-4 pb-24 pt-8 sm:px-6 sm:pt-10">
                <Link to={backTo} className="mb-6 inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink">
                    <ArrowLeft size={15} /> All movers
                </Link>

                <Notice message={error} onDismiss={() => setError("")} />
                <Notice message={success} kind="success" onDismiss={() => setSuccess("")} />

                {loading && <div className="h-64 animate-pulse rounded-2xl border border-line bg-surface" aria-hidden="true" />}
                {!loading && problem === "forbidden" && <StaffOnly />}
                {!loading && problem === "missing" && (
                    <div className="rounded-2xl border border-dashed border-line-strong px-6 py-12 text-center text-sm text-ink-2">
                        This mover doesn't exist. It may have been removed.
                    </div>
                )}
                {!loading && mover && (
                    <MoverProfile
                        mover={mover}
                        onSaved={(updated) => {
                            setResult({ id, mover: updated, problem: null })
                            setSuccess(updated.is_bookable ? "Saved. This mover is now bookable." : "Saved.")
                        }}
                    />
                )}
            </main>
        </>
    )
}

function MoverProfile({ mover, onSaved }) {
    const address = [mover.street, [mover.city, mover.state].filter(Boolean).join(", "), mover.zip_code].filter(Boolean).join(" · ")
    return (
        <>
            <header className="mb-8">
                <p className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-accent-text">Mover</p>
                <h1 className="font-display text-4xl leading-[1.05] tracking-tight text-ink sm:text-5xl">{displayName(mover)}</h1>
                {mover.dba_name && <p className="mt-2 text-[0.9375rem] text-ink-2">{mover.name}</p>}
                <div className="mt-4 flex flex-wrap gap-1.5">
                    <StatusBadge status={mover.status} />
                    <ClaimedBadge claimed={mover.claimed} />
                    <UtcBadge status={mover.utc_status} />
                    {mover.fmcsa_authority_active !== null && <AuthorityBadge active={mover.fmcsa_authority_active} />}
                </div>
            </header>

            <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
                <div className="space-y-6">
                    <Card icon={Building2} title="Company">
                        <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
                            <Item label="Legal name">{mover.name}</Item>
                            <Item label="DBA name">{mover.dba_name || "-"}</Item>
                            <Item label="Address" wide>{address || "-"}</Item>
                            <Item label="Phone">{formatPhone(mover.phone)}</Item>
                            <Item label="USDOT number">
                                {mover.usdot_number ? (
                                    <ExternalItem href={saferUrl(mover.usdot_number)} label="opens FMCSA's SAFER company snapshot">{mover.usdot_number}</ExternalItem>
                                ) : "None on record"}
                            </Item>
                            <Item label="MC number">{mover.mc_number ? `MC ${mover.mc_number}` : "-"}</Item>
                        </dl>
                    </Card>

                    <Card icon={Landmark} title="Washington UTC" description="From the UTC's regulated companies list. This is what in-state moves depend on.">
                        <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
                            <Item label="UTC status"><UtcBadge status={mover.utc_status} /></Item>
                            <Item label="UTC permit number">{mover.utc_permit_number || "-"}</Item>
                            <Item label="UTC company page">
                                {mover.utc_company_id ? (
                                    <ExternalItem href={utcCompanyUrl(mover.utc_company_id)} label="opens the company's page on utc.wa.gov">UTC {mover.utc_company_id}</ExternalItem>
                                ) : "Not linked"}
                            </Item>
                            <Item label="Last synced">{formatDateTime(mover.utc_synced_at)}</Item>
                        </dl>
                    </Card>

                    <Card icon={DatabaseZap} title="Federal data" description="From FMCSA's “Carrier – All With History” dataset (interstate authority).">
                        <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
                            <Item label="Household goods authority"><AuthorityBadge active={mover.fmcsa_authority_active} /></Item>
                            <Item label="Last synced">{formatDateTime(mover.fmcsa_synced_at)}</Item>
                        </dl>
                    </Card>

                    <Card icon={Building2} title="Profile">
                        <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
                            <Item label="Added from">{SOURCE_LABELS[mover.source] ?? "-"}</Item>
                            <Item label="Google place">{mover.google_place_id ? "Linked" : "Not linked"}</Item>
                            <Item label="Profile created">{formatDateTime(mover.created_at)}</Item>
                            <Item label="Last updated">{formatDateTime(mover.updated_at)}</Item>
                        </dl>
                    </Card>
                </div>

                <aside className="lg:sticky lg:top-24">
                    <VerificationForm key={mover.updated_at} mover={mover} onSaved={onSaved} />
                </aside>
            </div>
        </>
    )
}

function VerificationForm({ mover, onSaved }) {
    const [permit, setPermit] = useState(mover.utc_permit_number ?? "")
    const [status, setStatus] = useState(mover.status)
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState("")

    const changed = permit.trim().toUpperCase() !== (mover.utc_permit_number ?? "") || status !== mover.status

    const save = async (e) => {
        e.preventDefault()
        setSaving(true)
        setError("")
        try {
            const res = await api.patch(`/api/movers/${mover.id}/`, { utc_permit_number: permit, status })
            onSaved(res.data)
        } catch (err) {
            setError(errorMessage(err, "Couldn't save."))
            setSaving(false)
        }
    }

    return (
        <form onSubmit={save} aria-label="Verification" className={`${cardClass} overflow-hidden`}>
            <div className="space-y-5 p-5 sm:p-6">
                <header className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-text">
                        <ShieldCheck size={15} />
                    </span>
                    <div>
                        <h2 className="text-[0.9375rem] font-semibold text-ink">Verification</h2>
                        <p className="text-xs text-ink-3">Check the permit with the UTC before verifying.</p>
                    </div>
                </header>

                <Field label="UTC permit number" htmlFor="utc-permit">
                    <input id="utc-permit" value={permit} onChange={(e) => setPermit(e.target.value)} placeholder="e.g. HG000000" autoComplete="off" className={`${inputClass} uppercase placeholder:normal-case`} />
                </Field>

                <Segmented label="Status" name="mover-status" value={status} options={STATUS_OPTIONS} onChange={setStatus} />

                <Bookable mover={mover} />
                {error && <p role="alert" className="text-sm text-danger">{error}</p>}
            </div>
            <div className="border-t border-line bg-subtle/50 p-4 sm:px-6">
                <button type="submit" disabled={saving || !changed} className={`${buttonClass.primary} w-full`}>
                    {saving ? "Saving…" : "Save"}
                </button>
            </div>
        </form>
    )
}

function Bookable({ mover }) {
    return mover.is_bookable ? (
        <p className="rounded-lg bg-success-soft px-3 py-2 text-sm text-success">Bookable: verified with a UTC permit.</p>
    ) : (
        <p className="rounded-lg bg-subtle px-3 py-2 text-sm text-ink-2">Not bookable yet. Customers can book a mover once it's verified with a UTC permit number.</p>
    )
}

function Card({ icon: Icon, title, description, children }) {
    return (
        <section className={`${cardClass} p-5 sm:p-6`}>
            <header className="mb-5 flex items-start gap-3">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-text">
                    <Icon size={15} />
                </span>
                <div>
                    <h2 className="text-[0.9375rem] font-semibold text-ink">{title}</h2>
                    {description && <p className="text-xs text-ink-3">{description}</p>}
                </div>
            </header>
            {children}
        </section>
    )
}

function ExternalItem({ href, label, children }) {
    return (
        <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent-text hover:underline underline-offset-4">
            {children}
            <ExternalLink size={13} aria-hidden="true" />
            <span className="sr-only">({label})</span>
        </a>
    )
}

function Item({ label, children, wide = false }) {
    return (
        <div className={wide ? "sm:col-span-2" : ""}>
            <dt className="text-[0.6875rem] font-semibold uppercase tracking-[0.08em] text-ink-3">{label}</dt>
            <dd className="mt-1 text-sm text-ink">{children}</dd>
        </div>
    )
}

export default MoverDetail
