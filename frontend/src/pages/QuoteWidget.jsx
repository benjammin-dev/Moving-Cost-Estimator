import { useRef, useState } from "react"
import EstimateForm from "../components/EstimateForm"
import Notice from "../components/Notice"
import { usePricingOptions, useReportHeight } from "../hooks"

// Public quote widget: anyone can price a move without an account. It only
// calls the public preview and pricing-options endpoints and never saves.
// No nav bar, so it fits inside an <iframe> on another site. When embedded,
// it reports its height so public/embed.js can resize the iframe to fit.
function QuoteWidget() {
    const [error, setError] = useState("")
    const options = usePricingOptions(setError)
    const mainRef = useRef(null)
    useReportHeight(mainRef)

    return (
        <main ref={mainRef} className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
            <header className="mb-6">
                <h1 className="font-display text-3xl leading-tight tracking-tight text-ink sm:text-4xl">Get a moving quote</h1>
                <p className="mt-2 max-w-xl text-[0.9375rem] text-ink-2">
                    Describe your move and see an estimate instantly. No account needed.
                </p>
            </header>
            <Notice message={error} onDismiss={() => setError("")} />
            <EstimateForm layout="split" options={options} quoteOnly />
        </main>
    )
}

export default QuoteWidget
