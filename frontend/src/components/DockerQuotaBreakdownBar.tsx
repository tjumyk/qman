import type { ReactNode } from 'react'
import { Box, Group, Progress, Stack, Text, Tooltip } from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { BlockSize } from './BlockSize'
import { useI18n } from '../i18n'
import type { UserQuota } from '../api/schemas'

function pct(total: number, value: number): number {
  return total > 0 ? (value / total) * 100 : 0
}

function DockerBreakdownBarRow({
  label,
  bar,
  isMobile,
  labelWidth,
  labelBarGap,
}: {
  label: string
  bar: ReactNode
  isMobile: boolean
  labelWidth: number
  labelBarGap: number
}) {
  return (
    <Stack gap={4} style={{ width: '100%' }}>
      {isMobile ? (
        <>
          <Text size="sm" fw={500}>
            {label}
          </Text>
          <Box style={{ width: '100%', minWidth: 0 }}>{bar}</Box>
        </>
      ) : (
        <Box style={{ display: 'flex', alignItems: 'center', gap: labelBarGap }}>
          <Text size="sm" fw={500} style={{ width: labelWidth, flexShrink: 0 }}>
            {label}
          </Text>
          <Box style={{ flex: 1, minWidth: 0 }}>{bar}</Box>
        </Box>
      )}
    </Stack>
  )
}

interface DockerQuotaBreakdownBarProps {
  quota: UserQuota
}

export function DockerQuotaBreakdownBar({ quota }: DockerQuotaBreakdownBarProps) {
  const { t } = useI18n()
  const isMobile = useMediaQuery('(max-width: 36em)')
  const barHeight = 'sm'
  const labelWidth = 115
  const labelBarGap = 12
  const barStartOffset = labelWidth + labelBarGap

  const blockLimit =
    quota.block_hard_limit > 0 ? quota.block_hard_limit : quota.block_soft_limit
  const blockLimitBytes = blockLimit * 1024
  const used = quota.block_current
  const containerB = quota.docker_container_bytes ?? 0
  const layerB = quota.docker_image_layer_bytes ?? 0
  const volumeB = quota.docker_volume_bytes ?? 0
  const decomposed = containerB + layerB + volumeB
  if (decomposed === 0 && used > 0) {
    return null
  }

  const maxBytes =
    blockLimitBytes > 0 ? Math.max(blockLimitBytes, used, 1) : Math.max(used, 1)
  const remaining = blockLimitBytes > 0 ? Math.max(0, blockLimitBytes - used) : 0

  const segmentTooltip = (segmentLabel: string, size: number) => (
    <>
      {segmentLabel}: <BlockSize size={size} />
    </>
  )

  const containerPct = pct(maxBytes, containerB)
  const layerPct = pct(maxBytes, layerB)
  const volumePct = pct(maxBytes, volumeB)
  const remainingPct = blockLimitBytes > 0 ? pct(maxBytes, remaining) : 0

  if (
    containerPct <= 0 &&
    layerPct <= 0 &&
    volumePct <= 0 &&
    remainingPct <= 0
  ) {
    return null
  }

  return (
    <Stack gap="sm">
      <DockerBreakdownBarRow
        label={t('blockUsage')}
        bar={
          <Progress.Root size={barHeight}>
            {containerPct > 0 && (
              <Tooltip
                withArrow
                label={segmentTooltip(t('dockerUsageContainerWorkLayer'), containerB)}
              >
                <Progress.Section value={containerPct} color="blue" />
              </Tooltip>
            )}
            {layerPct > 0 && (
              <Tooltip
                withArrow
                label={segmentTooltip(t('dockerUsageImageLayers'), layerB)}
              >
                <Progress.Section value={layerPct} color="grape" />
              </Tooltip>
            )}
            {volumePct > 0 && (
              <Tooltip
                withArrow
                label={segmentTooltip(t('dockerUsageVolumes'), volumeB)}
              >
                <Progress.Section value={volumePct} color="cyan" />
              </Tooltip>
            )}
            {remainingPct > 0 && (
              <Tooltip
                withArrow
                label={segmentTooltip(t('dockerQuotaRemainingLabel'), remaining)}
              >
                <Progress.Section value={remainingPct} color="green" />
              </Tooltip>
            )}
          </Progress.Root>
        }
        isMobile={!!isMobile}
        labelWidth={labelWidth}
        labelBarGap={labelBarGap}
      />
      <Group
        gap="md"
        wrap="wrap"
        style={{ paddingLeft: isMobile ? 0 : barStartOffset }}
      >
        <Group gap={4}>
          <Box
            w={8}
            h={8}
            style={{ borderRadius: 2, backgroundColor: 'var(--mantine-color-blue-5)' }}
          />
          <Text size="xs" c="dimmed">
            {t('dockerUsageContainerWorkLayer')}
          </Text>
        </Group>
        <Group gap={4}>
          <Box
            w={8}
            h={8}
            style={{ borderRadius: 2, backgroundColor: 'var(--mantine-color-grape-5)' }}
          />
          <Text size="xs" c="dimmed">
            {t('dockerUsageImageLayers')}
          </Text>
        </Group>
        <Group gap={4}>
          <Box
            w={8}
            h={8}
            style={{ borderRadius: 2, backgroundColor: 'var(--mantine-color-cyan-5)' }}
          />
          <Text size="xs" c="dimmed">
            {t('dockerUsageVolumes')}
          </Text>
        </Group>
        {blockLimitBytes > 0 && (
          <Group gap={4}>
            <Box
              w={8}
              h={8}
              style={{ borderRadius: 2, backgroundColor: 'var(--mantine-color-green-5)' }}
            />
            <Text size="xs" c="dimmed">
              {t('dockerQuotaRemainingLabel')}
            </Text>
          </Group>
        )}
      </Group>
    </Stack>
  )
}
