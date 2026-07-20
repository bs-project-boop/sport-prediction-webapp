import { describe, expect, it } from 'vitest'
import { getValidationMeta, type ValidationStatus } from './validation'

describe('getValidationMeta', () => {
  it.each([
    ['BENAR', 'Benar', 'success'],
    ['SEBAGIAN_BENAR', 'Sebagian benar', 'warning'],
    ['SALAH', 'Salah', 'danger'],
    ['NO_PICK', 'No pick', 'muted'],
    ['NO_PREDICTION', 'Belum ada prediksi', 'subtle'],
  ] as const)('maps %s to an accessible label and tone', (status, label, tone) => {
    expect(getValidationMeta(status)).toMatchObject({ label, tone })
  })

  it('uses a safe fallback for unknown API values', () => {
    expect(getValidationMeta('FUTURE_STATUS' as ValidationStatus)).toMatchObject({
      label: 'Status tidak dikenali',
      tone: 'muted',
    })
  })
})
