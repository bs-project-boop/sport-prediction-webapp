export function normalizePinInput(raw: string): string {
  return raw.replace(/\D/g, '').slice(0, 6)
}

export function pastePinValue(raw: string): { value: string; shouldSubmit: false } {
  return { value: normalizePinInput(raw), shouldSubmit: false }
}
