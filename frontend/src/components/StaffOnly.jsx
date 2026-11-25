import { Lock } from "lucide-react"
import { cardClass } from "../ui"

// Shown when a signed-in account without staff access opens a staff page.
function StaffOnly() {
    return (
        <div className={`${cardClass} mx-auto max-w-md p-8 text-center`}>
            <span className="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-subtle text-ink-3">
                <Lock size={18} />
            </span>
            <h2 className="text-base font-semibold text-ink">Staff only</h2>
            <p className="mt-1.5 text-sm text-ink-2">
                The movers directory is only available to staff accounts. Ask an administrator to give your account staff access.
            </p>
        </div>
    )
}

export default StaffOnly
