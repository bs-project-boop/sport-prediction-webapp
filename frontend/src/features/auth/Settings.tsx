import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiClient, ApiError } from '../../lib/api'

interface Props {
  api: ApiClient
  onPinChanged: () => void
}

type FieldName = 'current_pin' | 'new_pin' | 'confirm_pin'

interface FieldState {
  value: string
  error: string | null
}

function validateNewPin(pin: string): string | null {
  if (pin.length !== 6) return 'PIN must be exactly 6 digits'
  if (!/^\d{6}$/.test(pin)) return 'PIN must contain only numbers'
  return null
}

export function Settings({ api, onPinChanged }: Props) {
  const [fields, setFields] = useState<Record<FieldName, FieldState>>({
    current_pin: { value: '', error: null },
    new_pin: { value: '', error: null },
    confirm_pin: { value: '', error: null },
  })
  const [globalError, setGlobalError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const changePin = useMutation({
    mutationFn: () => api.changePin(fields.current_pin.value, fields.new_pin.value),
    onError: (err: unknown) => {
      if (err instanceof ApiError) {
        if (err.status === 401) setGlobalError('Current PIN is incorrect')
        else if (err.status === 403) setGlobalError('Current PIN is incorrect')
        else if (err.status === 422) setGlobalError('New PIN must be exactly 6 digits')
        else if (err.status === 429) setGlobalError('Too many attempts — please wait before trying again')
        else setGlobalError(`Error (${err.status}) — could not change PIN`)
      } else {
        setGlobalError('An unexpected error occurred')
      }
    },
    onSuccess: () => {
      setSuccess(true)
      setFields({ current_pin: { value: '', error: null }, new_pin: { value: '', error: null }, confirm_pin: { value: '', error: null } })
      setTimeout(() => { setSuccess(false); onPinChanged() }, 3000)
    },
  })

  const touch = (name: FieldName) => {
    setFields((prev) => {
      const next = { ...prev }
      if (name === 'new_pin') {
        next.new_pin = { ...next.new_pin, error: validateNewPin(next.new_pin.value) }
      }
      if (name === 'confirm_pin') {
        const err = next.new_pin.value !== next.confirm_pin.value ? 'PINs do not match' : null
        next.confirm_pin = { ...next.confirm_pin, error: err }
      }
      return next
    })
  }

  const set = (name: FieldName, raw: string) => {
    const value = raw.replace(/\D/g, '')
    setFields((prev) => ({ ...prev, [name]: { value, error: null } }))
    setGlobalError(null)
    if (name === 'new_pin') {
      const err = validateNewPin(value)
      if (err) {
        setFields((prev) => ({ ...prev, new_pin: { value, error: err } }))
      } else {
        setFields((prev) => {
          const confirmErr = prev.confirm_pin.value && value !== prev.confirm_pin.value ? 'PINs do not match' : null
          return { ...prev, confirm_pin: { ...prev.confirm_pin, error: confirmErr } }
        })
      }
    }
    if (name === 'confirm_pin') {
      const newPin = fields.new_pin.value
      if (newPin && value && newPin !== value) {
        setFields((prev) => ({ ...prev, confirm_pin: { value, error: 'PINs do not match' } }))
      }
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const newPinErr = validateNewPin(fields.new_pin.value)
    const confirmErr = fields.new_pin.value !== fields.confirm_pin.value ? 'PINs do not match' : null
    if (newPinErr || confirmErr || !fields.current_pin.value) {
      setFields((prev) => ({
        ...prev,
        current_pin: { ...prev.current_pin, error: !prev.current_pin.value ? 'Required' : prev.current_pin.error },
        new_pin: { ...prev.new_pin, error: newPinErr ?? prev.new_pin.error },
        confirm_pin: { ...prev.confirm_pin, error: confirmErr ?? prev.confirm_pin.error },
      }))
      return
    }
    setGlobalError(null)
    changePin.mutate()
  }

  const busy = changePin.isPending

  return (
    <div className="settings-panel">
      <h2>Change PIN</h2>
      {success && (
        <div className="alert alert-success" role="status">
          PIN changed successfully.
        </div>
      )}
      <form onSubmit={handleSubmit} noValidate>
        <div className="form-group">
          <label htmlFor="current_pin">Current PIN</label>
          <input
            id="current_pin"
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            autoComplete="current-password"
            maxLength={6}
            placeholder="••••••"
            value={fields.current_pin.value}
            onChange={(e) => set('current_pin', e.target.value)}
            onBlur={() => touch('current_pin')}
            disabled={busy}
            aria-describedby={fields.current_pin.error ? 'current_pin_err' : undefined}
          />
          {fields.current_pin.error && <span className="field-error" id="current_pin_err">{fields.current_pin.error}</span>}
        </div>

        <div className="form-group">
          <label htmlFor="new_pin">New PIN</label>
          <input
            id="new_pin"
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            autoComplete="new-password"
            maxLength={6}
            placeholder="••••••"
            value={fields.new_pin.value}
            onChange={(e) => set('new_pin', e.target.value)}
            onBlur={() => touch('new_pin')}
            disabled={busy}
            aria-describedby={fields.new_pin.error ? 'new_pin_err' : undefined}
          />
          {fields.new_pin.error && <span className="field-error" id="new_pin_err">{fields.new_pin.error}</span>}
        </div>

        <div className="form-group">
          <label htmlFor="confirm_pin">Confirm New PIN</label>
          <input
            id="confirm_pin"
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            autoComplete="new-password"
            maxLength={6}
            placeholder="••••••"
            value={fields.confirm_pin.value}
            onChange={(e) => set('confirm_pin', e.target.value)}
            onBlur={() => touch('confirm_pin')}
            disabled={busy}
            aria-describedby={fields.confirm_pin.error ? 'confirm_pin_err' : undefined}
          />
          {fields.confirm_pin.error && <span className="field-error" id="confirm_pin_err">{fields.confirm_pin.error}</span>}
        </div>

        {globalError && (
          <div className="alert alert-error" role="alert">{globalError}</div>
        )}

        <button type="submit" disabled={busy} className="submit-button">
          {busy ? 'Changing…' : 'Change PIN'}
        </button>
      </form>
    </div>
  )
}
