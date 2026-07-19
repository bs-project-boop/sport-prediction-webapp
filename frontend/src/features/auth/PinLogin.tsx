import type { ClipboardEvent } from 'react'
import { useState } from 'react'
import { normalizePinInput, pastePinValue } from './pin'

interface PinLoginProps {
  busy: boolean
  error: string | null
  onSubmit: (pin: string) => void
}

export function PinLogin({ busy, error, onSubmit }: PinLoginProps) {
  const [pin, setPin] = useState('')

  const updatePin = (value: string) => setPin(normalizePinInput(value))
  const handlePaste = (event: ClipboardEvent<HTMLInputElement>) => {
    event.preventDefault()
    setPin(pastePinValue(event.clipboardData.getData('text')).value)
  }

  return (
    <main className="auth-shell">
      <section className="auth-card" aria-labelledby="login-title">
        <div className="brand-mark" aria-hidden="true">SP</div>
        <p className="eyebrow">SPORT INTELLIGENCE / PRIVATE BETA</p>
        <h1 id="login-title">Your edge,<br /><span>measured.</span></h1>
        <p className="auth-copy">Enter your six-digit access PIN to open today&apos;s prediction desk.</p>
        <form onSubmit={(event) => { event.preventDefault(); if (pin.length === 6) onSubmit(pin) }}>
          <label className="pin-label" htmlFor="pin-entry">Access PIN</label>
          <input
            id="pin-entry"
            className="pin-entry"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={pin}
            onChange={(event) => updatePin(event.target.value)}
            onPaste={handlePaste}
            aria-describedby={error ? 'pin-error' : 'pin-help'}
          />
          <div className="pin-boxes" aria-hidden="true">
            {Array.from({ length: 6 }, (_, index) => (
              <span className={`pin-box ${pin[index] ? 'filled' : ''}`} key={index}>{pin[index] ? '•' : ''}</span>
            ))}
          </div>
          <p id="pin-help" className="pin-help">Six digits · Your session stays private</p>
          {error && <p id="pin-error" className="form-error" role="alert">We couldn&apos;t verify that PIN. Please try again.</p>}
          <button className="primary-button" type="submit" disabled={busy || pin.length !== 6}>
            {busy ? 'Checking access…' : 'Open dashboard'} <span aria-hidden="true">↗</span>
          </button>
        </form>
        <p className="auth-footer">Protected prediction workspace · v3.2 data contract</p>
      </section>
      <aside className="auth-art" aria-label="Dashboard preview">
        <div className="orb orb-one" />
        <div className="orb orb-two" />
        <div className="art-copy"><span>LIVE SIGNAL</span><strong>Read the game<br />before it starts.</strong></div>
        <div className="mini-chart"><i /><i /><i /><i /><i /><i /><i /></div>
      </aside>
    </main>
  )
}
