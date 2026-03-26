import {
  Alert,
  Badge,
  Group,
  Loader,
  Modal,
  ScrollArea,
  Stack,
  Switch,
  Table,
  Text,
  UnstyledButton,
} from '@mantine/core'
import { CodeHighlight } from '@mantine/code-highlight'
import type {
  DockerUsageReviewEvent,
  DockerUsageReviewEventsResponse,
} from '../../api/schemas'
import { getErrorMessage } from '../../api'
import { useI18n } from '../../i18n'
import { useState } from 'react'

/** Pretty-print for CodeHighlight; falls back to raw string if not valid JSON. */
function formatPayloadAsJson(payload: string): string {
  const trimmed = payload.trim()
  if (trimmed === '') return ''
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2)
  } catch {
    return payload
  }
}

function DockerEventReviewCell({ ev }: { ev: DockerUsageReviewEvent }) {
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

function DockerEventAutoCell({ ev }: { ev: DockerUsageReviewEvent }) {
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

export type DockerEntityEventsPanelProps = {
  includeUsed: boolean
  includeResolved: boolean
  onIncludeUsedChange: (value: boolean) => void
  onIncludeResolvedChange: (value: boolean) => void
  includeUsedLabel: string
  includeResolvedLabel: string
  isLoading: boolean
  error: unknown | null | undefined
  /** Fallback string for `getErrorMessage` when the events request fails. */
  eventsErrorFallback: string
  data: DockerUsageReviewEventsResponse | undefined
  /** When set, wraps the table in `ScrollArea` with this height. */
  tableScrollHeight?: number
  /** `stack`: vertical switches; `group`: horizontal row (e.g. drawer). */
  switchLayout?: 'stack' | 'group'
}

export function DockerEntityEventsPanel({
  includeUsed,
  includeResolved,
  onIncludeUsedChange,
  onIncludeResolvedChange,
  includeUsedLabel,
  includeResolvedLabel,
  isLoading,
  error,
  eventsErrorFallback,
  data,
  tableScrollHeight,
  switchLayout = 'stack',
}: DockerEntityEventsPanelProps) {
  const { t } = useI18n()
  const [payloadModalCode, setPayloadModalCode] = useState<string | null>(null)

  const switches =
    switchLayout === 'group' ? (
      <Group gap="xl">
        <Switch
          label={includeUsedLabel}
          checked={includeUsed}
          onChange={(e) => onIncludeUsedChange(e.currentTarget.checked)}
        />
        <Switch
          label={includeResolvedLabel}
          checked={includeResolved}
          onChange={(e) => onIncludeResolvedChange(e.currentTarget.checked)}
        />
      </Group>
    ) : (
      [
        <Switch
          key="include-used"
          label={includeUsedLabel}
          checked={includeUsed}
          onChange={(e) => onIncludeUsedChange(e.currentTarget.checked)}
        />,
        <Switch
          key="include-resolved"
          label={includeResolvedLabel}
          checked={includeResolved}
          onChange={(e) => onIncludeResolvedChange(e.currentTarget.checked)}
        />,
      ]
    )

  const table = data && (
    <Table striped fz="xs">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('dockerUsageReviewColSource')}</Table.Th>
          <Table.Th>{t('dockerUsageReviewColWhen')}</Table.Th>
          <Table.Th>{t('dockerEventColReview')}</Table.Th>
          <Table.Th>{t('dockerEventColAuto')}</Table.Th>
          <Table.Th>{t('dockerUsageReviewColPayload')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {data.events.map((ev) => (
          <Table.Tr key={`${ev.source}-${ev.id}`}>
            <Table.Td>
              <Badge size="xs">{ev.source}</Badge>
            </Table.Td>
            <Table.Td>
              <Text size="xs" lineClamp={2}>
                {ev.event_ts ?? ev.created_at ?? '—'}
              </Text>
            </Table.Td>
            <DockerEventReviewCell ev={ev} />
            <DockerEventAutoCell ev={ev} />
            <Table.Td>
              <UnstyledButton
                type="button"
                onClick={() => setPayloadModalCode(formatPayloadAsJson(ev.payload))}
                style={{ width: '100%', textAlign: 'left' }}
              >
                <Text
                  size="xs"
                  lineClamp={3}
                  style={{ wordBreak: 'break-all' }}
                  c="blue"
                  td="underline"
                >
                  {ev.payload}
                </Text>
              </UnstyledButton>
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )

  const tableBlock =
    tableScrollHeight != null && table ? (
      <ScrollArea h={tableScrollHeight}>{table}</ScrollArea>
    ) : (
      table
    )

  return (
    <Stack gap="sm">
      <Modal
        opened={payloadModalCode !== null}
        onClose={() => setPayloadModalCode(null)}
        title={t('dockerEventPayloadModalTitle')}
        size="lg"
      >
        <ScrollArea h={420}>
          <CodeHighlight
            code={payloadModalCode ?? ''}
            language="json"
            withCopyButton
            styles={{
              code: {
                backgroundColor: 'var(--mantine-color-default-hover)',
                borderRadius: 4,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              },
            }}
          />
        </ScrollArea>
      </Modal>
      {switches}
      {isLoading && (
        <Group>
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            {t('loading')}
          </Text>
        </Group>
      )}
      {error != null ? (
        <Alert color="red" title={t('error')}>
          {getErrorMessage(error, eventsErrorFallback)}
        </Alert>
      ) : null}
      {tableBlock}
    </Stack>
  )
}
