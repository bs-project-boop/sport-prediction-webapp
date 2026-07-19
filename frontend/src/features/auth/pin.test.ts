import { describe, expect, it } from 'vitest'
import { normalizePinInput, pastePinValue } from './pin'

describe('PIN input helpers', () => {
  it('keeps only six numeric digits', () => {
    expect(normalizePinInput('12a-345678')).toBe('123456')
    expect(normalizePinInput(' 987 ')).toBe('987')
  })

  it('supports a pasted PIN without auto-submitting', () => {
    expect(pastePinValue('123456789')).toEqual({ value: '123456', shouldSubmit: false })
  })
})
