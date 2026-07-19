export type ValidationStatus =
  | 'BENAR'
  | 'SEBAGIAN_BENAR'
  | 'SALAH'
  | 'NO_PICK'
  | 'NO_PREDICTION'

export const VALIDATION_STATUSES: ValidationStatus[] = ['BENAR', 'SEBAGIAN_BENAR', 'SALAH', 'NO_PICK', 'NO_PREDICTION']

export type ValidationTone = 'success' | 'warning' | 'danger' | 'muted' | 'subtle'

export interface ValidationMeta {
  label: string
  description: string
  icon: string
  tone: ValidationTone
}

const VALIDATION_META: Record<ValidationStatus, ValidationMeta> = {
  BENAR: { label: 'Correct', description: 'Prediction matched the result.', icon: '✓', tone: 'success' },
  SEBAGIAN_BENAR: { label: 'Partial', description: 'Prediction was partially correct.', icon: '◐', tone: 'warning' },
  SALAH: { label: 'Incorrect', description: 'Prediction did not match the result.', icon: '×', tone: 'danger' },
  NO_PICK: { label: 'No pick', description: 'The model intentionally made no definitive pick.', icon: '—', tone: 'muted' },
  NO_PREDICTION: { label: 'No prediction', description: 'No prediction was available for this event.', icon: '·', tone: 'subtle' },
}

export function getValidationMeta(status: ValidationStatus | string | null | undefined): ValidationMeta {
  if (status && status in VALIDATION_META) {
    return VALIDATION_META[status as ValidationStatus]
  }
  return { label: 'Unknown status', description: 'The source returned an unrecognized status.', icon: '?', tone: 'muted' }
}
