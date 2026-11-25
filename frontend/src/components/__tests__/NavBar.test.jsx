import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import NavBar from '../NavBar'
import api from '../../api'

vi.mock('../../api', () => ({ default: { get: vi.fn() } }))

const renderNav = () => render(<MemoryRouter><NavBar /></MemoryRouter>)

describe('NavBar', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows the Movers link to staff', async () => {
    api.get.mockResolvedValue({ data: { username: 'benja', is_staff: true } })
    renderNav()
    expect(await screen.findByRole('link', { name: 'Movers' })).toHaveAttribute('href', '/movers')
    expect(api.get).toHaveBeenCalledWith('/api/user/me/')
  })

  it('hides it from other accounts', async () => {
    api.get.mockResolvedValue({ data: { username: 'someone', is_staff: false } })
    renderNav()
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    expect(screen.queryByRole('link', { name: 'Movers' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Estimates' })).toBeInTheDocument()
  })

  it('hides it if the account can’t be loaded', async () => {
    api.get.mockRejectedValue(new Error('offline'))
    renderNav()
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    expect(screen.queryByRole('link', { name: 'Movers' })).not.toBeInTheDocument()
  })
})
