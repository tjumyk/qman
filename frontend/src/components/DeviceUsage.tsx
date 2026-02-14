import type { ReactNode } from 'react'
import { Stack, Text, Progress, Group, Badge, Box } from '@mantine/core'
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
}

export function DeviceUsage({ usage, userQuotas }: DeviceUsageProps) {
  const { t } = useI18n()
  const { used, total, percent } = usage
  const free = total - used
  const hasFree = free > 0

  const simple = (
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        {t('diskUsageLabel')}
      </Text>
      <Progress
        value={percent}
        size="sm"
        color={hasFree ? 'green' : 'red'}
      />
      <Group gap="xs">
        <Text size="xs" c="dimmed">
          <BlockSize size={used} /> / <BlockSize size={total} /> ({Math.round(percent)}%)
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
  const otherUsage = Math.max(0, used - trackedUsage)
  const overSoldSoft = reservedSoft > total
  const overSoldHard = reservedHard > total

  let otherPct = pct(total, otherUsage)
  let trackedPct = pct(total, trackedUsage)
  let freePct = Math.max(0, pct(total, free))
  if (used >= total && used > 0) {
    const usedSum = otherPct + trackedPct
    if (usedSum > 0) {
      const scale = 100 / usedSum
      otherPct *= scale
      trackedPct *= scale
    }
    freePct = 0
  }
  const totalDemandSoft = otherUsage + reservedSoft
  const totalDemandHard = otherUsage + reservedHard
  const freeSoft = Math.max(0, total - otherUsage - reservedSoft)
  const freeHard = Math.max(0, total - otherUsage - reservedHard)

  const maxBytes = Math.max(total, totalDemandSoft, totalDemandHard, 1)
  const toScalePct = (bytes: number) => pct(maxBytes, bytes)

  const barHeight = 'sm'
  const labelWidth = 115
  const labelBarGap = 12
  const barStartOffset = labelWidth + labelBarGap

  const diskOtherPct = toScalePct(otherUsage)
  const diskTrackedPct = toScalePct(trackedUsage)
  const diskFreePct = toScalePct(Math.max(0, free))

  const softOtherPct = toScalePct(otherUsage)
  const softReservedPct = toScalePct(reservedSoft)
  const softFreePct = toScalePct(freeSoft)

  const hardOtherPct = toScalePct(otherUsage)
  const hardReservedPct = toScalePct(reservedHard)
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

  const BarRow = ({
    label,
    bar,
    caption,
    badge,
  }: {
    label: string
    bar: ReactNode
    caption: ReactNode
    badge?: ReactNode
  }) => (
    <Stack gap={4} style={{ width: '100%' }}>
      <Box style={{ display: 'flex', alignItems: 'center', gap: labelBarGap }}>
        <Text size="sm" fw={500} style={{ width: labelWidth, flexShrink: 0 }}>{label}</Text>
        <Box style={{ flex: 1, minWidth: 0 }}>{bar}</Box>
      </Box>
      <Box style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: barStartOffset }}>
        <Text size="xs" c="dimmed">{caption}</Text>
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
            {diskOtherPct > 0 && <Progress.Section value={diskOtherPct} color="gray" />}
            {diskTrackedPct > 0 && <Progress.Section value={diskTrackedPct} color="blue" />}
            {diskFreePct > 0 && <Progress.Section value={diskFreePct} color="green" />}
          </Progress.Root>
        }
        caption={<><BlockSize size={used} /> / <BlockSize size={total} /> ({Math.round(percent)}%)</>}
        badge={hasFree ? <Badge size="xs" color="green" variant="light">{t('freeSpaceLabel')}</Badge> : <Badge size="xs" color="red" variant="light">{t('noFreeSpaceLabel')}</Badge>}
      />

      <BarRow
        label={t('reservedSoftLabel')}
        bar={
          <BarWithMarker showDiskLimit={overSoldSoft}>
            <Progress.Root size={barHeight}>
              {softOtherPct > 0 && <Progress.Section value={softOtherPct} color="gray" />}
              {softReservedPct > 0 && <Progress.Section value={softReservedPct} color="orange" />}
              {softFreePct > 0 && <Progress.Section value={softFreePct} color="green" />}
            </Progress.Root>
          </BarWithMarker>
        }
        caption={
          overSoldSoft
            ? <><BlockSize size={otherUsage} /> + <BlockSize size={reservedSoft} /> = <BlockSize size={totalDemandSoft} /></>
            : <><BlockSize size={otherUsage} /> + <BlockSize size={reservedSoft} /> + <BlockSize size={freeSoft} /> = <BlockSize size={total} /></>
        }
        badge={overSoldSoft ? <Badge size="xs" color="orange" variant="light">{t('overSoldLabel')}</Badge> : undefined}
      />

      <BarRow
        label={t('reservedHardLabel')}
        bar={
          <BarWithMarker showDiskLimit={overSoldHard}>
            <Progress.Root size={barHeight}>
              {hardOtherPct > 0 && <Progress.Section value={hardOtherPct} color="gray" />}
              {hardReservedPct > 0 && <Progress.Section value={hardReservedPct} color="red" />}
              {hardFreePct > 0 && <Progress.Section value={hardFreePct} color="green" />}
            </Progress.Root>
          </BarWithMarker>
        }
        caption={
          overSoldHard
            ? <><BlockSize size={otherUsage} /> + <BlockSize size={reservedHard} /> = <BlockSize size={totalDemandHard} /></>
            : <><BlockSize size={otherUsage} /> + <BlockSize size={reservedHard} /> + <BlockSize size={freeHard} /> = <BlockSize size={total} /></>
        }
        badge={overSoldHard ? <Badge size="xs" color="red" variant="light">{t('overSoldLabel')}</Badge> : undefined}
      />

      <Group gap="md" wrap="wrap" style={{ paddingLeft: barStartOffset }}>
        <Group gap={4}>
          <Box w={8} h={8} style={{ borderRadius: 2, backgroundColor: 'var(--mantine-color-gray-5)' }} />
          <Text size="xs" c="dimmed">{t('otherUsageLabel')}</Text>
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
