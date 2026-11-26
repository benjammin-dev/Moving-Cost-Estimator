import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import MoverDetail from '../MoverDetail'
import api from '../../api'

vi.mock('../../api', () => ({
  default: { get: vi.fn(), patch: vi.fn() },
}))

const MOVER = {
  id: 7, name: 'HANSEN BROS TRANSFER & STORAGE CO., INC.', dba_name: 'HANSEN MOVERS', usdot_number: 8257, mc_number: '59073',
  street: '1 MAIN ST', city: 'SEATTLE', state: 'WA', zip_code: '98133-8883', phone: '2065550100',
  utc_permit_number: null, status: 'unverified', claimed: false, google_place_id: null,
  fmcsa_authority_active: true, fmcsa_synced_at: '2026-11-25T18:00:00Z', is_bookable: false,
  source: 'fmcsa', utc_company_id: null, utc_status: '', utc_synced_at: null,
  created_at: '2026-11-25T18:00:00Z', updated_at: '2026-11-25T18:00:00Z',
}

const UTC_MOVER = {
  ...MOVER, id: 8, name: 'A Aaron Glide Self Mover Service', dba_name: '', usdot_number: null, mc_number: '',
  source: 'utc', utc_company_id: 44654, utc_status: 'Unregulated', utc_synced_at: '2026-11-25T19:00:00Z',
  fmcsa_authority_active: null, fmcsa_synced_at: null, status: 'inactive',
}

function renderPage(mover = MOVER, state) {
  api.get.mockImplementation((url) => {
    if (url === '/api/user/me/') return Promise.resolve({ data: { username: 'benja', is_staff: true } })
    if (url === `/api/movers/${mover.id}/`) return Promise.resolve({ data: mover })
    return Promise.reject({ response: { status: 404, data: { detail: 'No Mover matches the given query.' } } })
  })
  return render(
    <MemoryRouter initialEntries={[{ pathname: `/movers/${mover.id}`, state }]}>
      <Routes>
        <Route path="/movers/:id" element={<MoverDetail />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('MoverDetail page', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows the profile and links the USDOT number to FMCSA', async () => {
    renderPage()
    expect(await screen.findByRole('heading', { name: 'HANSEN MOVERS', level: 1 })).toBeInTheDocument()
    expect(screen.getAllByText('HANSEN BROS TRANSFER & STORAGE CO., INC.').length).toBeGreaterThan(0)
    expect(screen.getByText('(206) 555-0100')).toBeInTheDocument()
    expect(screen.getByText('MC 59073')).toBeInTheDocument()
    const safer = screen.getByRole('link', { name: /8257/ })
    expect(safer).toHaveAttribute('href', expect.stringContaining('safer.fmcsa.dot.gov'))
    expect(safer).toHaveAttribute('href', expect.stringContaining('query_string=8257'))
    expect(safer).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByText(/Not bookable yet/)).toBeInTheDocument()
  })

  it('shows UTC details and handles a mover with no USDOT number', async () => {
    renderPage(UTC_MOVER)
    expect(await screen.findByRole('heading', { name: 'A Aaron Glide Self Mover Service', level: 1 })).toBeInTheDocument()
    expect(screen.getByText('None on record')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /SAFER/ })).not.toBeInTheDocument()
    expect(screen.getAllByText('UTC: Unregulated').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /UTC 44654/ })).toHaveAttribute('href', 'https://www.utc.wa.gov/company/44654')
    expect(screen.getByText('Washington UTC import')).toBeInTheDocument()
  })

  it('confirms a mover that was just added', async () => {
    renderPage(MOVER, { created: true })
    expect(await screen.findByText("Mover added. Verify it once you've checked its UTC permit.")).toBeInTheDocument()
  })

  it('links back to the list with the filters it came from', async () => {
    renderPage(MOVER, { from: '?status=unverified' })
    await screen.findByRole('heading', { level: 1 })
    expect(screen.getByRole('link', { name: /All movers/ })).toHaveAttribute('href', '/movers?status=unverified')
  })

  it('verifies a mover with a permit number', async () => {
    api.patch.mockResolvedValue({ data: { ...MOVER, utc_permit_number: 'HG068043', status: 'verified', is_bookable: true, updated_at: '2026-11-25T19:00:00Z' } })
    renderPage()
    await screen.findByRole('heading', { level: 1 })
    const save = screen.getByRole('button', { name: 'Save' })
    expect(save).toBeDisabled() // nothing changed yet

    fireEvent.change(screen.getByLabelText('UTC permit number'), { target: { value: 'hg068043' } })
    fireEvent.click(screen.getByRole('radio', { name: 'Verified' }))
    fireEvent.click(save)

    expect(api.patch).toHaveBeenCalledWith('/api/movers/7/', { utc_permit_number: 'hg068043', status: 'verified' })
    expect(await screen.findByText('Saved. This mover is now bookable.')).toBeInTheDocument()
    expect(screen.getByText(/Bookable: verified with a UTC permit/)).toBeInTheDocument()
    expect(screen.getByLabelText('UTC permit number')).toHaveValue('HG068043')
  })

  it('shows the reason a save was refused', async () => {
    api.patch.mockRejectedValue({ response: { status: 400, data: { status: ["Add the mover's UTC permit number before verifying it."] } } })
    renderPage()
    await screen.findByRole('heading', { level: 1 })
    fireEvent.click(screen.getByRole('radio', { name: 'Verified' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("Add the mover's UTC permit number before verifying it.")
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
  })

  it('says when a mover does not exist', async () => {
    api.get.mockImplementation((url) =>
      url === '/api/user/me/'
        ? Promise.resolve({ data: { is_staff: true } })
        : Promise.reject({ response: { status: 404, data: {} } })
    )
    render(
      <MemoryRouter initialEntries={['/movers/999']}>
        <Routes><Route path="/movers/:id" element={<MoverDetail />} /></Routes>
      </MemoryRouter>
    )
    expect(await screen.findByText(/This mover doesn't exist/)).toBeInTheDocument()
  })

  it('tells non-staff accounts the page is staff only', async () => {
    api.get.mockRejectedValue({ response: { status: 403, data: {} } })
    render(
      <MemoryRouter initialEntries={['/movers/7']}>
        <Routes><Route path="/movers/:id" element={<MoverDetail />} /></Routes>
      </MemoryRouter>
    )
    expect(await screen.findByText('Staff only')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
  })
})
