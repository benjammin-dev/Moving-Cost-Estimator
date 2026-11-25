import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import AddMover from '../AddMover'
import api from '../../api'

vi.mock('../../api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

function Landing() {
  const location = useLocation()
  return <div data-testid="landed">{location.pathname} {JSON.stringify(location.state)}</div>
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/movers/new']}>
      <Routes>
        <Route path="/movers/new" element={<AddMover />} />
        <Route path="/movers/:id" element={<Landing />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('AddMover page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockResolvedValue({ data: { username: 'benja', is_staff: true } })
  })

  it('adds a mover and opens its page', async () => {
    api.post.mockResolvedValue({ data: { id: 42 } })
    renderPage()
    fireEvent.change(screen.getByLabelText('Company name'), { target: { value: 'Aaron Glide Moving' } })
    fireEvent.change(screen.getByLabelText('City'), { target: { value: 'Seattle' } })
    fireEvent.change(screen.getByLabelText('Business phone'), { target: { value: '425-745-9047' } })
    expect(screen.getByLabelText('State')).toHaveValue('WA')
    fireEvent.click(screen.getByRole('button', { name: 'Add mover' }))

    expect(api.post).toHaveBeenCalledWith('/api/movers/', expect.objectContaining({
      name: 'Aaron Glide Moving', city: 'Seattle', phone: '425-745-9047', state: 'WA', usdot_number: null,
    }))
    expect(await screen.findByTestId('landed')).toHaveTextContent('/movers/42 {"created":true}')
  })

  it('sends the USDOT number as a number', async () => {
    api.post.mockResolvedValue({ data: { id: 1 } })
    renderPage()
    fireEvent.change(screen.getByLabelText('Company name'), { target: { value: 'X' } })
    fireEvent.change(screen.getByLabelText('USDOT number'), { target: { value: '373544' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add mover' }))
    expect(api.post).toHaveBeenCalledWith('/api/movers/', expect.objectContaining({ usdot_number: 373544 }))
  })

  it('shows why it was refused', async () => {
    api.post.mockRejectedValue({ response: { status: 400, data: { usdot_number: ['Another mover already has this USDOT number.'] } } })
    renderPage()
    fireEvent.change(screen.getByLabelText('Company name'), { target: { value: 'Dup' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add mover' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('usdot number: Another mover already has this USDOT number.')
    expect(screen.getByRole('button', { name: 'Add mover' })).toBeEnabled()
  })

  it('tells non-staff accounts the page is staff only', async () => {
    api.post.mockRejectedValue({ response: { status: 403, data: {} } })
    renderPage()
    fireEvent.change(screen.getByLabelText('Company name'), { target: { value: 'X' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add mover' }))
    expect(await screen.findByText('Staff only')).toBeInTheDocument()
  })
})
