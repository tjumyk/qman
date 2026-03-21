import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Stack,
  Text,
  Loader,
  Alert,
  Group,
  Button,
  Table,
  Select,
  Checkbox,
  Drawer,
  ScrollArea,
  Code,
  Pagination,
  SegmentedControl,
  Switch,
  Badge,
} from '@mantine/core'
import { IconBrandDocker } from '@tabler/icons-react'
import { useMemo, useState } from 'react'
import {
  fetchHosts,
  fetchAdminMappings,
  fetchAdminDockerUsageReviewQueue,
  fetchAdminDockerUsageEvents,
  postAdminDockerUsageAttribute,
  deleteAdminDockerUsageAttribute,
  getErrorMessage,
  type DockerUsageEntityType,
} from '../api'
import type { DockerUsageReviewQueueItem } from '../api/schemas'
import { useI18n } from '../i18n'
import { notifications } from '@mantine/notifications'
import { DockerEventReviewCell, DockerEventAutoCell } from '../components/docker/DockerUsageEventStatusCells'

function entityKey(item: DockerUsageReviewQueueItem): string {
  if (item.entity_type === 'container') return item.container_id
  if (item.entity_type === 'image') return item.image_id
  return item.volume_name
}

function attributionSummary(item: DockerUsageReviewQueueItem): string {
  if (item.entity_type === 'container') {
    const u = item.host_user_name
    const uid = item.uid
    if (u != null && u !== '') return uid != null ? `${u} (${uid})` : u
    return '—'
  }
  if (item.entity_type === 'image') {
    const u = item.puller_host_user_name
    const uid = item.puller_uid
    if (u != null && u !== '') return uid != null ? `${u} (${uid})` : u
    return '—'
  }
  const u = item.host_user_name
  const uid = item.uid
  if (u != null && u !== '') return uid != null ? `${u} (${uid})` : u
  return '—'
}

export function AdminDockerUsageReviewPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [hostId, setHostId] = useState<string | null>(null)
  const [entityType, setEntityType] = useState<DockerUsageEntityType>('container')
  const [page, setPage] = useState(1)
  const [drawerItem, setDrawerItem] = useState<DockerUsageReviewQueueItem | null>(null)
  const [includeUsed, setIncludeUsed] = useState(false)
  const [includeResolved, setIncludeResolved] = useState(false)
  const [assigneeValue, setAssigneeValue] = useState<string | null>(null)
  const [cascade, setCascade] = useState(true)

  const { data: hosts, isLoading: hostsLoading, error: hostsError } = useQuery({
    queryKey: ['hosts'],
    queryFn: fetchHosts,
  })

  const { data: mappings } = useQuery({
    queryKey: ['admin-mappings'],
    queryFn: fetchAdminMappings,
  })

  const {
    data: queue,
    isLoading: queueLoading,
    error: queueError,
  } = useQuery({
    queryKey: ['admin-docker-usage-review', hostId, entityType, page],
    queryFn: () =>
      fetchAdminDockerUsageReviewQueue(hostId!, { entityType, page, pageSize: 25 }),
    enabled: !!hostId,
  })

  const drawerKey = drawerItem ? entityKey(drawerItem) : null
  const {
    data: eventsData,
    isLoading: eventsLoading,
    error: eventsError,
  } = useQuery({
    queryKey: [
      'admin-docker-usage-events',
      hostId,
      drawerItem?.entity_type,
      drawerKey,
      includeUsed,
      includeResolved,
    ],
    queryFn: () =>
      fetchAdminDockerUsageEvents(hostId!, {
        entityType: drawerItem!.entity_type,
        entityId: drawerKey!,
        includeUsed,
        includeResolved,
        volumeName: drawerItem!.entity_type === 'volume' ? drawerItem!.volume_name : undefined,
      }),
    enabled: !!hostId && !!drawerItem && !!drawerKey,
  })

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

  const assignMutation = useMutation({
    mutationFn: async () => {
      if (!hostId || !drawerItem || !assigneeValue) throw new Error('missing')
      const tab = assigneeValue.indexOf('\t')
      const oauthUserId = Number(assigneeValue.slice(0, tab))
      const hostUserName = assigneeValue.slice(tab + 1)
      const base = {
        entity_type: drawerItem.entity_type,
        oauth_user_id: oauthUserId,
        host_user_name: hostUserName,
        cascade: drawerItem.entity_type === 'volume' ? false : cascade,
      }
      if (drawerItem.entity_type === 'container') {
        return postAdminDockerUsageAttribute(hostId, {
          ...base,
          container_id: drawerItem.container_id,
        })
      }
      if (drawerItem.entity_type === 'image') {
        return postAdminDockerUsageAttribute(hostId, {
          ...base,
          image_id: drawerItem.image_id,
        })
      }
      return postAdminDockerUsageAttribute(hostId, {
        ...base,
        volume_name: drawerItem.volume_name,
      })
    },
    onSuccess: async () => {
      notifications.show({ color: 'green', message: t('dockerUsageReviewAssigned') })
      await queryClient.invalidateQueries({ queryKey: ['admin-docker-usage-review'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-docker-usage-events'] })
    },
    onError: (e: unknown) => {
      notifications.show({
        color: 'red',
        message: getErrorMessage(e, t('dockerUsageReviewAssignFailed')),
      })
    },
  })

  const clearMutation = useMutation({
    mutationFn: async () => {
      if (!hostId || !drawerItem) throw new Error('missing')
      const id = entityKey(drawerItem)
      return deleteAdminDockerUsageAttribute(hostId, {
        entityType: drawerItem.entity_type,
        entityId: id,
        cascade: drawerItem.entity_type === 'volume' ? false : cascade,
        volumeName: drawerItem.entity_type === 'volume' ? drawerItem.volume_name : undefined,
      })
    },
    onSuccess: async () => {
      notifications.show({ color: 'teal', message: t('dockerUsageReviewCleared') })
      await queryClient.invalidateQueries({ queryKey: ['admin-docker-usage-review'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-docker-usage-events'] })
    },
    onError: (e: unknown) => {
      notifications.show({
        color: 'red',
        message: getErrorMessage(e, t('dockerUsageReviewClearFailed')),
      })
    },
  })

  const hostSelectData = useMemo(
    () => (hosts ?? []).map((h) => ({ value: h.id, label: h.id })),
    [hosts]
  )

  return (
    <Stack gap="md">
      <Group gap="sm">
        <IconBrandDocker size={28} aria-hidden />
        <div>
          <Text fw={600} size="lg">
            {t('dockerUsageReviewTitle')}
          </Text>
          <Text size="sm" c="dimmed">
            {t('dockerUsageReviewDescription')}
          </Text>
        </div>
      </Group>

      {hostsError && (
        <Alert color="red" title={t('error')}>
          {getErrorMessage(hostsError, t('failedToLoadQuotas'))}
        </Alert>
      )}

      <Group align="flex-end" wrap="wrap">
        <Select
          label={t('hosts')}
          placeholder={t('dockerUsageReviewPickHost')}
          data={hostSelectData}
          value={hostId}
          onChange={(v) => {
            setHostId(v)
            setPage(1)
            setDrawerItem(null)
            setAssigneeValue(null)
          }}
          searchable
          w={{ base: '100%', sm: 280 }}
          disabled={hostsLoading}
        />
        <div>
          <Text size="sm" fw={500} mb={6}>
            {t('dockerUsageReviewEntityType')}
          </Text>
          <SegmentedControl
            value={entityType}
            onChange={(v) => {
              setEntityType(v as DockerUsageEntityType)
              setPage(1)
              setDrawerItem(null)
              setAssigneeValue(null)
            }}
            data={[
              { label: t('dockerUsageReviewContainers'), value: 'container' },
              { label: t('dockerUsageReviewImages'), value: 'image' },
              { label: t('dockerUsageReviewVolumes'), value: 'volume' },
            ]}
          />
        </div>
      </Group>

      {!hostId && (
        <Text size="sm" c="dimmed">
          {t('dockerUsageReviewPickHostHint')}
        </Text>
      )}

      {hostId && queueError && (
        <Alert color="red" title={t('error')}>
          {getErrorMessage(queueError, t('dockerUsageReviewQueueFailed'))}
        </Alert>
      )}

      {hostId && queueLoading && (
        <Group>
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            {t('loading')}
          </Text>
        </Group>
      )}

      {hostId && queue && (
        <>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('dockerUsageReviewColId')}</Table.Th>
                <Table.Th>{t('dockerUsageReviewColUnresolved')}</Table.Th>
                <Table.Th>{t('dockerUsageReviewColAttribution')}</Table.Th>
                <Table.Th w={120}>{t('actions')}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {queue.items.length === 0 ? (
                <Table.Tr>
                  <Table.Td colSpan={4}>
                    <Text size="sm" c="dimmed">
                      {t('dockerUsageReviewEmpty')}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ) : (
                queue.items.map((item) => (
                  <Table.Tr key={entityKey(item)}>
                    <Table.Td>
                      <Code fz="xs" style={{ wordBreak: 'break-all' }}>
                        {entityKey(item)}
                      </Code>
                    </Table.Td>
                    <Table.Td>
                      <Badge variant="light">{item.unresolved_events}</Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{attributionSummary(item)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Button size="xs" variant="light" onClick={() => setDrawerItem(item)}>
                        {t('dockerUsageReviewDetails')}
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                ))
              )}
            </Table.Tbody>
          </Table>
          {queue.total > queue.page_size && (
            <Pagination
              total={Math.ceil(queue.total / queue.page_size)}
              value={page}
              onChange={setPage}
              size="sm"
            />
          )}
        </>
      )}

      <Drawer
        opened={!!drawerItem}
        onClose={() => {
          setDrawerItem(null)
          setAssigneeValue(null)
        }}
        title={t('dockerUsageReviewDrawerTitle')}
        position="right"
        size="lg"
      >
        {drawerItem && (
          <Stack gap="md">
            <Code block style={{ wordBreak: 'break-all' }}>
              {entityKey(drawerItem)}
            </Code>
            <Text size="sm">
              {t('dockerUsageReviewCurrentAttribution')}: {attributionSummary(drawerItem)}
            </Text>

            <Group gap="xl">
              <Switch
                label={t('dockerUsageReviewIncludeUsed')}
                checked={includeUsed}
                onChange={(e) => setIncludeUsed(e.currentTarget.checked)}
              />
              <Switch
                label={t('dockerEntityDetailIncludeResolved')}
                checked={includeResolved}
                onChange={(e) => setIncludeResolved(e.currentTarget.checked)}
              />
            </Group>

            {eventsError && (
              <Alert color="red" title={t('error')}>
                {getErrorMessage(eventsError, t('dockerUsageReviewEventsFailed'))}
              </Alert>
            )}
            {eventsLoading && (
              <Group>
                <Loader size="sm" />
                <Text size="sm" c="dimmed">
                  {t('loading')}
                </Text>
              </Group>
            )}
            {eventsData && (
              <ScrollArea h={280}>
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
                    {eventsData.events.map((ev) => (
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

            <Select
              label={t('dockerUsageReviewAssignee')}
              placeholder={t('dockerUsageReviewAssigneePlaceholder')}
              data={mappingOptions}
              value={assigneeValue}
              onChange={setAssigneeValue}
              searchable
              disabled={mappingOptions.length === 0}
            />
            {mappingOptions.length === 0 && (
              <Text size="xs" c="dimmed">
                {t('dockerUsageReviewNoMappings')}
              </Text>
            )}

            {drawerItem.entity_type !== 'volume' && (
              <Checkbox
                label={t('dockerUsageReviewCascade')}
                checked={cascade}
                onChange={(e) => setCascade(e.currentTarget.checked)}
              />
            )}

            <Group>
              <Button
                onClick={() => assignMutation.mutate()}
                loading={assignMutation.isPending}
                disabled={!assigneeValue}
              >
                {t('dockerUsageReviewAssign')}
              </Button>
              <Button
                variant="default"
                color="gray"
                onClick={() => clearMutation.mutate()}
                loading={clearMutation.isPending}
              >
                {t('dockerUsageReviewClear')}
              </Button>
            </Group>
          </Stack>
        )}
      </Drawer>
    </Stack>
  )
}
