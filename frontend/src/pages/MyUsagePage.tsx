import { useQuery } from '@tanstack/react-query'
import { Card, Stack, Text, Progress, Badge, Loader, Alert, Group, SimpleGrid, Title } from '@mantine/core'
import { IconChartBar } from '@tabler/icons-react'
import { Link } from 'react-router-dom'
import { Anchor } from '@mantine/core'
import { fetchMeMappings, fetchMeQuotas } from '../api'
import { useI18n } from '../i18n'
import { BlockSize } from '../components/BlockSize'
import { INodeSize } from '../components/INodeSize'
import { getQuotaStatus, getQuotaStatusColor, getQuotaStatusLabelKey } from '../utils/quotaStatus'
import type { DeviceQuota, UserQuota } from '../api/schemas'

const MAPPING_KEY_SEP = '|'

function parseMappingKey(key: string): { hostId: string; hostUserName: string } {
  const i = key.indexOf(MAPPING_KEY_SEP)
  if (i === -1) return { hostId: key, hostUserName: '' }
  return { hostId: key.slice(0, i), hostUserName: key.slice(i + 1) }
}

function QuotaCard({
  device,
  quota,
  t,
}: {
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
    <Card shadow="sm" padding="sm" radius="md" withBorder>
      <Stack gap="xs">
        <Group justify="space-between" wrap="wrap" gap="xs" align="center">
          <Group gap="xs" wrap="wrap" align="center">
            <Text size="sm" fw={600} lineClamp={1}>
              {device.name}
            </Text>
            {device.mount_points.map((mp) => (
              <Badge key={mp} size="sm" variant="outline" color="gray" styles={{ root: { textTransform: 'none' } }}>
                {mp}
              </Badge>
            ))}
          </Group>
          <Badge color={statusColor} variant="light" size="sm">
            {statusLabel}
          </Badge>
        </Group>
        <Stack gap={4}>
          <div>
            <Text size="xs" fw={500} c="dimmed" mb={2}>
              {t('blockUsage')}
            </Text>
            <Progress value={blockPct} color={statusColor} size="sm" />
            <Text size="xs" c="dimmed" mt={2}>
              <BlockSize size={quota.block_current} />
              {blockLimit > 0 && (
                <> / <BlockSize size={blockLimit * 1024} /></>
              )}
            </Text>
          </div>
          {device.user_quota_format !== 'zfs' && (
            <div>
              <Text size="xs" fw={500} c="dimmed" mb={2}>
                {t('inodeUsage')}
              </Text>
              <Progress value={inodePct} color={statusColor} size="sm" />
              <Text size="xs" c="dimmed" mt={2}>
                <INodeSize size={quota.inode_current} />
                {inodeLimit > 0 && (
                  <> / <INodeSize size={inodeLimit} /></>
                )}
              </Text>
            </div>
          )}
        </Stack>
      </Stack>
    </Card>
  )
}

export function MyUsagePage() {
  const { t } = useI18n()
  const { data: mappings, isLoading: mappingsLoading, error: mappingsError } = useQuery({
    queryKey: ['me-mappings'],
    queryFn: fetchMeMappings,
  })

  const { data: quotasData, isLoading: quotasLoading, error: quotasError } = useQuery({
    queryKey: ['me-quotas'],
    queryFn: () => fetchMeQuotas(),
    enabled: mappings !== undefined && (mappings?.length ?? 0) > 0,
  })

  if (mappingsLoading) {
    return (
      <Stack align="center" gap="md" py="xl">
        <Loader size="lg" />
        <Text c="dimmed">{t('loadingYourQuotas')}</Text>
      </Stack>
    )
  }
  if (mappingsError) {
    return (
      <Alert color="red" title={t('error')}>
        {mappingsError instanceof Error ? mappingsError.message : t('failedToLoadQuotas')}
      </Alert>
    )
  }
  if (!mappings) return null

  if (mappings.length === 0) {
    return (
      <Stack gap="md">
        <Group gap="sm">
          <IconChartBar size={24} />
          <Text size="lg" fw={600}>
            {t('yourQuotaUsage')}
          </Text>
        </Group>
        <Alert color="blue" title={t('noHostUserLinked')}>
          {t('noHostUserLinkedMessage')}{' '}
          <Anchor component={Link} to="/my-mappings">
            {t('manageMyMappings')}
          </Anchor>
        </Alert>
      </Stack>
    )
  }

  if (quotasLoading && !quotasData) {
    return (
      <Stack align="center" gap="md" py="xl">
        <Loader size="lg" />
        <Text c="dimmed">{t('loadingYourQuotas')}</Text>
      </Stack>
    )
  }
  if (quotasError) {
    return (
      <Alert color="red" title={t('error')}>
        {quotasError instanceof Error ? quotasError.message : t('failedToLoadQuotas')}
      </Alert>
    )
  }
  const data = quotasData ?? {}
  // Build sections in mapping order (from mappings list) so UI is stable
  const mappingKeys = (mappings ?? []).map((m) => `${m.host_id}${MAPPING_KEY_SEP}${m.host_user_name}`)
  const sections: { mappingKey: string; label: string; cards: { device: DeviceQuota; quota: UserQuota }[] }[] = []
  for (const mappingKey of mappingKeys) {
    const { hostId, hostUserName } = parseMappingKey(mappingKey)
    const label = `${hostId} › ${hostUserName}`
    const hostData = data[mappingKey]
    const cards: { device: DeviceQuota; quota: UserQuota }[] = []
    if (hostData && !hostData.error && hostData.results) {
      for (const device of hostData.results) {
        const userQuotas = device.user_quotas || []
        for (const q of userQuotas) {
          cards.push({ device, quota: q })
        }
      }
    }
    sections.push({ mappingKey, label, cards })
  }

  const hasAnyCards = sections.some((s) => s.cards.length > 0)

  return (
    <Stack gap="lg">
      <Group gap="sm">
        <IconChartBar size={24} />
        <Text size="lg" fw={600}>
          {t('yourQuotaUsage')}
        </Text>
      </Group>
      {!hasAnyCards ? (
        <Alert color="blue" title={t('noQuotas')}>
          {t('noQuotasAssigned')}
        </Alert>
      ) : (
        <Stack gap="md">
          {sections.map(({ mappingKey, label, cards }) => (
            <Stack key={mappingKey} gap="xs">
              <Title order={5}>{label}</Title>
              {cards.length === 0 ? (
                <Alert color="gray">
                  {t('noQuotasAssigned')}
                </Alert>
              ) : (
                <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="sm">
                  {cards.map(({ device, quota }) => (
                    <QuotaCard
                      key={`${mappingKey}-${device.name}`}
                      device={device}
                      quota={quota}
                      t={t}
                    />
                  ))}
                </SimpleGrid>
              )}
            </Stack>
          ))}
        </Stack>
      )}
    </Stack>
  )
}
