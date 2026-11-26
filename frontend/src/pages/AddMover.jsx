import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { ArrowLeft, Building2 } from "lucide-react"
import api from "../api"
import NavBar from "../components/NavBar"
import PageHeader from "../components/PageHeader"
import StaffOnly from "../components/StaffOnly"
import { Field } from "../components/controls"
import { buttonClass, cardClass, errorMessage, inputClass } from "../ui"

const EMPTY = { name: "", dba_name: "", usdot_number: "", mc_number: "", street: "", city: "", state: "WA", zip_code: "", phone: "" }

// Staff form for adding a mover that isn't in the FMCSA or UTC data.
function AddMover() {
    const navigate = useNavigate()
    const [form, setForm] = useState(EMPTY)
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState("")
    const [forbidden, setForbidden] = useState(false)

    const onChange = (e) => setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }))

    const submit = async (e) => {
        e.preventDefault()
        setSaving(true)
        setError("")
        const payload = { ...form, usdot_number: form.usdot_number.trim() === "" ? null : Number(form.usdot_number) }
        try {
            const res = await api.post("/api/movers/", payload)
            navigate(`/movers/${res.data.id}`, { state: { created: true } })
        } catch (err) {
            if (err?.response?.status === 403) setForbidden(true)
            else setError(errorMessage(err, "Couldn't add the mover."))
            setSaving(false)
        }
    }

    const input = (name, props = {}) => (
        <input id={`add-${name}`} name={name} value={form[name]} onChange={onChange} className={inputClass} autoComplete="off" {...props} />
    )

    return (
        <>
            <NavBar />
            <main className="mx-auto max-w-3xl px-4 pb-24 pt-8 sm:px-6 sm:pt-10">
                <Link to="/movers" className="mb-6 inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink">
                    <ArrowLeft size={15} /> All movers
                </Link>
                <PageHeader
                    eyebrow="Staff"
                    title="Add a mover"
                    description="For a moving company that isn't in the FMCSA or UTC data. It starts unverified. Verify it on its page once you've checked its UTC permit."
                />

                {forbidden ? (
                    <StaffOnly />
                ) : (
                    <form onSubmit={submit} aria-label="Add a mover" className={`${cardClass} overflow-hidden`}>
                        <div className="space-y-6 p-5 sm:p-6">
                            <header className="flex items-start gap-3">
                                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-text">
                                    <Building2 size={15} />
                                </span>
                                <h2 className="text-[0.9375rem] font-semibold text-ink">Company</h2>
                            </header>

                            <div className="grid gap-4 sm:grid-cols-2">
                                <Field label="Company name" htmlFor="add-name">{input("name", { required: true, placeholder: "Legal or trading name" })}</Field>
                                <Field label="DBA name" htmlFor="add-dba_name" hint="Optional">{input("dba_name")}</Field>
                                <Field label="USDOT number" htmlFor="add-usdot_number" hint="Optional. Many local movers don't have one.">
                                    {input("usdot_number", { inputMode: "numeric", pattern: "[0-9]*" })}
                                </Field>
                                <Field label="MC number" htmlFor="add-mc_number" hint="Optional">{input("mc_number", { placeholder: "e.g. 123456" })}</Field>
                            </div>

                            <div className="grid gap-4 sm:grid-cols-6">
                                <Field label="Street address" htmlFor="add-street" className="sm:col-span-6">{input("street")}</Field>
                                <Field label="City" htmlFor="add-city" className="sm:col-span-3">{input("city")}</Field>
                                <Field label="State" htmlFor="add-state" className="sm:col-span-1">{input("state", { maxLength: 2, className: `${inputClass} uppercase` })}</Field>
                                <Field label="ZIP" htmlFor="add-zip_code" className="sm:col-span-2">{input("zip_code", { inputMode: "numeric" })}</Field>
                                <Field label="Business phone" htmlFor="add-phone" className="sm:col-span-3">{input("phone", { type: "tel" })}</Field>
                            </div>

                            {error && <p role="alert" className="text-sm text-danger">{error}</p>}
                        </div>
                        <div className="flex flex-col-reverse gap-2 border-t border-line bg-subtle/50 p-4 sm:flex-row sm:justify-end sm:px-6">
                            <Link to="/movers" className={buttonClass.ghost}>Cancel</Link>
                            <button type="submit" disabled={saving} className={buttonClass.primary}>
                                {saving ? "Adding…" : "Add mover"}
                            </button>
                        </div>
                    </form>
                )}
            </main>
        </>
    )
}

export default AddMover
