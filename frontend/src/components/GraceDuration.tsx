import { useI18n } from '../i18n'

interface GraceDurationProps {
  /** Grace period duration in seconds (device-level block_grace/inode_grace). */
  seconds: number
}

/** Format a grace period duration (seconds) for device-level quota info. Renders nothing when seconds <= 0. */
export function GraceDuration({ seconds }: GraceDurationProps) {
  const { t } = useI18n()
  if (seconds <= 0) return null
  if (seconds >= 86400) return <>{t('graceDurationDays').replace('{n}', String(Math.round(seconds / 86400)))}</>
  if (seconds >= 3600) return <>{t('graceDurationHours').replace('{n}', String(Math.round(seconds / 3600)))}</>
  if (seconds >= 60) return <>{t('graceDurationMinutes').replace('{n}', String(Math.round(seconds / 60)))}</>
  return <>{t('graceDurationSeconds').replace('{n}', String(seconds))}</>
}
