import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within, act } from '@testing-library/react'
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
  id: 1, kind: 'fmcsa', started_at: '2026-11-25T18:00:00Z', finished_at: '2026-11-25T18:00:05Z', state: 'WA',
  source: 'FMCSA', dry_run: false, triggered_by: 'benja', succeeded: true, error: '',
  stats: { records: 1345, carriers: 951, created: 196, updated: 0, inactive_skipped: 755, forwarders_skipped: 48, conflicts: 0, deactivated: 0 },
  messages: [],
}

const UTC_RUN = {
  id: 5, kind: 'utc', started_at: '2026-11-25T19:00:00Z', finished_at: '2026-11-25T19:12:00Z', state: 'WA',
  source: 'UTC', dry_run: false, triggered_by: 'benja', succeeded: true, error: '',
  stats: { listed: 1522, companies: 741, created: 597, updated: 144, verified: 270, deactivated: 0, inactive_skipped: 770, duplicates_skipped: 12, details_read: 700, conflicts: 0, errors: 0 },
  messages: ['UTC 1 (X): something to review'],
}

const SUMMARY = {
  counts: { total: 2, unverified: 1, verified: 1, inactive: 0, claimed: 1, bookable: 1, utc_active: 1 },
  latest_imports: { fmcsa: RUN, utc: UTC_RUN },
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

    expect(within(counts).getByText('UTC permitted')).toBeInTheDocument()

    expect(screen.getByTestId('fmcsa-latest')).toHaveTextContent('196 new · 0 updated · 755 without active authority · 48 freight forwarders skipped')
    expect(screen.getByTestId('fmcsa-latest')).toHaveTextContent('by benja')
    expect(screen.getByTestId('utc-latest')).toHaveTextContent('597 new · 144 updated · 270 verified with a UTC permit · 12 duplicate listings skipped')
    expect(screen.getByText('1 message to review')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Add mover/ })).toHaveAttribute('href', '/movers/new')
  })

  it('shows UTC permit status for each mover, and movers without a USDOT number', async () => {
    mockApi({ list: [mover(1, 'PERMITTED CO', { utc_status: 'Active' }), mover(2, 'LOCAL CO', { usdot_number: null, utc_status: 'Unregulated', fmcsa_authority_active: null })] })
    renderPage()
    const table = await screen.findByRole('table')
    expect(within(table).getByText('UTC permit active')).toBeInTheDocument()
    expect(within(table).getByText('UTC: Unregulated')).toBeInTheDocument()
    expect(within(table).getByText('No USDOT')).toBeInTheDocument()
    expect(within(table).getAllByText(/Authority/)).toHaveLength(1)  // no FMCSA badge for the local mover
  })

  it('filters by UTC permit status', async () => {
    renderPage()
    await screen.findByRole('table')
    fireEvent.change(screen.getByRole('combobox', { name: 'UTC permit' }), { target: { value: 'active' } })
    await waitFor(() => expect(listCalls()).toContain('/api/movers/?utc=active'))
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

  describe('imports', () => {
    afterEach(() => vi.useRealTimers())

    // Summary responses in order; the last one repeats.
    function summaries(...list) {
      let i = 0
      api.get.mockImplementation((url) => {
        if (url === '/api/movers/summary/') return Promise.resolve({ data: list[Math.min(i++, list.length - 1)] })
        if (url === '/api/user/me/') return Promise.resolve({ data: { username: 'benja', is_staff: true } })
        return Promise.resolve({ data: { count: 1, results: [mover(1, 'HANSEN BROS')] } })
      })
    }
    const utcPanel = () => screen.getByRole('region', { name: 'Washington UTC import' })
    const summaryCalls = () => api.get.mock.calls.filter(([url]) => url === '/api/movers/summary/').length

    it('starts a UTC preview by default, shows it running, then reports and refreshes', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      const running = { ...UTC_RUN, id: 9, dry_run: true, finished_at: null, stats: {} }
      const done = { ...running, finished_at: '2026-11-25T19:01:00Z', stats: UTC_RUN.stats, messages: [] }
      summaries(SUMMARY, { ...SUMMARY, latest_imports: { ...SUMMARY.latest_imports, utc: running } }, { ...SUMMARY, latest_imports: { ...SUMMARY.latest_imports, utc: done } })
      api.post.mockResolvedValue({ data: running })
      renderPage()
      await screen.findByRole('table')

      fireEvent.click(within(utcPanel()).getByRole('button', { name: 'Preview import' }))
      expect(api.post).toHaveBeenCalledWith('/api/movers/imports/', { kind: 'utc', dry_run: true })
      expect(await within(utcPanel()).findByText(/Preview running/)).toBeInTheDocument()
      expect(within(utcPanel()).getByRole('button', { name: 'Running…' })).toBeDisabled()

      const listCallsBefore = listCalls().length
      await act(() => vi.advanceTimersByTimeAsync(3000))
      expect(await screen.findByText(/UTC preview finished, nothing saved: 597 new/)).toBeInTheDocument()
      await waitFor(() => expect(listCalls().length).toBeGreaterThan(listCallsBefore))
      // Stops checking once nothing is running.
      const calls = summaryCalls()
      await act(() => vi.advanceTimersByTimeAsync(9000))
      expect(summaryCalls()).toBe(calls)
    })

    it('runs a real FMCSA import when preview is turned off', async () => {
      summaries(SUMMARY)
      api.post.mockResolvedValue({ data: { ...RUN, id: 2, finished_at: null } })
      renderPage()
      await screen.findByRole('table')
      const panel = screen.getByRole('region', { name: 'FMCSA import' })
      fireEvent.click(within(panel).getByRole('checkbox', { name: /Preview only/ }))
      fireEvent.click(within(panel).getByRole('button', { name: 'Run import' }))
      expect(api.post).toHaveBeenCalledWith('/api/movers/imports/', { kind: 'fmcsa', dry_run: false })
    })

    it('reports a run that failed', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      const running = { ...UTC_RUN, id: 9, finished_at: null }
      const failed = { ...running, finished_at: '2026-11-25T19:01:00Z', succeeded: false, error: 'UTC list download failed: HTTP 503', messages: [] }
      summaries({ ...SUMMARY, latest_imports: { ...SUMMARY.latest_imports, utc: running } }, { ...SUMMARY, latest_imports: { ...SUMMARY.latest_imports, utc: failed } })
      renderPage()
      await screen.findByRole('table')
      await act(() => vi.advanceTimersByTimeAsync(3000))
      expect(await screen.findByText('UTC import failed: UTC list download failed: HTTP 503')).toBeInTheDocument()
      expect(within(utcPanel()).getByText('Failed: UTC list download failed: HTTP 503')).toBeInTheDocument()
    })

    it('says when an import is already running', async () => {
      summaries(SUMMARY)
      api.post.mockRejectedValue({ response: { status: 409, data: { detail: 'That import is already running. Wait for it to finish.' } } })
      renderPage()
      await screen.findByRole('table')
      fireEvent.click(within(utcPanel()).getByRole('button', { name: 'Preview import' }))
      expect(await within(utcPanel()).findByRole('alert')).toHaveTextContent('That import is already running.')
    })
  })

  it('explains how to get movers when there are none', async () => {
    mockApi({ summary: { counts: { total: 0, unverified: 0, verified: 0, inactive: 0, claimed: 0, bookable: 0, utc_active: 0 }, latest_imports: { fmcsa: null, utc: null } }, list: [] })
    renderPage()
    expect(await screen.findByText(/No movers yet/)).toBeInTheDocument()
    expect(screen.getAllByText('No imports yet.')).toHaveLength(2)
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
    expect(screen.queryByRole('link', { name: /Add mover/ })).not.toBeInTheDocument()
  })
})
