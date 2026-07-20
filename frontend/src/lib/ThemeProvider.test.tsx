import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { ThemeProvider, useTheme } from './ThemeProvider'

// Store for localStorage mock
const store: Record<string, string> = {}
const localStorageMock = {
  getItem: vi.fn((key: string) => store[key] ?? null),
  setItem: vi.fn((key: string, val: string) => { store[key] = val }),
  removeItem: vi.fn((key: string) => { delete store[key] }),
}
vi.stubGlobal('localStorage', localStorageMock)

// Mock matchMedia on window object directly (not vi.stubGlobal which can miss jsdom)
const lightQuery = { matches: true, media: '(prefers-color-scheme: light)' }
const darkQuery = { matches: false, media: '(prefers-color-scheme: light)' }

function mockMatchMedia(matches: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockReturnValue(matches ? lightQuery : darkQuery),
  })
}

describe('useTheme', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    store['sport-intel-theme'] = ''
    document.documentElement.className = ''
    document.documentElement.removeAttribute('data-theme')
    // Default: system prefers dark
    mockMatchMedia(false)
  })

  it('defaults to dark when no preference stored', () => {
    const { result } = renderHook(useTheme, { wrapper: ThemeProvider })
    expect(result.current.theme).toBe('dark')
  })

  it('defaults to light when prefers-color-scheme is light', () => {
    mockMatchMedia(true)
    delete store['sport-intel-theme']
    const { result } = renderHook(useTheme, { wrapper: ThemeProvider })
    expect(result.current.theme).toBe('light')
  })

  it('uses stored preference when available', () => {
    store['sport-intel-theme'] = 'light'
    const { result } = renderHook(useTheme, { wrapper: ThemeProvider })
    expect(result.current.theme).toBe('light')
  })

  it('toggle switches dark → light', () => {
    const { result } = renderHook(useTheme, { wrapper: ThemeProvider })
    expect(result.current.theme).toBe('dark')
    act(() => { result.current.toggle() })
    expect(result.current.theme).toBe('light')
  })

  it('toggle switches light → dark', () => {
    store['sport-intel-theme'] = 'light'
    const { result } = renderHook(useTheme, { wrapper: ThemeProvider })
    act(() => { result.current.toggle() })
    expect(result.current.theme).toBe('dark')
  })

  it('persists theme to localStorage on toggle', () => {
    const { result } = renderHook(useTheme, { wrapper: ThemeProvider })
    act(() => { result.current.toggle() })
    expect(localStorageMock.setItem).toHaveBeenCalledWith('sport-intel-theme', 'light')
  })

  it('applies dark class to html element', () => {
    renderHook(useTheme, { wrapper: ThemeProvider })
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })

  it('applies light class to html element', () => {
    store['sport-intel-theme'] = 'light'
    renderHook(useTheme, { wrapper: ThemeProvider })
    expect(document.documentElement.classList.contains('light')).toBe(true)
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })
})
