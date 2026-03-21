import { useQueries } from '@tanstack/react-query'
import {
  Modal,
  Tabs,
  Stack,
  Text,
  Loader,
  Alert,
  ScrollArea,
  Code,
  Table,
  Switch,
  Group,
  Badge,
  Paper,
  Title,
} from '@mantine/core'
import { CodeHighlight } from '@mantine/code-highlight'
import { useState } from 'react'
import {
  fetchDockerInspect,
  fetchDockerAttributionDetail,
  fetchAdminDockerUsageEvents,
  getErrorMessage,
  type DockerUsageEntityType,
} from '../../api'
import { useI18n } from '../../i18n'
import { DockerEventReviewCell, DockerEventAutoCell } from './DockerUsageEventStatusCells'

export type DockerEntityDetailModalProps = {
  opened: boolean
  onClose: () => void
  hostId: string
  entityType: DockerUsageEntityType
  entityId: string
}

export function DockerEntityDetailModal({
  opened,
  onClose,
  hostId,
  entityType,
  entityId,
}: DockerEntityDetailModalProps) {
  const { t } = useI18n()
  const [includeUsed, setIncludeUsed] = useState(true)
  const [includeResolved, setIncludeResolved] = useState(true)

  const [inspectQ, attrQ, eventsQ] = useQueries({
    queries: [
      {
        queryKey: ['docker-inspect', hostId, entityType, entityId],
        queryFn: () => fetchDockerInspect(hostId, { kind: entityType, id: entityId }),
        enabled: opened && !!hostId && !!entityId,
      },
      {
        queryKey: ['docker-attribution-detail', hostId, entityType, entityId],
        queryFn: () => fetchDockerAttributionDetail(hostId, { entityType, entityId }),
        enabled: opened && !!hostId && !!entityId,
      },
      {
        queryKey: [
          'admin-docker-usage-events',
          hostId,
          entityType,
          entityId,
          includeUsed,
          includeResolved,
        ],
        queryFn: () =>
          fetchAdminDockerUsageEvents(hostId, {
            entityType,
            entityId,
            includeUsed,
            includeResolved,
            volumeName: entityType === 'volume' ? entityId : undefined,
          }),
        enabled: opened && !!hostId && !!entityId,
      },
    ],
  })

  const inspectJson =
    inspectQ.data?.inspect != null
      ? JSON.stringify(inspectQ.data.inspect, null, 2)
      : null

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('dockerEntityDetailTitle')}
      size="xl"
      scrollAreaComponent={ScrollArea.Autosize}
    >
      <Tabs defaultValue="inspect">
        <Tabs.List>
          <Tabs.Tab value="inspect">{t('dockerEntityDetailTabInspect')}</Tabs.Tab>
          <Tabs.Tab value="attribution">{t('dockerEntityDetailTabAttribution')}</Tabs.Tab>
          <Tabs.Tab value="events">{t('dockerEntityDetailTabEvents')}</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="inspect" pt="md">
          {inspectQ.isLoading && (
            <Group>
              <Loader size="sm" />
              <Text size="sm" c="dimmed">
                {t('loading')}
              </Text>
            </Group>
          )}
          {inspectQ.error && (
            <Alert color="red" title={t('error')}>
              {getErrorMessage(inspectQ.error, t('dockerEntityDetailInspectFailed'))}
            </Alert>
          )}
          {inspectJson != null && (
            <ScrollArea h={420}>
              <CodeHighlight
                code={inspectJson}
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
          )}
        </Tabs.Panel>

        <Tabs.Panel value="attribution" pt="md">
          {attrQ.isLoading && (
            <Group>
              <Loader size="sm" />
              <Text size="sm" c="dimmed">
                {t('loading')}
              </Text>
            </Group>
          )}
          {attrQ.error && (
            <Alert color="red" title={t('error')}>
              {getErrorMessage(attrQ.error, t('dockerEntityDetailAttributionFailed'))}
            </Alert>
          )}
          {attrQ.data && (
            <Stack gap="md">
              <Paper p="md" withBorder>
                <Title order={6} mb="xs">
                  {t('dockerEntityDetailAutoAttribution')}
                </Title>
                {attrQ.data.auto == null ? (
                  <Text size="sm" c="dimmed">
                    {t('dockerEntityDetailNoAuto')}
                  </Text>
                ) : (
                  <Code block style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                    {JSON.stringify(attrQ.data.auto, null, 2)}
                  </Code>
                )}
              </Paper>
              <Paper p="md" withBorder>
                <Title order={6} mb="xs">
                  {t('dockerEntityDetailManualOverride')}
                </Title>
                {attrQ.data.override == null ? (
                  <Text size="sm" c="dimmed">
                    {t('dockerEntityDetailNoOverride')}
                  </Text>
                ) : (
                  <Code block style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                    {JSON.stringify(attrQ.data.override, null, 2)}
                  </Code>
                )}
              </Paper>
            </Stack>
          )}
        </Tabs.Panel>

        <Tabs.Panel value="events" pt="md">
          <Stack gap="sm">
            <Switch
              label={t('dockerEntityDetailIncludeUsed')}
              checked={includeUsed}
              onChange={(e) => setIncludeUsed(e.currentTarget.checked)}
            />
            <Switch
              label={t('dockerEntityDetailIncludeResolved')}
              checked={includeResolved}
              onChange={(e) => setIncludeResolved(e.currentTarget.checked)}
            />
            {eventsQ.isLoading && (
              <Group>
                <Loader size="sm" />
                <Text size="sm" c="dimmed">
                  {t('loading')}
                </Text>
              </Group>
            )}
            {eventsQ.error && (
              <Alert color="red" title={t('error')}>
                {getErrorMessage(eventsQ.error, t('dockerEntityDetailEventsFailed'))}
              </Alert>
            )}
            {eventsQ.data && (
              <ScrollArea h={360}>
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
                    {eventsQ.data.events.map((ev) => (
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
                          <Text size="xs" lineClamp={3} style={{ wordBreak: 'break-all' }}>
                            {ev.payload}
                          </Text>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </ScrollArea>
            )}
          </Stack>
        </Tabs.Panel>
      </Tabs>
    </Modal>
  )
}
