import { Card, Text, Progress, Stack, Group, Badge } from '@mantine/core'
import { BlockSize } from '../BlockSize'
import { useI18n } from '../../i18n'

interface UsageSummaryCardProps {
  label: string
  bytes: number
  totalBytes?: number
  color?: string
  badge?: string
  badgeColor?: string
}

export function UsageSummaryCard({
  label,
  bytes,
  totalBytes,
  color = 'blue',
  badge,
  badgeColor,
}: UsageSummaryCardProps) {
  const { t } = useI18n()
  const pct = totalBytes && totalBytes > 0 ? Math.min((bytes / totalBytes) * 100, 100) : 0

  return (
    <Card shadow="sm" padding="md" radius="md" withBorder>
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start">
          <Text size="sm" c="dimmed" fw={500}>
            {label}
          </Text>
          {badge && (
            <Badge size="xs" color={badgeColor} variant="light">
              {badge}
            </Badge>
          )}
        </Group>
        <Text size="xl" fw={700}>
          <BlockSize size={bytes} />
        </Text>
        {totalBytes !== undefined && totalBytes > 0 && (
          <>
            <Progress value={pct} size="sm" color={color} />
            <Text size="xs" c="dimmed">
              {Math.round(pct)}% {t('ofTotal')}
            </Text>
          </>
        )}
      </Stack>
    </Card>
  )
}

interface UsageSummaryCardsProps {
  totalBytes: number
  attributedBytes: number
  unattributedBytes: number
}

export function UsageSummaryCards({
  totalBytes,
  attributedBytes,
  unattributedBytes,
}: UsageSummaryCardsProps) {
  const { t } = useI18n()

  return (
    <Group gap="md" grow>
      <UsageSummaryCard
        label={t('totalBytes')}
        bytes={totalBytes}
        color="blue"
      />
      <UsageSummaryCard
        label={t('attributedBytes')}
        bytes={attributedBytes}
        totalBytes={totalBytes}
        color="green"
      />
      <UsageSummaryCard
        label={t('unattributedBytes')}
        bytes={unattributedBytes}
        totalBytes={totalBytes}
        color="orange"
      />
    </Group>
  )
}
