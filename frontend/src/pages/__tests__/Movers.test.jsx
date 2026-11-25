import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import Movers from '../Movers'
import api from '../../api'

vi.mock('../../api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}))

const mover = (id, name, overrides = {}) => ({
  id, name, dba_name: '', usdot_number: 8000 + id, mc_number: String(50000 + id),
  street: '1 MAIN ST', city: 'SEATTLE', state: 'WA', zip_code: '98101', phone: '2065550100',
  utc_permit_number: null, status: 'unverified', claimed: false, google_place_id: null,
  fmcsa_authority_active: true, fmcsa_synced_at: '2026-11-25T18:00:00Z', is_bookable: false,
  created_at: '2026-11-25T18:00:00Z', updated_at: '2026-11-25T18:00:00Z', ...overrides,
})

const RUN = {
  id: 1, started_at: '2026-11-25T18:00:00Z', finished_at: '2026-11-25T18:00:05Z', state: 'WA',
  source: 'FMCSA', dry_run: false, triggered_by: 'benja', succeeded: true, error: '',
  stats: { records: 1345, carriers: 951, created: 196, updated: 0, inactive_skipped: 755, forwarders_skipped: 48, conflicts: 0, deactivated: 0 },
  messages: [],
}

const SUMMARY = {
  counts: { total: 2, unverified: 1, verified: 1, inactive: 0, claimed: 1, bookable: 1 },
  latest_import: RUN,
}

function mockApi({ summary = SUMMARY, list = [mover(1, 'HANSEN BROS'), mover(2, 'TACOMA MOVING', { dba_name: 'TACOMA MOVERS', status: 'verified', claimed: true })] } = {}) {
  api.get.mockImplementation((url) => {
    if (url === '/api/user/me/') return Promise.resolve({ data: { username: 'benja', is_staff: true } })
    if (url === '/api/movers/summary/') return Promise.resolve({ data: summary })
    if (url.startsWith('/api/movers/')) return Promise.resolve({ data: { count: list.length, results: list } })
    return Promise.reject(new Error(`unexpected ${url}`))
  })
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}{location.search}</div>
}

function renderPage(path = '/movers') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/movers" element={<><Movers /><LocationProbe /></>} />
        <Route path="/movers/:id" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>
  )
}

const listCalls = () => api.get.mock.calls.map(([url]) => url).filter((url) => url.startsWith('/api/movers/') && !url.includes('summary'))

