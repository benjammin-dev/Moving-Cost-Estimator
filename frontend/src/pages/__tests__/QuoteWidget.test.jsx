import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
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
