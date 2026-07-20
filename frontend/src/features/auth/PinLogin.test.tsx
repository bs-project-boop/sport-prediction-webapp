import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PinLogin } from './PinLogin'

const defaultProps = {
  busy: false,
  error: null,
  onSubmit: vi.fn(),
}

describe('PinLogin', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders 6 PIN box buttons', () => {
    render(<PinLogin {...defaultProps} />)
    const boxes = screen.getAllByRole('button')
    const digitBoxes = boxes.filter((b: HTMLElement) => b.getAttribute('aria-label')?.startsWith('Digit '))
    expect(digitBoxes.length).toBe(6)
    digitBoxes.forEach((box: HTMLElement, i: number) => {
      expect(box.getAttribute('aria-label')).toBe(`Digit ${i + 1}`)
    })
  })

  it('fills boxes when user types via the hidden input', async () => {
    const user = userEvent.setup()
    render(<PinLogin {...defaultProps} />)
    const input = screen.getByLabelText('Access PIN')
    await user.type(input, '123456')
    const filled = screen.getAllByText('•')
    expect(filled.length).toBe(6)
  })

  it('calls onSubmit with 6-digit PIN when form is submitted', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<PinLogin {...defaultProps} onSubmit={onSubmit} />)
    await user.type(screen.getByLabelText('Access PIN'), '123456')
    await user.click(screen.getByRole('button', { name: /Open dashboard/i }))
    expect(onSubmit).toHaveBeenCalledWith('123456')
  })

  it('does NOT call onSubmit when fewer than 6 digits', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<PinLogin {...defaultProps} onSubmit={onSubmit} />)
    await user.type(screen.getByLabelText('Access PIN'), '123')
    await user.click(screen.getByRole('button', { name: /Open dashboard/i }))
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('clicking a PIN box focuses the hidden input', async () => {
    const user = userEvent.setup()
    render(<PinLogin {...defaultProps} />)
    const thirdBox = screen.getByRole('button', { name: /Digit 3/i })
    await user.click(thirdBox)
    expect(document.activeElement).toBe(screen.getByLabelText('Access PIN'))
  })

  it('shows error message when error prop is set', () => {
    render(<PinLogin {...defaultProps} error="Bad PIN" />)
    expect(screen.getByRole('alert').textContent).toMatch(/couldn.t verify/i)
  })

  it('submit button is disabled when fewer than 6 digits', () => {
    render(<PinLogin {...defaultProps} />)
    const btn = screen.getByRole('button', { name: /Open dashboard/i })
    expect((btn as HTMLButtonElement).disabled).toBe(true)
  })
})
