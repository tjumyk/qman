import { useQueries, useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Modal,
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
  Select,
  Checkbox,
  Button,
  Box,
} from '@mantine/core'
import { CodeHighlight } from '@mantine/code-highlight'
import { useEffect, useMemo, useState } from 'react'
import {
  fetchDockerInspect,
  fetchDockerAttributionDetail,
  fetchAdminDockerUsageEvents,
  fetchAdminMappings,
  postAdminDockerUsageAttribute,
  deleteAdminDockerUsageAttribute,
  getErrorMessage,
  type DockerUsageEntityType,
} from '../../api'
import { useI18n } from '../../i18n'
import { DockerEventReviewCell, DockerEventAutoCell } from './DockerUsageEventStatusCells'
import { notifications } from '@mantine/notifications'

export type DockerEntityDetailModalProps = {
  opened: boolean
  onClose: () => void
  hostId: string
  entityType: DockerUsageEntityType
  entityId: string
  /** Parent list queries to refresh (e.g. docker-containers for ContainersTab). Modal always refreshes its own detail/events. */
  onAttributionChanged?: () => void | Promise<void>
}

export function DockerEntityDetailModal({
  opened,
  onClose,
  hostId,
  entityType,
  entityId,
  onAttributionChanged,
}: DockerEntityDetailModalProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [includeUsed, setIncludeUsed] = useState(true)
  const [includeResolved, setIncludeResolved] = useState(true)
  const [assigneeValue, setAssigneeValue] = useState<string | null>(null)
  const [cascade, setCascade] = useState(true)

  const { data: mappings } = useQuery({
    queryKey: ['admin-mappings'],
    queryFn: fetchAdminMappings,
    enabled: opened,
  })

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

  useEffect(() => {
    setCascade(entityType !== 'volume')
  }, [entityType])

  useEffect(() => {
    setAssigneeValue(null)
  }, [hostId, entityType, entityId])

  useEffect(() => {
    const o = attrQ.data?.override
    if (!o) {
      setAssigneeValue(null)
      return
    }
    if (!mappings) return
    const oauthId =
      typeof o.resolved_by_oauth_user_id === 'number' ? o.resolved_by_oauth_user_id : null
    const hostUser =
      (typeof o.host_user_name === 'string' && o.host_user_name) ||
      (typeof o.puller_host_user_name === 'string' && o.puller_host_user_name) ||
      null
    if (oauthId == null || !hostUser) {
      setAssigneeValue(null)
      return
    }
    const row = mappings.find(
      (m) =>
        m.host_id === hostId &&
        m.oauth_user_id === oauthId &&
        m.host_user_name === hostUser
    )
    setAssigneeValue(row ? `${row.oauth_user_id}\t${row.host_user_name}` : null)
  }, [attrQ.data?.override, mappings, hostId])

  const mappingOptions = useMemo(() => {
    if (!hostId || !mappings) return []
    return mappings
      .filter((m) => m.host_id === hostId)
      .map((m) => ({
        value: `${m.oauth_user_id}\t${m.host_user_name}`,
        label:
          m.oauth_user_name != null && m.oauth_user_name !== ''
            ? `${m.oauth_user_name} → ${m.host_user_name}`
            : `${m.oauth_user_id} → ${m.host_user_name}`,
      }))
  }, [hostId, mappings])

  const invalidateAttributionQueries = async () => {
    await queryClient.invalidateQueries({
      queryKey: ['docker-attribution-detail', hostId, entityType, entityId],
    })
    await queryClient.invalidateQueries({
      queryKey: [
        'admin-docker-usage-events',
        hostId,
        entityType,
        entityId,
      ],
    })
    await queryClient.invalidateQueries({ queryKey: ['admin-docker-usage-review'] })
    await onAttributionChanged?.()
  }

  const assignMutation = useMutation({
    mutationFn: async () => {
      if (!assigneeValue) throw new Error('missing assignee')
      const tab = assigneeValue.indexOf('\t')
      const oauthUserId = Number(assigneeValue.slice(0, tab))
      const hostUserName = assigneeValue.slice(tab + 1)
      const base = {
        entity_type: entityType,
        oauth_user_id: oauthUserId,
        host_user_name: hostUserName,
        cascade: entityType === 'volume' ? false : cascade,
      }
      if (entityType === 'container') {
        return postAdminDockerUsageAttribute(hostId, { ...base, container_id: entityId })
      }
      if (entityType === 'image') {
        return postAdminDockerUsageAttribute(hostId, { ...base, image_id: entityId })
      }
      return postAdminDockerUsageAttribute(hostId, { ...base, volume_name: entityId })
    },
    onSuccess: async () => {
      notifications.show({ color: 'green', message: t('dockerUsageReviewAssigned') })
      await invalidateAttributionQueries()
    },
    onError: (e: unknown) => {
      notifications.show({
        color: 'red',
        message: getErrorMessage(e, t('dockerUsageReviewAssignFailed')),
      })
    },
  })

  const clearMutation = useMutation({
    mutationFn: async () =>
      deleteAdminDockerUsageAttribute(hostId, {
        entityType,
        entityId,
        cascade: entityType === 'volume' ? false : cascade,
        volumeName: entityType === 'volume' ? entityId : undefined,
      }),
    onSuccess: async () => {
      notifications.show({ color: 'teal', message: t('dockerUsageReviewCleared') })
      await invalidateAttributionQueries()
    },
    onError: (e: unknown) => {
      notifications.show({
        color: 'red',
        message: getErrorMessage(e, t('dockerUsageReviewClearFailed')),
      })
    },
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
      size="95%"
      styles={{
        content: { maxWidth: 'min(95vw, 1400px)' },
        body: { paddingTop: 'var(--mantine-spacing-md)' },
      }}
      scrollAreaComponent={ScrollArea.Autosize}
    >
      <Box
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(280px, 1fr) minmax(320px, 1fr)',
          gap: 'var(--mantine-spacing-md)',
          alignItems: 'stretch',
          minHeight: 560,
        }}
      >
        <Paper withBorder p="md" style={{ minHeight: 560, display: 'flex', flexDirection: 'column' }}>
          <Title order={6} mb="sm">
            {t('dockerEntityDetailTabInspect')}
          </Title>
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
            <ScrollArea flex={1} style={{ minHeight: 0 }} type="auto">
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
        </Paper>

        <Stack gap="md" style={{ minHeight: 560 }}>
          <Paper withBorder p="md">
            <Stack gap="md">
              <Title order={6}>{t('dockerEntityDetailTabAttribution')}</Title>
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
                <>
                  <div>
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
                  </div>
                  <div>
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
                  </div>
                  <Stack gap="sm">
                    <Select
                      label={t('dockerUsageReviewAssignee')}
                      placeholder={t('dockerUsageReviewAssigneePlaceholder')}
                      data={mappingOptions}
                      value={assigneeValue}
                      onChange={setAssigneeValue}
                      searchable
                      clearable
                      disabled={mappingOptions.length === 0}
                    />
                    {mappingOptions.length === 0 && (
                      <Text size="xs" c="dimmed">
                        {t('dockerUsageReviewNoMappings')}
                      </Text>
                    )}
                    {entityType !== 'volume' && (
                      <Checkbox
                        label={t('dockerUsageReviewCascade')}
                        checked={cascade}
                        onChange={(e) => setCascade(e.currentTarget.checked)}
                      />
                    )}
                    <Group gap="sm">
                      <Button
                        size="xs"
                        onClick={() => assignMutation.mutate()}
                        loading={assignMutation.isPending}
                        disabled={!assigneeValue}
                      >
                        {t('dockerUsageReviewAssign')}
                      </Button>
                      <Button
                        size="xs"
                        variant="light"
                        color="gray"
                        onClick={() => clearMutation.mutate()}
                        loading={clearMutation.isPending}
                        disabled={attrQ.data.override == null}
                      >
                        {t('dockerUsageReviewClear')}
                      </Button>
                    </Group>
                  </Stack>
                </>
              )}
            </Stack>
          </Paper>

          <Paper withBorder p="md" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            <Title order={6} mb="sm">
              {t('dockerEntityDetailTabEvents')}
            </Title>
            <Stack gap="sm" style={{ flex: 1, minHeight: 0 }}>
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
                <ScrollArea flex={1} style={{ minHeight: 240 }} type="auto">
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
          </Paper>
        </Stack>
      </Box>
    </Modal>
  )
}
