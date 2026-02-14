import { useEffect, useState } from 'react'

interface GraceTimestampProps {
  time: number
}

function formatRelative(ts: number): string {
  if (!ts) return '0'
  const now = Math.floor(Date.now() / 1000)
  const diff = ts - now
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  if (Math.abs(diff) < 60) return rtf.format(diff, 'second')
  if (Math.abs(diff) < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (Math.abs(diff) < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  return rtf.format(Math.round(diff / 86400), 'day')
}

export function GraceTimestamp({ time }: GraceTimestampProps) {
  const [, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 30_000)
    return () => clearInterval(id)
  }, [])
  return <>{formatRelative(time)}</>
}
