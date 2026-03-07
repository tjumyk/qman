import { useEffect, useState } from 'react'
import { useI18n } from '../i18n'

interface GraceEndRelativeProps {
  /** Unix timestamp (seconds) when the grace period ends. */
  time: number
}

function formatRelative(ts: number, locale: string): string {
  const now = Math.floor(Date.now() / 1000)
  const diff = ts - now
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  if (Math.abs(diff) < 60) return rtf.format(diff, 'second')
  if (Math.abs(diff) < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (Math.abs(diff) < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  return rtf.format(Math.round(diff / 86400), 'day')
}

/** Renders when a grace period ends as relative time (e.g. "in 5 days", "2 days ago"). Returns null when time <= 0. */
export function GraceEndRelative({ time }: GraceEndRelativeProps) {
  const { locale } = useI18n()
  const [, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 30_000)
    return () => clearInterval(id)
  }, [])
  if (time <= 0) return null
  return <>{formatRelative(time, locale)}</>
}
