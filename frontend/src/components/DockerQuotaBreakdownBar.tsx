import { Box, Group, Progress, Text, Tooltip } from '@mantine/core'
import { BlockSize } from './BlockSize'
import { useI18n } from '../i18n'
import type { UserQuota } from '../api/schemas'

function pct(total: number, value: number): number {
  return total > 0 ? (value / total) * 100 : 0
}

interface DockerQuotaBreakdownBarProps {
  quota: UserQuota
}

/**
 * Multi-segment block usage for Docker (My usage cards). Unused quota is the default
 * Progress track (grey). Pair with {@link DockerQuotaBreakdownLegend} below used/total.
 */
export function DockerQuotaBreakdownBar({ quota }: DockerQuotaBreakdownBarProps) {
  const { t } = useI18n()
  const barHeight = 'sm'

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

  const segmentTooltip = (segmentLabel: string, size: number) => (
    <>
      {segmentLabel}: <BlockSize size={size} />
    </>
  )

  const containerPct = pct(maxBytes, containerB)
  const layerPct = pct(maxBytes, layerB)
  const volumePct = pct(maxBytes, volumeB)

  if (containerPct <= 0 && layerPct <= 0 && volumePct <= 0) {
    return null
  }

  return (
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
    </Progress.Root>
  )
}

export function DockerQuotaBreakdownLegend({ quota }: DockerQuotaBreakdownBarProps) {
  const { t } = useI18n()
  const blockLimit =
    quota.block_hard_limit > 0 ? quota.block_hard_limit : quota.block_soft_limit
  const blockLimitBytes = blockLimit * 1024

  return (
    <Group gap="md" wrap="wrap">
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
            style={{
              borderRadius: 2,
              backgroundColor: 'var(--mantine-color-gray-4)',
            }}
          />
          <Text size="xs" c="dimmed">
            {t('dockerQuotaRemainingLabel')}
          </Text>
        </Group>
      )}
    </Group>
  )
}
