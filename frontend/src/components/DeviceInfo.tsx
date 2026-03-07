import { Stack, Text } from '@mantine/core'
import { useI18n } from '../i18n'
import { DeviceUsage } from './DeviceUsage'
import type { DeviceQuota } from '../api/schemas'

export interface DeviceInfoProps {
  device: DeviceQuota
}

export function DeviceInfo({ device }: DeviceInfoProps) {
  const { t } = useI18n()
  return (
    <Stack gap={2}>
      <Text size="sm" c="dimmed">
        {t('fstypeLabel')}: {device.fstype}
      </Text>
      <Text size="sm" c="dimmed">
        {t('mountPointsLabel')}: {device.mount_points.join(', ')}
      </Text>
      {device.usage && (
        <DeviceUsage
          usage={device.usage}
          userQuotas={device.user_quotas ?? []}
          quotaFormat={device.user_quota_format}
        />
      )}
    </Stack>
  )
}
