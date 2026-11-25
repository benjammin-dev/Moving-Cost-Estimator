import { useEffect, useState } from "react"
import api from "./api"
import { errorMessage } from "./ui"

// Choice lists (parking, packing, special items) defined in the backend's
// pricing.py, so labels and items only live in one place.
export function usePricingOptions(onError) {
    const [options, setOptions] = useState(null)
    useEffect(() => {
        api.get("/api/pricing/options/")
            .then((res) => setOptions(res.data))
            .catch((err) => onError?.(errorMessage(err, "Couldn't load pricing options.")))
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])
    return options
}

// Loads estimates with the given status ("open" or "completed") and gives
// helpers to keep the list in sync as cards change.
export function useEstimates(status, onError) {
    const [estimates, setEstimates] = useState([])
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        api.get(`/api/estimates/?status=${status}`)
            .then((res) => setEstimates(res.data))
            .catch((err) => onError?.(errorMessage(err, "Couldn't load estimates.")))
            .finally(() => setLoading(false))
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [status])

    const belongsHere = (est) => (status === "completed" ? Boolean(est.completion) : !est.completion)

    const replace = (updated) =>
        setEstimates((prev) =>
            belongsHere(updated)
                ? prev.map((e) => (e.id === updated.id ? updated : e))
                : prev.filter((e) => e.id !== updated.id)
        )
    const remove = (id) => setEstimates((prev) => prev.filter((e) => e.id !== id))
    const add = (est) => setEstimates((prev) => [est, ...prev])

    return { estimates, loading, replace, remove, add }
}

// Message the widget sends to the page embedding it. public/embed.js
// listens for it, so keep the two in sync.
export const RESIZE_MESSAGE = "moving-quote:resize"

// When this page is shown inside an <iframe>, tell the parent page how tall
// `ref`'s element is whenever it changes, so embed.js can size the iframe to
// fit. Measure a content wrapper, not the document: body has min-height:
// 100vh, so the document would never report a height smaller than the frame.
export function useReportHeight(ref) {
    useEffect(() => {
        const el = ref.current
        if (!el || window.parent === window || typeof ResizeObserver === "undefined") return
        let last = 0
        const report = () => {
            const height = Math.ceil(el.getBoundingClientRect().height)
            if (!height || height === last) return
            last = height
            // Only a height is sent, nothing private, so any parent origin is fine.
            window.parent.postMessage({ type: RESIZE_MESSAGE, height }, "*")
        }
        const observer = new ResizeObserver(report)
        observer.observe(el)
        report()
        return () => observer.disconnect()
    }, [ref])
}
