import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Tabs, Stack, Text, Table, Button, Badge, TextInput, Group, Modal } from '@mantine/core'
import { IconUsers, IconBox, IconPhoto, IconDatabase, IconPlus, IconSettings } from '@tabler/icons-react'
import { BlockSize } from '../BlockSize'
import {
  getQuotaStatus,
  getQuotaStatusColor,
  getQuotaStatusLabelKey,
  type QuotaStatus,
} from '../../utils/quotaStatus'
import { useI18n } from '../../i18n'
import { EditQuotaModal } from '../EditQuotaModal'
import { BatchQuotaModal } from '../BatchQuotaModal'
import { DefaultQuotaModal } from '../DefaultQuotaModal'
import { getDeviceDefaultQuota } from '../../api'
import { DeviceUsage } from '../DeviceUsage'
import { ContainersTab } from './ContainersTab'
import { ImagesTab } from './ImagesTab'
import { VolumesTab } from './VolumesTab'
import { resolveHostUser, getErrorMessage } from '../../api'
import type { DeviceQuota, UserQuota } from '../../api/schemas'

interface DockerDetailTabsProps {
  hostId: string
  device: DeviceQuota
}

function syntheticUserQuota(uid: number, name: string): UserQuota {
  return {
    uid,
    name,
    block_hard_limit: 0,
    block_soft_limit: 0,
    block_current: 0,
    inode_hard_limit: 0,
    inode_soft_limit: 0,
    inode_current: 0,
    block_time_limit: 0,
    inode_time_limit: 0,
  }
}

const STATUS_ORDER: Record<QuotaStatus, number> = { ok: 0, warning: 1, over: 2 }

type UserSortColumn = 'uid' | 'name' | 'block_current' | 'block_hard_limit' | 'status'
type SortDirection = 'asc' | 'desc'

function compareUserQuota(
  a: UserQuota,
  b: UserQuota,
  col: UserSortColumn,
  dir: SortDirection
): number {
  let cmp = 0
  if (col === 'status') {
    cmp = STATUS_ORDER[getQuotaStatus(a)] - STATUS_ORDER[getQuotaStatus(b)]
  } else if (col === 'name') {
    cmp = a.name.localeCompare(b.name, undefined, { numeric: true })
  } else {
    const aVal = a[col] as number
    const bVal = b[col] as number
    cmp = aVal - bVal
  }
  return dir === 'asc' ? cmp : -cmp
}

