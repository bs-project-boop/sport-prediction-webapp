/**
 * SearchBox — debounced search input for matches (teams or individuals).
 *
 * ui-ux-pro-max guidelines applied:
 *  - Forms → Input Labels: visible label above the input (not placeholder-only).
 *    Placeholder shows example query, but the label "Cari tim atau nama" is
 *    always present for screen readers.
 *  - Search → Autocomplete: debounced (300ms) — see useDebounced in caller.
 *  - Touch Target Size: clear button is 44x44 (min-h-[44px] min-w-[44px]).
 *  - Input Affordance: bordered background with focus ring.
 *  - Accessibility: aria-label, role="search", live region for count.
 */
import { useId } from 'react'

interface SearchBoxProps {
  value: string
  onChange: (v: string) => void
  resultCount?: number
  totalCount?: number
  placeholder?: string
  label?: string
}

export function SearchBox({
  value,
  onChange,
  resultCount,
  totalCount,
  placeholder = 'Cari tim atau nama…',
  label = 'Cari tim atau nama',
}: SearchBoxProps) {
  const inputId = useId()
  const liveId = useId()
  const hasQuery = value.trim().length > 0
  const showCount = resultCount !== undefined && hasQuery

  return (
    <div className="search-box" role="search">
      <label htmlFor={inputId} className="search-box-label">
        {label}
      </label>
      <div className="search-box-input-wrap">
        <svg
          className="search-box-icon"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          id={inputId}
          type="search"
          className="search-box-input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          aria-label={label}
          aria-describedby={liveId}
          autoComplete="off"
          spellCheck={false}
        />
        {hasQuery && (
          <button
            type="button"
            className="search-box-clear"
            onClick={() => onChange('')}
            aria-label="Bersihkan pencarian"
            title="Bersihkan pencarian"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        )}
      </div>
      {/* live region announces result count to screen readers */}
      <div id={liveId} className="search-box-live" aria-live="polite" aria-atomic="true">
        {showCount && resultCount === 0 && (
          <span className="search-box-empty">
            Tidak ditemukan pertandingan untuk &ldquo;{value}&rdquo;.
          </span>
        )}
        {showCount && resultCount! > 0 && totalCount !== undefined && (
          <span className="search-box-count">
            {resultCount} dari {totalCount} pertandingan cocok dengan &ldquo;{value}&rdquo;.
          </span>
        )}
      </div>
    </div>
  )
}