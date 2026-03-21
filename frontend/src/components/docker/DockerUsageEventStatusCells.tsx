import { Badge, Table } from '@mantine/core'
import type { DockerUsageReviewEvent } from '../../api/schemas'
import { useI18n } from '../../i18n'

export function DockerEventReviewCell({ ev }: { ev: DockerUsageReviewEvent }) {
  const { t } = useI18n()
  const reviewed = ev.manual_resolved_at != null && ev.manual_resolved_at !== ''
  return (
    <Table.Td>
      <Badge size="xs" color={reviewed ? 'teal' : 'yellow'} variant="light">
        {reviewed ? t('dockerEventReview_reviewed') : t('dockerEventReview_pending')}
      </Badge>
    </Table.Td>
  )
}

export function DockerEventAutoCell({ ev }: { ev: DockerUsageReviewEvent }) {
  const { t } = useI18n()
  const consumed = ev.used_for_auto_attribution
  return (
    <Table.Td>
      <Badge size="xs" color={consumed ? 'blue' : 'gray'} variant="light">
        {consumed ? t('dockerEventAuto_consumed') : t('dockerEventAuto_unused')}
      </Badge>
    </Table.Td>
  )
}
