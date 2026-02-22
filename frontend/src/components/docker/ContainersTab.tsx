import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Stack, Text, Table, Loader, Alert, TextInput, Badge, Group } from '@mantine/core'
import { fetchDockerContainers } from '../../api'
import { BlockSize } from '../BlockSize'
import { useI18n } from '../../i18n'
import { UsageSummaryCards } from './UsageSummaryCard'
import type { DockerContainer } from '../../api/schemas'

interface ContainersTabProps {
  hostId: string
}

type SortField = 'name' | 'image' | 'status' | 'host_user_name' | 'size_bytes'
type SortDirection = 'asc' | 'desc'

function getStatusColor(status: string): string {
  switch (status.toLowerCase()) {
    case 'running':
      return 'green'
    case 'exited':
    case 'dead':
      return 'red'
    case 'paused':
      return 'yellow'
    case 'created':
    case 'restarting':
      return 'blue'
    default:
      return 'gray'
  }
}

export function ContainersTab({ hostId }: ContainersTabProps) {
  const { t } = useI18n()
  const [search, setSearch] = useState('')
  const [sortField, setSortField] = useState<SortField>('name')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')

  const { data, isLoading, error } = useQuery({
    queryKey: ['docker-containers', hostId],
    queryFn: () => fetchDockerContainers(hostId),
  })

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDirection('asc')
    }
  }

  const filteredAndSorted = useMemo(() => {
    if (!data) return []
    let list = data.containers
    if (search.trim()) {
      const s = search.trim().toLowerCase()
      list = list.filter(
        (c) =>
          c.name.toLowerCase().includes(s) ||
          c.image.toLowerCase().includes(s) ||
          (c.host_user_name?.toLowerCase() || '').includes(s) ||
          c.container_id.toLowerCase().includes(s)
      )
    }
    return [...list].sort((a, b) => {
      const dir = sortDirection === 'asc' ? 1 : -1
      switch (sortField) {
        case 'name':
          return a.name.localeCompare(b.name) * dir
        case 'image':
          return a.image.localeCompare(b.image) * dir
        case 'status':
          return a.status.localeCompare(b.status) * dir
        case 'host_user_name':
          return ((a.host_user_name || '') as string).localeCompare(b.host_user_name || '') * dir
        case 'size_bytes':
          return (a.size_bytes - b.size_bytes) * dir
        default:
          return 0
      }
    })
  }, [data, search, sortField, sortDirection])

  const SortableHeader = ({ field, children }: { field: SortField; children: React.ReactNode }) => (
    <Table.Th
      style={{ cursor: 'pointer', userSelect: 'none' }}
      onClick={() => handleSort(field)}
    >
      <Group gap={4}>
        {children}
        {sortField === field && (
          <Text size="xs" c="dimmed">
            {sortDirection === 'asc' ? '▲' : '▼'}
          </Text>
        )}
      </Group>
    </Table.Th>
  )

  if (isLoading) {
    return (
      <Stack align="center" gap="md" py="xl">
        <Loader size="lg" />
        <Text c="dimmed">{t('loading')}</Text>
      </Stack>
    )
  }

  if (error || !data) {
    return (
      <Alert color="red" title={t('error')}>
        {error instanceof Error ? error.message : t('failedToLoadDockerContainers')}
      </Alert>
    )
  }

  return (
    <Stack gap="md">
      <UsageSummaryCards
        totalBytes={data.total_bytes}
        attributedBytes={data.attributed_bytes}
        unattributedBytes={data.unattributed_bytes}
      />

      <TextInput
        placeholder={t('searchContainers')}
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
        style={{ maxWidth: 300 }}
      />

      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('containerId')}</Table.Th>
            <SortableHeader field="name">{t('containerName')}</SortableHeader>
            <SortableHeader field="image">{t('containerImage')}</SortableHeader>
            <SortableHeader field="status">{t('containerStatus')}</SortableHeader>
            <SortableHeader field="host_user_name">{t('owner')}</SortableHeader>
            <SortableHeader field="size_bytes">{t('size')}</SortableHeader>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {filteredAndSorted.map((c: DockerContainer) => (
            <Table.Tr key={c.container_id}>
              <Table.Td>
                <Text size="xs" ff="monospace" c="dimmed">
                  {c.container_id.slice(0, 12)}
                </Text>
              </Table.Td>
              <Table.Td>{c.name}</Table.Td>
              <Table.Td>
                <Text size="sm" style={{ maxWidth: 200 }} truncate>
                  {c.image}
                </Text>
              </Table.Td>
              <Table.Td>
                <Badge size="sm" color={getStatusColor(c.status)} variant="light">
                  {c.status}
                </Badge>
              </Table.Td>
              <Table.Td>
                {c.host_user_name ? (
                  <Text size="sm">{c.host_user_name}</Text>
                ) : (
                  <Text size="sm" c="dimmed" fs="italic">
                    {t('unattributed')}
                  </Text>
                )}
              </Table.Td>
              <Table.Td>
                <BlockSize size={c.size_bytes} />
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>

      {filteredAndSorted.length === 0 && (
        <Text size="sm" c="dimmed">
          {t('noContainersMatch')}
        </Text>
      )}
    </Stack>
  )
}
