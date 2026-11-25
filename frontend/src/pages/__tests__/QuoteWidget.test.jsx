import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import QuoteWidget from '../QuoteWidget'
import api from '../../api'

vi.mock('../../api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

const OPTIONS = {
  parking: [{ value: 'driveway', label: 'Driveway / at the door' }],
  packing: [{ value: 'none', label: 'No packing' }],
  special_items: [{ value: 'upright_piano', label: 'Upright piano', fee: 150, minutes: 30 }],
}

const BREAKDOWN = {
  weight: 7000, weight_source: 'entered', crew: 3, crew_source: 'recommended for weight',
  hours: [{ label: 'Loading', hours: 2.33, detail: 'standard access' }],
  total_hours: 4.7, billable_hours: 4.75, minimum_applied: false, hourly_rate: 250,
  costs: [{ label: 'Labor', amount: 1187.5 }], total: 1287.5, low: 1158.75, high: 1416.25,
}

function renderWidget() {
  return render(
    <MemoryRouter>
      <QuoteWidget />
    </MemoryRouter>
  )
}

describe('QuoteWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockResolvedValue({ data: OPTIONS })
    api.post.mockResolvedValue({ data: BREAKDOWN })
  })

  it('shows a live quote without logging in', async () => {
    renderWidget()
    fireEvent.change(screen.getByLabelText('Square footage'), { target: { value: '1000' } })

    expect(await screen.findByTestId('live-quote', {}, { timeout: 2000 })).toHaveTextContent('1,287.50')
    expect(api.post).toHaveBeenCalledWith('/api/estimates/preview/', expect.objectContaining({ square_footage: 1000 }))
  })

  it('has no customer fields or save button, and never saves', async () => {
    renderWidget()
    await waitFor(() => expect(screen.getByText('Upright piano')).toBeInTheDocument())

    expect(screen.queryByLabelText('Customer name')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /save/i })).not.toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalledWith('/api/estimates/', expect.anything())
    expect(api.get).not.toHaveBeenCalledWith(expect.stringMatching(/^\/api\/estimates/))
  })
})

describe('QuoteWidget inside an iframe', () => {
  let parentPostMessage
  let observerCallback
  let height

  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockResolvedValue({ data: OPTIONS })
    api.post.mockResolvedValue({ data: BREAKDOWN })
    height = 900
    parentPostMessage = vi.fn()
    vi.spyOn(window, 'parent', 'get').mockReturnValue({ postMessage: parentPostMessage })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(() => ({ height }))
    vi.stubGlobal('ResizeObserver', class {
      constructor(cb) { observerCallback = cb }
      observe() {}
      disconnect() {}
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('reports its height to the parent page, and again when it changes', async () => {
    renderWidget()
    expect(parentPostMessage).toHaveBeenCalledWith({ type: 'moving-quote:resize', height: 900 }, '*')

    height = 1250.4
    act(() => observerCallback())
    expect(parentPostMessage).toHaveBeenLastCalledWith({ type: 'moving-quote:resize', height: 1251 }, '*')

    // Unchanged height: no extra message.
    act(() => observerCallback())
    expect(parentPostMessage).toHaveBeenCalledTimes(2)
  })
})

describe('QuoteWidget outside an iframe', () => {
  it('does not post its height', () => {
    vi.clearAllMocks()
    api.get.mockResolvedValue({ data: OPTIONS })
    const spy = vi.spyOn(window, 'postMessage')
    renderWidget()
    expect(spy).not.toHaveBeenCalled()
    spy.mockRestore()
  })
})