export function DockerDetailTabs({ hostId, device }: DockerDetailTabsProps) {
  const { t } = useI18n()
  const [activeTab, setActiveTab] = useState<string | null>('users')
  const [search, setSearch] = useState('')
  const [editQuota, setEditQuota] = useState<UserQuota | null>(null)
  const [addQuotaOpened, setAddQuotaOpened] = useState(false)
  const [addQuotaUsername, setAddQuotaUsername] = useState('')
  const [addQuotaResolving, setAddQuotaResolving] = useState(false)
  const [addQuotaError, setAddQuotaError] = useState<string | null>(null)
  const [batchQuotaOpened, setBatchQuotaOpened] = useState(false)
  const [defaultQuotaOpened, setDefaultQuotaOpened] = useState(false)
  const [sortBy, setSortBy] = useState<UserSortColumn>('name')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')

  const { data: deviceDefault } = useQuery({
    queryKey: ['deviceDefaultQuota', hostId, device.name],
    queryFn: () => getDeviceDefaultQuota(hostId, device.name),
    enabled: !!hostId && !!device.name,
  })

  const users = device.user_quotas || []
  const filteredUsers = useMemo(() => {
    if (!search.trim()) return users
    const s = search.trim().toLowerCase()
    return users.filter(
      (q) => q.name.toLowerCase().includes(s) || String(q.uid).includes(s)
    )
  }, [users, search])

  const sortedUsers = useMemo(
    () => [...filteredUsers].sort((a, b) => compareUserQuota(a, b, sortBy, sortDirection)),
    [filteredUsers, sortBy, sortDirection]
  )

  function handleSort(column: UserSortColumn) {
    if (sortBy === column) {
      setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(column)
      setSortDirection('asc')
    }
  }

  async function handleAddQuotaContinue() {
    const username = addQuotaUsername.trim()
    if (!username || !hostId) return
    setAddQuotaError(null)
    setAddQuotaResolving(true)
    try {
      const resolved = await resolveHostUser(hostId, username)
      setAddQuotaOpened(false)
      setAddQuotaUsername('')
      setEditQuota(syntheticUserQuota(resolved.uid, resolved.name))
    } catch (err) {
      setAddQuotaError(getErrorMessage(err, t('userNotFound')))
    } finally {
      setAddQuotaResolving(false)
    }
  }

  return (
    <Stack gap="md">
      <Stack gap={2}>
        <Text size="sm" c="dimmed">
          {t('fstypeLabel')}: {device.fstype}
        </Text>
        <Text size="sm" c="dimmed">
          {t('mountPointsLabel')}: {device.mount_points.join(', ')}
        </Text>
        {device.usage && <DeviceUsage usage={device.usage} userQuotas={device.user_quotas} quotaFormat="docker" />}
      </Stack>

      <Tabs value={activeTab} onChange={setActiveTab}>
        <Tabs.List>
          <Tabs.Tab value="users" leftSection={<IconUsers size={16} />}>
            {t('usersTab')}
          </Tabs.Tab>
          <Tabs.Tab value="containers" leftSection={<IconBox size={16} />}>
            {t('containersTab')}
          </Tabs.Tab>
          <Tabs.Tab value="images" leftSection={<IconPhoto size={16} />}>
            {t('imagesTab')}
          </Tabs.Tab>
          <Tabs.Tab value="volumes" leftSection={<IconDatabase size={16} />}>
            {t('volumesTab')}
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="users" pt="md">
          <Stack gap="md">
            <Group gap="sm">
              <TextInput
                placeholder={t('searchByNameOrUid')}
                value={search}
                onChange={(e) => setSearch(e.currentTarget.value)}
                style={{ maxWidth: 300 }}
              />
              <Button
                leftSection={<IconPlus size={16} />}
                variant="light"
                onClick={() => {
                  setAddQuotaOpened(true)
                  setAddQuotaUsername('')
                  setAddQuotaError(null)
                }}
              >
                {t('addQuota')}
              </Button>
              <Button
                leftSection={<IconUsers size={16} />}
                variant="light"
                color="violet"
                onClick={() => setBatchQuotaOpened(true)}
              >
                {t('batchSetQuota')}
              </Button>
              <Button
                leftSection={<IconSettings size={16} />}
                variant="light"
                onClick={() => setDefaultQuotaOpened(true)}
              >
                {t('defaultQuota')}
              </Button>
            </Group>

            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th
                    style={{ cursor: 'pointer', userSelect: 'none' }}
                    onClick={() => handleSort('uid')}
                  >
                    <Group gap={4}>
                      {t('uid')}
                      {sortBy === 'uid' && (
                        <Text size="xs" c="dimmed">
                          {sortDirection === 'asc' ? '▲' : '▼'}
                        </Text>
                      )}
                    </Group>
                  </Table.Th>
                  <Table.Th
                    style={{ cursor: 'pointer', userSelect: 'none' }}
                    onClick={() => handleSort('name')}
                  >
                    <Group gap={4}>
                      {t('name')}
                      {sortBy === 'name' && (
                        <Text size="xs" c="dimmed">
                          {sortDirection === 'asc' ? '▲' : '▼'}
                        </Text>
                      )}
                    </Group>
                  </Table.Th>
                  <Table.Th
                    style={{ cursor: 'pointer', userSelect: 'none' }}
                    onClick={() => handleSort('block_current')}
                  >
                    <Group gap={4}>
                      {t('blockUsed')}
                      {sortBy === 'block_current' && (
                        <Text size="xs" c="dimmed">
                          {sortDirection === 'asc' ? '▲' : '▼'}
                        </Text>
                      )}
                    </Group>
                  </Table.Th>
                  <Table.Th
                    style={{ cursor: 'pointer', userSelect: 'none' }}
                    onClick={() => handleSort('block_hard_limit')}
                  >
                    <Group gap={4}>
                      {t('blockHard')}
                      {sortBy === 'block_hard_limit' && (
                        <Text size="xs" c="dimmed">
                          {sortDirection === 'asc' ? '▲' : '▼'}
                        </Text>
                      )}
                    </Group>
                  </Table.Th>
                  <Table.Th
                    style={{ cursor: 'pointer', userSelect: 'none' }}
                    onClick={() => handleSort('status')}
                  >
                    <Group gap={4}>
                      {t('status')}
                      {sortBy === 'status' && (
                        <Text size="xs" c="dimmed">
                          {sortDirection === 'asc' ? '▲' : '▼'}
                        </Text>
                      )}
                    </Group>
                  </Table.Th>
                  <Table.Th>{t('actions')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {sortedUsers.map((q) => {
                  const status = getQuotaStatus(q)
                  return (
                    <Table.Tr key={q.uid}>
                      <Table.Td>{q.uid}</Table.Td>
                      <Table.Td>{q.name}</Table.Td>
                      <Table.Td>
                        <BlockSize size={q.block_current} />
                      </Table.Td>
                      <Table.Td>
                        <BlockSize size={q.block_hard_limit * 1024} />
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
            {sortedUsers.length === 0 && (
              <Text size="sm" c="dimmed">
                {t('noUsersMatch')}
              </Text>
            )}
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="containers" pt="md">
          <ContainersTab hostId={hostId} />
        </Tabs.Panel>

        <Tabs.Panel value="images" pt="md">
          <ImagesTab hostId={hostId} />
        </Tabs.Panel>

        <Tabs.Panel value="volumes" pt="md">
          <VolumesTab hostId={hostId} />
        </Tabs.Panel>
      </Tabs>

      <Modal
        opened={addQuotaOpened}
        onClose={() => setAddQuotaOpened(false)}
        title={t('addQuotaForUser')}
        size="sm"
      >
        <Stack gap="md">
          <TextInput
            label={t('usernameLabel')}
            placeholder={t('usernameLabel')}
            value={addQuotaUsername}
            onChange={(e) => {
              setAddQuotaUsername(e.currentTarget.value)
              setAddQuotaError(null)
            }}
            onKeyDown={(e) => e.key === 'Enter' && handleAddQuotaContinue()}
          />
          {addQuotaError && (
            <Text size="sm" c="red">
              {addQuotaError}
            </Text>
          )}
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setAddQuotaOpened(false)}>
              {t('cancel')}
            </Button>
            <Button
              loading={addQuotaResolving}
              onClick={handleAddQuotaContinue}
              disabled={!addQuotaUsername.trim()}
            >
              {t('continue')}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <EditQuotaModal
        opened={editQuota !== null}
        onClose={() => setEditQuota(null)}
        hostId={hostId}
        deviceName={device.name}
        quota={editQuota}
        userQuotaFormat={device.user_quota_format}
        deviceDefault={deviceDefault ?? undefined}
      />

      <BatchQuotaModal
        opened={batchQuotaOpened}
        onClose={() => setBatchQuotaOpened(false)}
        hostId={hostId}
        device={device}
        deviceDefault={deviceDefault ?? undefined}
      />

      <DefaultQuotaModal
        opened={defaultQuotaOpened}
        onClose={() => setDefaultQuotaOpened(false)}
        hostId={hostId}
        device={device}
      />
    </Stack>
  )
}
