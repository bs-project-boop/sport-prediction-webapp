import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SearchBox } from './SearchBox'

describe('SearchBox', () => {
  it('renders a labeled input (not placeholder-only)', () => {
    render(<SearchBox value="" onChange={() => {}} label="Cari tim" />)
    expect(screen.getByLabelText('Cari tim')).toBeTruthy()
  })

  it('shows empty state when query has 0 results', () => {
    render(<SearchBox value="atlantis" onChange={() => {}} resultCount={0} totalCount={10} />)
    expect(screen.queryByText(/Tidak ditemukan pertandingan/)).toBeTruthy()
  })

  it('shows match count when query has results', () => {
    render(<SearchBox value="manchester" onChange={() => {}} resultCount={3} totalCount={50} />)
    expect(screen.queryByText(/3 dari 50 pertandingan cocok/)).toBeTruthy()
  })

  it('does NOT show empty state when query is empty (no false alarms)', () => {
    render(<SearchBox value="" onChange={() => {}} resultCount={0} totalCount={10} />)
    expect(screen.queryByText(/Tidak ditemukan/)).toBeNull()
  })

  it('clear button (x) resets the query', async () => {
    const onChange = vi.fn()
    render(<SearchBox value="manchester" onChange={onChange} />)
    const user = userEvent.setup()
    await user.click(screen.getByLabelText('Bersihkan pencarian'))
    expect(onChange).toHaveBeenCalledWith('')
  })

  it('typing fires onChange', () => {
    const onChange = vi.fn()
    render(<SearchBox value="" onChange={onChange} />)
    const input = screen.getByLabelText('Cari tim atau nama')
    fireEvent.change(input, { target: { value: 'liverpool' } })
    expect(onChange).toHaveBeenCalledWith('liverpool')
  })
})