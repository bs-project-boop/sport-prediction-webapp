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
  BENAR: { label: 'Benar', description: 'Prediksi tepat dengan keputusan sebenar.', icon: '✓', tone: 'success' },
  SEBAGIAN_BENAR: { label: 'Sebagian benar', description: 'Prediksi sebahagian sahaja.', icon: '◐', tone: 'warning' },
  SALAH: { label: 'Salah', description: 'Prediksi tidak tepat.', icon: '×', tone: 'danger' },
  NO_PICK: { label: 'No pick', description: 'Model tidak buat pilihan tegas.', icon: '—', tone: 'muted' },
  NO_PREDICTION: { label: 'Belum ada prediksi', description: 'Tiada prediksi untuk peristiwa ini.', icon: '·', tone: 'subtle' },
}

export function getValidationMeta(status: ValidationStatus | string | null | undefined): ValidationMeta {
  if (status && status in VALIDATION_META) {
    return VALIDATION_META[status as ValidationStatus]
  }
  return { label: 'Status tidak dikenali', description: 'Status daripada sumber tidak dapat dikenalpasti.', icon: '?', tone: 'muted' }
}
