import { useEffect, useState } from 'react'
import { Text, Tooltip } from '@mantine/core'
import { useI18n } from '../i18n'
import type { DeviceQuota } from '../api/schemas'

function formatPastRelative(cachedAt: number, locale: string): string {
  const now = Math.floor(Date.now() / 1000)
  const diff = cachedAt - now
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  const abs = Math.abs(diff)
  if (abs < 60) return rtf.format(diff, 'second')
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  return rtf.format(Math.round(diff / 86400), 'day')
}

function formatAbsolute(cachedAt: number, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(cachedAt * 1000))
}

interface DockerUsageCacheHintProps {
  device: DeviceQuota
}

/** Hint when Docker quota usage comes from a cached df snapshot (may be stale). */
export function DockerUsageCacheHint({ device }: DockerUsageCacheHintProps) {
  const { t, locale } = useI18n()
  const [, setTick] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 30_000)
    return () => clearInterval(id)
  }, [])

  if (device.fstype !== 'docker') return null

  const cachedAt = device.docker_usage_cached_at
  if (cachedAt == null || cachedAt <= 0) {
    return (
      <Text size="xs" c="dimmed">
        {t('dockerUsageCachePending')}
      </Text>
    )
  }

  const relative = formatPastRelative(cachedAt, locale)
  const absolute = formatAbsolute(cachedAt, locale)
  const isStale = device.docker_usage_cache_stale === true
  const template = isStale ? t('dockerUsageCacheStale') : t('dockerUsageCacheFresh')
  const label = template.replace('{time}', relative)

  return (
    <Tooltip label={absolute} withArrow>
      <Text size="xs" c={isStale ? 'orange' : 'dimmed'}>
        {label}
      </Text>
    </Tooltip>
  )
}
