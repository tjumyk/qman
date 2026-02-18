import type { ReactNode } from 'react'
import { Stack, Text, Progress, Group, Badge, Box, Tooltip } from '@mantine/core'
import { BlockSize } from './BlockSize'
import { useI18n } from '../i18n'
import type { DiskUsage, UserQuota } from '../api/schemas'

// Backend: block_soft_limit / block_hard_limit are in 1K blocks (pyquota); block_current is bytes
const BLOCK_SIZE = 1024

function computeReservedAndTracked(userQuotas: UserQuota[]): {
  reservedSoft: number
  reservedHard: number
  trackedUsage: number
} {
  let reservedSoft = 0
  let reservedHard = 0
  let trackedUsage = 0
  for (const q of userQuotas) {
    if (q.block_soft_limit > 0) reservedSoft += q.block_soft_limit * BLOCK_SIZE
    if (q.block_hard_limit > 0) reservedHard += q.block_hard_limit * BLOCK_SIZE
    trackedUsage += q.block_current
  }
  return { reservedSoft, reservedHard, trackedUsage }
}

function pct(total: number, value: number): number {
  return total > 0 ? (value / total) * 100 : 0
}

interface DeviceUsageProps {
  usage: DiskUsage
  userQuotas?: UserQuota[]
  /** When set (e.g. Docker with unattributed usage), used as label for the "other" segment instead of otherUsageLabel. */
  otherUsageLabelOverride?: string
  /** When set (e.g. Docker), size in bytes for the "other" segment. If not set, other = used - trackedUsage (pyquota/ZFS). */
  otherUsageBytes?: number
}