describe('Movers page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApi()
  })

  it('shows counts, the latest import and the movers', async () => {
    renderPage()
    const table = await screen.findByRole('table')
    expect(within(table).getByRole('link', { name: 'HANSEN BROS' })).toHaveAttribute('href', '/movers/1')
    // The DBA name is shown first, with the legal name under it.
    expect(within(table).getByRole('link', { name: 'TACOMA MOVERS' })).toBeInTheDocument()
    expect(within(table).getByText('TACOMA MOVING')).toBeInTheDocument()

    const counts = screen.getByRole('region', { name: 'Mover counts' })
    expect(within(counts).getByText('Bookable')).toBeInTheDocument()
    expect(within(counts).getByText('1 claimed')).toBeInTheDocument()

    expect(screen.getByTestId('latest-import')).toHaveTextContent('196 new · 0 updated · 755 without active authority · 48 freight forwarders skipped')
    expect(screen.getByTestId('latest-import')).toHaveTextContent('by benja')
  })

  it('filters by status and keeps filters in the URL', async () => {
    renderPage()
    await screen.findByRole('table')
    fireEvent.click(screen.getByRole('radio', { name: 'Verified' }))
    await waitFor(() => expect(listCalls()).toContain('/api/movers/?status=verified'))
    expect(screen.getByTestId('location')).toHaveTextContent('/movers?status=verified')
  })

  it('searches after typing stops', async () => {
    renderPage()
    await screen.findByRole('table')
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search movers' }), { target: { value: 'hansen' } })
    await waitFor(() => expect(listCalls()).toContain('/api/movers/?search=hansen'), { timeout: 2000 })
  })

  it('reads filters from the URL', async () => {
    renderPage('/movers?claimed=false&page=2')
    await screen.findByRole('table')
    expect(listCalls()[0]).toBe('/api/movers/?claimed=false&page=2')
    expect(screen.getByRole('combobox', { name: 'Claimed' })).toHaveValue('false')
  })

  it('pages through results', async () => {
    mockApi({ list: Array.from({ length: 25 }, (_, i) => mover(i + 1, `MOVER ${i + 1}`)) })
    api.get.mockImplementation((url) => {
      if (url === '/api/movers/summary/') return Promise.resolve({ data: SUMMARY })
      if (url.startsWith('/api/movers/')) return Promise.resolve({ data: { count: 60, results: Array.from({ length: 25 }, (_, i) => mover(i + 1, `MOVER ${i + 1}`)) } })
      return Promise.resolve({ data: {} })
    })
    renderPage()
    expect(await screen.findByText('1–25 of 60')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Previous/ })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: /Next/ }))
    await waitFor(() => expect(listCalls()).toContain('/api/movers/?page=2'))
  })

  it('previews an import by default, then refreshes', async () => {
    api.post.mockResolvedValue({ data: { ...RUN, id: 2, dry_run: true } })
    renderPage()
    await screen.findByRole('table')
    const summaryCalls = () => api.get.mock.calls.filter(([url]) => url === '/api/movers/summary/').length
    expect(summaryCalls()).toBe(1)

    fireEvent.click(screen.getByRole('button', { name: 'Preview import' }))
    expect(api.post).toHaveBeenCalledWith('/api/movers/imports/', { dry_run: true })
    expect(await screen.findByText(/Preview finished, nothing saved: 196 new/)).toBeInTheDocument()
    await waitFor(() => expect(summaryCalls()).toBe(2))
  })

  it('runs a real import when preview is turned off', async () => {
    api.post.mockResolvedValue({ data: { ...RUN, id: 2 } })
    renderPage()
    await screen.findByRole('table')
    fireEvent.click(screen.getByRole('checkbox', { name: /Preview only/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Run import' }))
    expect(api.post).toHaveBeenCalledWith('/api/movers/imports/', { dry_run: false })
    expect(await screen.findByText(/Import finished: 196 new/)).toBeInTheDocument()
  })

  it('shows why an import failed', async () => {
    api.post.mockRejectedValue({ response: { status: 502, data: { detail: "The import couldn't reach FMCSA (HTTP 503)." } } })
    renderPage()
    await screen.findByRole('table')
    fireEvent.click(screen.getByRole('button', { name: 'Preview import' }))
    expect(await screen.findByText("The import couldn't reach FMCSA (HTTP 503).")).toBeInTheDocument()
  })

  it('explains how to get movers when there are none', async () => {
    mockApi({ summary: { counts: { total: 0, unverified: 0, verified: 0, inactive: 0, claimed: 0, bookable: 0 }, latest_import: null }, list: [] })
    renderPage()
    expect(await screen.findByText(/No movers yet/)).toBeInTheDocument()
    expect(screen.getByText('No imports yet.')).toBeInTheDocument()
  })

  it('offers to clear filters when nothing matches', async () => {
    mockApi({ list: [] })
    renderPage('/movers?search=zzz')
    expect(await screen.findByText('No movers match these filters.')).toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: 'Search movers' })).toHaveValue('zzz')
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(/^\/movers$/))
    expect(screen.getByRole('searchbox', { name: 'Search movers' })).toHaveValue('')
  })

  it('tells non-staff accounts the page is staff only', async () => {
    api.get.mockRejectedValue({ response: { status: 403, data: { detail: 'You do not have permission to perform this action.' } } })
    renderPage()
    expect(await screen.findByText('Staff only')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /import/i })).not.toBeInTheDocument()
  })
})
