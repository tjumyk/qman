import { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Stack, Text, Loader, Alert, Group } from '@mantine/core'
import { IconDisc } from '@tabler/icons-react'
import { fetchQuotas } from '../api'
import { useI18n } from '../i18n'
import { DeviceUsage } from '../components/DeviceUsage'
import { DockerDetailTabs } from '../components/docker/DockerDetailTabs'
import { UserQuotaTable } from '../components/UserQuotaTable'

export function DeviceUserListPage() {
  const { hostId, deviceName } = useParams<{ hostId: string; deviceName: string }>()
  const { t } = useI18n()

  const { data, isLoading, error } = useQuery({ queryKey: ['quotas'], queryFn: fetchQuotas })

  const device = useMemo(() => {
    if (!hostId || !deviceName || !data) return null
    const payload = data[hostId]
    if (!payload?.results) return null
    return payload.results.find((d) => d.name === deviceName) ?? null
  }, [data, hostId, deviceName])

  if (!hostId || !deviceName) return <Alert color="red">{t('missingHostOrDevice')}</Alert>
  if (isLoading) {
    return (
      <Stack align="center" gap="md" py="xl">
        <Loader size="lg" />
        <Text c="dimmed">{t('loading')}</Text>
      </Stack>
    )
  }
  if (error || !data) {
    return (
      <Alert color="red" title={t('error')}>
        {error instanceof Error ? error.message : t('failedToLoadQuotas')}
      </Alert>
    )
  }
  if (!device) {
    return <Alert color="red">{t('deviceNotFound')}</Alert>
  }

  // Docker devices use special tabbed view with containers, images, volumes
  const isDockerDevice = device.fstype === 'docker'

  if (isDockerDevice) {
    return (
      <Stack gap="md">
        <Group justify="space-between" gap="sm">
          <Group gap="sm">
            <IconDisc size={24} />
            <Text size="lg" fw={600}>
              {hostId} › {deviceName}
            </Text>
          </Group>
        </Group>
        <DockerDetailTabs hostId={hostId} device={device} />
      </Stack>
    )
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" gap="sm">
        <Group gap="sm">
          <IconDisc size={24} />
          <Text size="lg" fw={600}>
            {hostId} › {deviceName}
          </Text>
        </Group>
      </Group>
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
            userQuotas={device.user_quotas}
            quotaFormat={device.user_quota_format}
          />
        )}
      </Stack>
      <UserQuotaTable hostId={hostId} device={device} />
    </Stack>
  )
}
