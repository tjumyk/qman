import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Stack, Text, Table, Loader, Alert, TextInput, Badge, Group } from '@mantine/core'
import { fetchDockerVolumes } from '../../api'
import { BlockSize } from '../BlockSize'
import { useI18n } from '../../i18n'
import { UsageSummaryCards } from './UsageSummaryCard'
import type { DockerVolume } from '../../api/schemas'

interface VolumesTabProps {
  hostId: string
}

type SortField = 'volume_name' | 'host_user_name' | 'size_bytes' | 'ref_count' | 'attribution_source'
type SortDirection = 'asc' | 'desc'

function getAttributionSourceColor(source: string | null): string {
  switch (source?.toLowerCase()) {
    case 'label':
      return 'blue'
    case 'container':
      return 'green'
    default:
      return 'gray'
  }
}

export function VolumesTab({ hostId }: VolumesTabProps) {
  const { t } = useI18n()
  const [search, setSearch] = useState('')
  const [sortField, setSortField] = useState<SortField>('volume_name')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')

  const { data, isLoading, error } = useQuery({
    queryKey: ['docker-volumes', hostId],
    queryFn: () => fetchDockerVolumes(hostId),
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
    let list = data.volumes
    if (search.trim()) {
      const s = search.trim().toLowerCase()
      list = list.filter(
        (v) =>
          v.volume_name.toLowerCase().includes(s) ||
          (v.host_user_name?.toLowerCase() || '').includes(s)
      )
    }
    return [...list].sort((a, b) => {
      const dir = sortDirection === 'asc' ? 1 : -1
      switch (sortField) {
        case 'volume_name':
          return a.volume_name.localeCompare(b.volume_name) * dir
        case 'host_user_name':
          return ((a.host_user_name || '') as string).localeCompare(b.host_user_name || '') * dir
        case 'size_bytes':
          return (a.size_bytes - b.size_bytes) * dir
        case 'ref_count':
          return (a.ref_count - b.ref_count) * dir
        case 'attribution_source':
          return ((a.attribution_source || '') as string).localeCompare(
            b.attribution_source || ''
          ) * dir
        default:
          return 0
      }
    })
  }, [data, search, sortField, sortDirection])

  const SortableHeader = ({ field, children }: { field: SortField; children: React.ReactNode }) => (
    <Table.Th style={{ cursor: 'pointer', userSelect: 'none' }} onClick={() => handleSort(field)}>
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
        {error instanceof Error ? error.message : t('failedToLoadDockerVolumes')}
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
        placeholder={t('searchVolumes')}
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
        style={{ maxWidth: 300 }}
      />

      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <SortableHeader field="volume_name">{t('volumeName')}</SortableHeader>
            <SortableHeader field="host_user_name">{t('owner')}</SortableHeader>
            <SortableHeader field="size_bytes">{t('size')}</SortableHeader>
            <SortableHeader field="ref_count">{t('refCount')}</SortableHeader>
            <SortableHeader field="attribution_source">{t('attributionSource')}</SortableHeader>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {filteredAndSorted.map((v: DockerVolume) => (
            <Table.Tr key={v.volume_name}>
              <Table.Td>
                <Text size="sm" style={{ maxWidth: 250 }} truncate>
                  {v.volume_name}
                </Text>
              </Table.Td>
              <Table.Td>
                {v.host_user_name ? (
                  <Text size="sm">{v.host_user_name}</Text>
                ) : (
                  <Text size="sm" c="dimmed" fs="italic">
                    {t('unattributed')}
                  </Text>
                )}
              </Table.Td>
              <Table.Td>
                <BlockSize size={v.size_bytes} />
              </Table.Td>
              <Table.Td>
                <Badge size="sm" variant="light" color={v.ref_count > 0 ? 'blue' : 'gray'}>
                  {v.ref_count}
                </Badge>
              </Table.Td>
              <Table.Td>
                {v.attribution_source ? (
                  <Badge
                    size="sm"
                    color={getAttributionSourceColor(v.attribution_source)}
                    variant="light"
                  >
                    {v.attribution_source}
                  </Badge>
                ) : (
                  <Text size="sm" c="dimmed">
                    -
                  </Text>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>

      {filteredAndSorted.length === 0 && (
        <Text size="sm" c="dimmed">
          {t('noVolumesMatch')}
        </Text>
      )}
    </Stack>
  )
}
