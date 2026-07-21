/**
 * Debounce hook — delays updating a value until `delay` ms after the last change.
 * Used to throttle search input so we don't refetch on every keystroke.
 *
 * Design notes (from ui-ux-pro-max):
 *  - Search → Autocomplete: "Debounced fetch + dropdown" (good)
 *  - Touch Target Size: "Minimum 44x44px touch targets" (relevant for clear button)
 */
import { useEffect, useState } from 'react'

export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(id)
  }, [value, delay])
  return debounced
}