import { Group, Text, Tooltip } from '@mantine/core'
import { IconHelp } from '@tabler/icons-react'
import { useI18n } from '../i18n'
import { GraceEndRelative } from './GraceEndRelative'
import type { UserQuota } from '../api/schemas'

export interface QuotaGraceDisplayProps {
  /** User quota with block_time_limit and inode_time_limit */
  quota: UserQuota
  /** Show help tooltips next to each grace line (e.g. on My Usage cards) */
  showTooltips?: boolean
}

export function QuotaGraceDisplay({
  quota,
  showTooltips = false,
}: QuotaGraceDisplayProps) {
  const { t } = useI18n()
  const overBlockSoft =
    quota.block_soft_limit > 0 && quota.block_current >= quota.block_soft_limit * 1024
  const overInodeSoft =
    quota.inode_soft_limit > 0 && quota.inode_current >= quota.inode_soft_limit
  const blockGraceVisible = quota.block_time_limit > 0 || overBlockSoft
  const inodeGraceVisible = quota.inode_time_limit > 0 || overInodeSoft

  if (!blockGraceVisible && !inodeGraceVisible) return null

  const blockGraceContent = (
    <Text size="xs" span>
      <Text component="span" c="dimmed" inherit>
        {t('blockGrace')}:
      </Text>{' '}
      {quota.block_time_limit > 0 ? (
        <Text component="span" c="yellow" fw={600} inherit>
          <GraceEndRelative time={quota.block_time_limit} />
        </Text>
      ) : (
        <Text component="span" c="red" fw={600} inherit>
          {t('graceExpired')}
        </Text>
      )}
    </Text>
  )

  const inodeGraceContent = (
    <Text size="xs" span>
      <Text component="span" c="dimmed" inherit>
        {t('inodeGrace')}:
      </Text>{' '}
      {quota.inode_time_limit > 0 ? (
        <Text component="span" c="yellow" fw={600} inherit>
          <GraceEndRelative time={quota.inode_time_limit} />
        </Text>
      ) : (
        <Text component="span" c="red" fw={600} inherit>
          {t('graceExpired')}
        </Text>
      )}
    </Text>
  )

  const wrapWithTooltip = (content: React.ReactNode, active: boolean) =>
    showTooltips ? (
      <Group gap={4} wrap="nowrap" align="center">
        {content}
        <Tooltip
          label={t(active ? 'graceTooltipActive' : 'graceTooltipExpired')}
          withArrow
          openDelay={300}
        >
          <Group gap={0} style={{ cursor: 'help' }} component="span" display="inline-flex">
            <IconHelp size={14} style={{ opacity: 0.7 }} />
          </Group>
        </Tooltip>
      </Group>
    ) : (
      content
    )

  return (
    <Group gap="xs" wrap="wrap">
      {blockGraceVisible && wrapWithTooltip(blockGraceContent, quota.block_time_limit > 0)}
      {inodeGraceVisible && wrapWithTooltip(inodeGraceContent, quota.inode_time_limit > 0)}
    </Group>
  )
}
