import { useState, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Stack,
  Text,
  Table,
  Button,
  Loader,
  Alert,
  TextInput,
  Badge,
  Group,
} from '@mantine/core'
import { fetchQuotas } from '../api'
import { BlockSize } from '../components/BlockSize'
import { INodeSize } from '../components/INodeSize'
import { getQuotaStatus, getQuotaStatusColor, getQuotaStatusLabelKey } from '../utils/quotaStatus'
import { useI18n } from '../i18n'
import { EditQuotaModal } from '../components/EditQuotaModal'
import type { UserQuota } from '../api/schemas'

export function DeviceUserListPage() {
  const { hostId, deviceName } = useParams<{ hostId: string; deviceName: string }>()
  const [search, setSearch] = useState('')
  const [editQuota, setEditQuota] = useState<UserQuota | null>(null)
  const { t } = useI18n()

  const { data, isLoading, error } = useQuery({ queryKey: ['quotas'], queryFn: fetchQuotas })

  const device = useMemo(() => {
    if (!hostId || !deviceName || !data) return null
    const payload = data[hostId]
    if (!payload?.results) return null
    return payload.results.find((d) => d.name === deviceName) ?? null
  }, [data, hostId, deviceName])

  const users = useMemo(() => {
    const list = device?.user_quotas ?? []
    if (!search.trim()) return list
    const s = search.trim().toLowerCase()
    return list.filter(
      (q) =>
        q.name.toLowerCase().includes(s) ||
        String(q.uid).includes(s)
    )
  }, [device?.user_quotas, search])

  if (!hostId || !deviceName) return <Alert color="red">{t('missingHostOrDevice')}</Alert>
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
        {error instanceof Error ? error.message : t('failedToLoadQuotas')}
      </Alert>
    )
  }
  if (!device) {
    return <Alert color="red">{t('deviceNotFound')}</Alert>
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text size="lg" fw={600}>
          {hostId} / {deviceName}
        </Text>
      </Group>
      <Text size="sm" c="dimmed">
        {device.fstype} · {device.mount_points.join(', ')}
      </Text>
      <TextInput
        placeholder={t('searchByNameOrUid')}
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
        style={{ maxWidth: 300 }}
      />
      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('uid')}</Table.Th>
            <Table.Th>{t('name')}</Table.Th>
            <Table.Th>{t('blockUsed')}</Table.Th>
            <Table.Th>{t('blockSoft')}</Table.Th>
            <Table.Th>{t('blockHard')}</Table.Th>
            <Table.Th>{t('inodeUsed')}</Table.Th>
            <Table.Th>{t('inodeSoft')}</Table.Th>
            <Table.Th>{t('inodeHard')}</Table.Th>
            <Table.Th>{t('status')}</Table.Th>
            <Table.Th>{t('actions')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {users.map((q) => {
            const status = getQuotaStatus(q)
            return (
              <Table.Tr key={q.uid}>
                <Table.Td>{q.uid}</Table.Td>
                <Table.Td>{q.name}</Table.Td>
                <Table.Td>
                  <BlockSize size={q.block_current * 1024} />
                </Table.Td>
                <Table.Td>
                  <BlockSize size={q.block_soft_limit * 1024} />
                </Table.Td>
                <Table.Td>
                  <BlockSize size={q.block_hard_limit * 1024} />
                </Table.Td>
                <Table.Td>
                  <INodeSize size={q.inode_current} />
                </Table.Td>
                <Table.Td>
                  <INodeSize size={q.inode_soft_limit} />
                </Table.Td>
                <Table.Td>
                  <INodeSize size={q.inode_hard_limit} />
                </Table.Td>
                <Table.Td>
                  <Badge size="sm" color={getQuotaStatusColor(status)} variant="light">
                    {t(getQuotaStatusLabelKey(status))}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Button size="xs" variant="light" onClick={() => setEditQuota(q)}>
                    {t('edit')}
                  </Button>
                </Table.Td>
              </Table.Tr>
            )
          })}
        </Table.Tbody>
      </Table>
      {users.length === 0 && (
        <Text size="sm" c="dimmed">
          {t('noUsersMatch')}
        </Text>
      )}
      <EditQuotaModal
        opened={editQuota !== null}
        onClose={() => setEditQuota(null)}
        hostId={hostId}
        deviceName={deviceName}
        quota={editQuota}
      />
    </Stack>
  )
}
