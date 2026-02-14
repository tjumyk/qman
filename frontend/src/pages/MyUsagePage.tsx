import { useQuery } from '@tanstack/react-query'
import { Card, Stack, Text, Progress, Badge, Loader, Alert, Group } from '@mantine/core'
import { fetchMeQuotas } from '../api'
import { useI18n } from '../i18n'
import { BlockSize } from '../components/BlockSize'
import { INodeSize } from '../components/INodeSize'
import { getQuotaStatus, getQuotaStatusColor, getQuotaStatusLabelKey } from '../utils/quotaStatus'
import type { DeviceQuota, UserQuota } from '../api/schemas'

function QuotaCard({
  hostId,
  device,
  quota,
  t,
}: {
  hostId: string
  device: DeviceQuota
  quota: UserQuota
  t: (key: string) => string
}) {
  const status = getQuotaStatus(quota)
  const statusColor = getQuotaStatusColor(status)
  const statusLabel = t(getQuotaStatusLabelKey(status))

  const blockLimit = quota.block_hard_limit > 0 ? quota.block_hard_limit : quota.block_soft_limit
  const blockLimitBytes = blockLimit * 1024
  const blockPct = blockLimitBytes > 0 ? Math.min(100, (quota.block_current / blockLimitBytes) * 100) : 0
  const inodeLimit = quota.inode_hard_limit > 0 ? quota.inode_hard_limit : quota.inode_soft_limit
  const inodePct = inodeLimit > 0 ? Math.min(100, (quota.inode_current / inodeLimit) * 100) : 0

  return (
    <Card shadow="sm" padding="lg" radius="md" withBorder>
      <Stack gap="xs">
        <Group justify="space-between">
          <Text fw={600}>
            {hostId} / {device.name}
          </Text>
          <Badge color={statusColor} variant="light">
            {statusLabel}
          </Badge>
        </Group>
        <Text size="sm" c="dimmed">
          {device.fstype} · {device.mount_points.join(', ')}
        </Text>
        <div>
          <Text size="sm" fw={500} mb={4}>
            {t('blockUsage')}
          </Text>
          <Progress value={blockPct} color={statusColor} size="lg" />
          <Text size="xs" c="dimmed" mt={4}>
            <BlockSize size={quota.block_current} />
            {blockLimit > 0 && (
              <> / <BlockSize size={blockLimit * 1024} /></>
            )}
          </Text>
        </div>
        <div>
          <Text size="sm" fw={500} mb={4}>
            {t('inodeUsage')}
          </Text>
          <Progress value={inodePct} color={statusColor} size="lg" />
          <Text size="xs" c="dimmed" mt={4}>
            <INodeSize size={quota.inode_current} />
            {inodeLimit > 0 && (
              <> / <INodeSize size={inodeLimit} /></>
            )}
          </Text>
        </div>
      </Stack>
    </Card>
  )
}

export function MyUsagePage() {
  const { t } = useI18n()
  const { data, isLoading, error } = useQuery({ queryKey: ['me-quotas'], queryFn: fetchMeQuotas })

  if (isLoading) {
    return (
      <Stack align="center" gap="md" py="xl">
        <Loader size="lg" />
        <Text c="dimmed">{t('loadingYourQuotas')}</Text>
      </Stack>
    )
  }
  if (error) {
    return (
      <Alert color="red" title={t('error')}>
        {error instanceof Error ? error.message : t('failedToLoadQuotas')}
      </Alert>
    )
  }
  if (!data) return null

  const cards: { hostId: string; device: DeviceQuota; quota: UserQuota }[] = []
  for (const [hostId, hostData] of Object.entries(data)) {
    if (hostData.error) continue
    const devices = hostData.results || []
    for (const device of devices) {
      const userQuotas = device.user_quotas || []
      for (const q of userQuotas) {
        cards.push({ hostId, device, quota: q })
      }
    }
  }

  if (cards.length === 0) {
    return (
      <Alert color="blue" title={t('noQuotas')}>
        {t('noQuotasAssigned')}
      </Alert>
    )
  }

  return (
    <Stack gap="md">
      <Text size="lg" fw={600}>
        {t('yourQuotaUsage')}
      </Text>
      <Stack gap="md">
        {cards.map(({ hostId, device, quota }) => (
          <QuotaCard key={`${hostId}-${device.name}`} hostId={hostId} device={device} quota={quota} t={t} />
        ))}
      </Stack>
    </Stack>
  )
}
