import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useDebounced } from './useDebounced'

describe('useDebounced', () => {
  it('returns the initial value immediately', () => {
    const { result } = renderHook(() => useDebounced('a', 100))
    expect(result.current).toBe('a')
  })

  it('does not change before delay', () => {
    const { result, rerender } = renderHook(({ v }) => useDebounced(v, 100), {
      initialProps: { v: 'a' },
    })
    rerender({ v: 'b' })
    // Same tick — still 'a'
    expect(result.current).toBe('a')
  })

  it('updates after delay', async () => {
    const { result, rerender } = renderHook(({ v }) => useDebounced(v, 50), {
      initialProps: { v: 'a' },
    })
    rerender({ v: 'b' })
    await new Promise((r) => setTimeout(r, 80))
    expect(result.current).toBe('b')
  })
})