export function DeviceUsage({ usage, userQuotas, otherUsageLabelOverride, otherUsageBytes }: DeviceUsageProps) {
  const { t } = useI18n()
  const otherLabel = otherUsageLabelOverride ?? t('otherUsageLabel')
  const { used, total, free: userFree } = usage
  const physicalFree = total - used
  const rootReserved = Math.max(0, physicalFree - userFree)
  const hasFree = userFree > 0
  /** For Docker, used = attributed only; total consumption = used + (otherUsageBytes ?? 0). For pyquota/ZFS, used = device used. */
  const displayUsed = otherUsageBytes != null ? used + otherUsageBytes : used
  const displayPercent = total > 0 ? Math.round((displayUsed / total) * 100) : 0

  const simple = (
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        {t('diskUsageLabel')}
      </Text>
      <Progress
        value={displayPercent}
        size="sm"
        color={hasFree ? 'green' : 'red'}
      />
      <Group gap="xs">
        <Text size="xs" c="dimmed">
          <BlockSize size={displayUsed} /> / <BlockSize size={total} /> ({Math.round(displayPercent)}%)
        </Text>
        {hasFree ? (
          <Badge size="xs" color="green" variant="light">{t('freeSpaceLabel')}</Badge>
        ) : (
          <Badge size="xs" color="red" variant="light">{t('noFreeSpaceLabel')}</Badge>
        )}
      </Group>
    </Stack>
  )

  if (!userQuotas || userQuotas.length === 0) {
    return simple
  }

  const { reservedSoft, reservedHard, trackedUsage } = computeReservedAndTracked(userQuotas)
  const otherUsage = otherUsageBytes != null ? Math.max(0, otherUsageBytes) : Math.max(0, used - trackedUsage)
  // Demand = other + root reserved + quota reserved; over-sold when demand > total (exceeds user-addressable pool)
  const totalDemandSoft = otherUsage + rootReserved + reservedSoft
  const totalDemandHard = otherUsage + rootReserved + reservedHard
  const overSoldSoft = totalDemandSoft > total
  const overSoldHard = totalDemandHard > total
  const freeSoft = Math.max(0, total - totalDemandSoft)
  const freeHard = Math.max(0, total - totalDemandHard)

  const maxBytes = Math.max(total, totalDemandSoft, totalDemandHard, 1)
  const toScalePct = (bytes: number) => pct(maxBytes, bytes)

  const barHeight = 'sm'
  const labelWidth = 115
  const labelBarGap = 12
  const barStartOffset = labelWidth + labelBarGap

  const diskOtherPct = toScalePct(otherUsage)
  const diskTrackedPct = toScalePct(trackedUsage)
  const diskRootReservedPct = toScalePct(rootReserved)
  const diskUserFreePct = toScalePct(userFree)

  const softOtherPct = toScalePct(otherUsage)
  const softReservedPct = toScalePct(reservedSoft)
  const softRootReservedPct = toScalePct(rootReserved)
  const softFreePct = toScalePct(freeSoft)

  const hardOtherPct = toScalePct(otherUsage)
  const hardReservedPct = toScalePct(reservedHard)
  const hardRootReservedPct = toScalePct(rootReserved)
  const hardFreePct = toScalePct(freeHard)

  const diskLimitPct = toScalePct(total)

  const BarWithMarker = ({
    children,
    showDiskLimit,
  }: { children: ReactNode; showDiskLimit: boolean }) => (
    <Box style={{ position: 'relative', width: '100%' }}>
      {children}
      {showDiskLimit && total < maxBytes && (
        <Box
          role="img"
          aria-label={t('diskLimitLabel')}
          title={t('diskLimitLabel')}
          style={{
            position: 'absolute',
            left: `${diskLimitPct}%`,
            top: 0,
            bottom: 0,
            width: 2,
            backgroundColor: 'var(--mantine-color-dark-7)',
            zIndex: 1,
          }}
        />
      )}
    </Box>
  )

  const segmentTooltip = (segmentLabel: string, size: number) => (
    <>{segmentLabel}: <BlockSize size={size} /></>
  )

  const BarRow = ({
    label,
    bar,
    summary,
    badge,
  }: {
    label: string
    bar: ReactNode
    summary: ReactNode
    badge?: ReactNode
  }) => (
    <Stack gap={4} style={{ width: '100%' }}>
      <Box style={{ display: 'flex', alignItems: 'center', gap: labelBarGap }}>
        <Text size="sm" fw={500} style={{ width: labelWidth, flexShrink: 0 }}>{label}</Text>
        <Box style={{ flex: 1, minWidth: 0 }}>{bar}</Box>
      </Box>
      <Box style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: barStartOffset }}>
        <Text size="xs" c="dimmed">{summary}</Text>
        {badge}
      </Box>
    </Stack>
  )

  return (
    <Stack gap="md">
      <BarRow
        label={t('diskUsageLabel')}
        bar={
          <Progress.Root size={barHeight}>
            {diskRootReservedPct > 0 && (
              <Tooltip withArrow label={segmentTooltip(t('rootReservedLabel'), rootReserved)}>
                <Progress.Section value={diskRootReservedPct} color="yellow" />
              </Tooltip>
            )}
            {diskOtherPct > 0 && (
              <Tooltip withArrow label={segmentTooltip(t('otherUsageLabel'), otherUsage)}>
                <Progress.Section value={diskOtherPct} color="gray" />
              </Tooltip>
            )}
            {diskTrackedPct > 0 && (
              <Tooltip withArrow label={segmentTooltip(t('trackedUsageLabel'), trackedUsage)}>
                <Progress.Section value={diskTrackedPct} color="blue" />
              </Tooltip>
            )}
            {diskUserFreePct > 0 && (
              <Tooltip withArrow label={segmentTooltip(t('freeSpaceLabel'), userFree)}>
                <Progress.Section value={diskUserFreePct} color="green" />
              </Tooltip>
            )}
          </Progress.Root>
        }
        summary={<>{t('captionEqualsTotal')} <BlockSize size={total} /></>}
        badge={hasFree ? <Badge size="xs" color="green" variant="light">{t('freeSpaceLabel')}</Badge> : <Badge size="xs" color="red" variant="light">{t('noFreeSpaceLabel')}</Badge>}
      />

      <BarRow
        label={t('softQuotaUsageLabel')}
        bar={
          <BarWithMarker showDiskLimit={overSoldSoft}>
            <Progress.Root size={barHeight}>
              {softRootReservedPct > 0 && <Progress.Section value={softRootReservedPct} color="transparent" />}
              {softOtherPct > 0 && <Progress.Section value={softOtherPct} color="transparent" />}
              {softReservedPct > 0 && (
                <Tooltip withArrow label={segmentTooltip(t('reservedSoftLabel'), reservedSoft)}>
                  <Progress.Section value={softReservedPct} color="orange" />
                </Tooltip>
              )}
              {softFreePct > 0 && (
                <Tooltip withArrow label={segmentTooltip(t('freeSpaceLabel'), freeSoft)}>
                  <Progress.Section value={softFreePct} color="green" />
                </Tooltip>
              )}
            </Progress.Root>
          </BarWithMarker>
        }
        summary={overSoldSoft ? <>{t('captionEqualsDemand')} <BlockSize size={totalDemandSoft} /> ({total > 0 ? Math.round((totalDemandSoft / total) * 100) : 0}%)</> : <>{t('captionEqualsTotal')} <BlockSize size={total} /></>}
        badge={overSoldSoft ? <Badge size="xs" color="orange" variant="light">{t('overSoldLabel')}</Badge> : <Badge size="xs" color="green" variant="light">{t('freeSpaceLabel')}</Badge>}
      />

      <BarRow
        label={t('hardQuotaUsageLabel')}
        bar={
          <BarWithMarker showDiskLimit={overSoldHard}>
            <Progress.Root size={barHeight}>
              {hardRootReservedPct > 0 && <Progress.Section value={hardRootReservedPct} color="transparent" />}
              {hardOtherPct > 0 && <Progress.Section value={hardOtherPct} color="transparent" />}
              {hardReservedPct > 0 && (
                <Tooltip withArrow label={segmentTooltip(t('reservedHardLabel'), reservedHard)}>
                  <Progress.Section value={hardReservedPct} color="red" />
                </Tooltip>
              )}
              {hardFreePct > 0 && (
                <Tooltip withArrow label={segmentTooltip(t('freeSpaceLabel'), freeHard)}>
                  <Progress.Section value={hardFreePct} color="green" />
                </Tooltip>
              )}
            </Progress.Root>
          </BarWithMarker>
        }
        summary={overSoldHard ? <>{t('captionEqualsDemand')} <BlockSize size={totalDemandHard} /> ({total > 0 ? Math.round((totalDemandHard / total) * 100) : 0}%)</> : <>{t('captionEqualsTotal')} <BlockSize size={total} /></>}
        badge={overSoldHard ? <Badge size="xs" color="red" variant="light">{t('overSoldLabel')}</Badge> : <Badge size="xs" color="green" variant="light">{t('freeSpaceLabel')}</Badge>}
      />

      <Group gap="md" wrap="wrap" style={{ paddingLeft: barStartOffset }}>
        {rootReserved > 0 && (
          <Group gap={4}>
            <Box w={8} h={8} style={{ borderRadius: 2, backgroundColor: 'var(--mantine-color-yellow-5)' }} />
            <Text size="xs" c="dimmed">{t('rootReservedLabel')}</Text>
          </Group>
        )}
        <Group gap={4}>
          <Box w={8} h={8} style={{ borderRadius: 2, backgroundColor: 'var(--mantine-color-gray-5)' }} />
          <Text size="xs" c="dimmed">{otherLabel}</Text>
        </Group>
        <Group gap={4}>
          <Box w={8} h={8} style={{ borderRadius: 2, backgroundColor: 'var(--mantine-color-blue-5)' }} />
          <Text size="xs" c="dimmed">{t('trackedUsageLabel')}</Text>
        </Group>
        <Group gap={4}>
          <Box w={8} h={8} style={{ borderRadius: 2, backgroundColor: 'var(--mantine-color-green-5)' }} />
          <Text size="xs" c="dimmed">{t('freeSpaceLabel')}</Text>
        </Group>
        <Group gap={4}>
          <Box w={8} h={8} style={{ borderRadius: 2, backgroundColor: 'var(--mantine-color-orange-5)' }} />
          <Text size="xs" c="dimmed">{t('reservedSoftLabel')}</Text>
        </Group>
        <Group gap={4}>
          <Box w={8} h={8} style={{ borderRadius: 2, backgroundColor: 'var(--mantine-color-red-5)' }} />
          <Text size="xs" c="dimmed">{t('reservedHardLabel')}</Text>
        </Group>
      </Group>
    </Stack>
  )
}
