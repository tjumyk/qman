import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Stack,
  Text,
  Table,
  Button,
  TextInput,
  Badge,
  Group,
  Modal,
  Box,
  Tooltip,
} from '@mantine/core'
import { IconPlus, IconSettings, IconUsers } from '@tabler/icons-react'
import { resolveHostUser, getErrorMessage, getDeviceDefaultQuota } from '../api'
import { BlockSize } from './BlockSize'
import { INodeSize } from './INodeSize'
import {
  getQuotaStatus,
  getQuotaStatusColor,
  getQuotaStatusLabelKey,
  type QuotaStatus,
} from '../utils/quotaStatus'
import { useI18n } from '../i18n'
import { EditQuotaModal } from './EditQuotaModal'
import { BatchQuotaModal } from './BatchQuotaModal'
import {
  DefaultQuotaModal,
  isDeviceDefaultNonEmpty,
} from './DefaultQuotaModal'
import type { DeviceQuota, UserQuota } from '../api/schemas'

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

type SortColumn =
  | 'uid'
  | 'name'
  | 'block_current'
  | 'block_soft_limit'
  | 'block_hard_limit'
  | 'inode_current'
  | 'inode_soft_limit'
  | 'inode_hard_limit'
  | 'status'

const REDUCED_SORT_COLUMNS: SortColumn[] = [
  'uid',
  'name',
  'block_current',
  'block_hard_limit',
  'status',
]

function compareQuota(a: UserQuota, b: UserQuota, col: SortColumn, dir: 'asc' | 'desc'): number {
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
  if (cmp !== 0) return dir === 'asc' ? cmp : -cmp
  // Stable sort: tie-break by uid
  return a.uid - b.uid
}

export interface UserQuotaTableProps {
  hostId: string
  device: DeviceQuota
}

export function UserQuotaTable({ hostId, device }: UserQuotaTableProps) {
  const { t } = useI18n()
  const [search, setSearch] = useState('')
  const [editQuota, setEditQuota] = useState<UserQuota | null>(null)
  const [addQuotaOpened, setAddQuotaOpened] = useState(false)
  const [addQuotaUsername, setAddQuotaUsername] = useState('')
  const [addQuotaResolving, setAddQuotaResolving] = useState(false)
  const [addQuotaError, setAddQuotaError] = useState<string | null>(null)
  const [batchQuotaOpened, setBatchQuotaOpened] = useState(false)
  const [defaultQuotaOpened, setDefaultQuotaOpened] = useState(false)
  const [sortBy, setSortBy] = useState<SortColumn>('name')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')

  const { data: deviceDefault } = useQuery({
    queryKey: ['deviceDefaultQuota', hostId, device.name],
    queryFn: () => getDeviceDefaultQuota(hostId, device.name),
    enabled: !!hostId && !!device.name,
  })

  const isReducedColumns =
    device.user_quota_format === 'zfs' || device.user_quota_format === 'docker'

  const effectiveSortBy = useMemo((): SortColumn => {
    if (isReducedColumns && !REDUCED_SORT_COLUMNS.includes(sortBy)) {
      return 'name'
    }
    return sortBy
  }, [isReducedColumns, sortBy])

  const users = useMemo(() => {
    const list = device.user_quotas ?? []
    if (!search.trim()) return list
    const s = search.trim().toLowerCase()
    return list.filter(
      (q) =>
        q.name.toLowerCase().includes(s) ||
        String(q.uid).includes(s)
    )
  }, [device.user_quotas, search])

  const sortedUsers = useMemo(() => {
    return [...users].sort((a, b) => compareQuota(a, b, effectiveSortBy, sortDirection))
  }, [users, effectiveSortBy, sortDirection])

  function handleSort(column: SortColumn) {
    if (isReducedColumns && !REDUCED_SORT_COLUMNS.includes(column)) return
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

  const showDefaultSummary =
    deviceDefault !== undefined && isDeviceDefaultNonEmpty(deviceDefault)

  return (
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
      </Group>

      {deviceDefault !== undefined && (
        <Box
          py="xs"
          px="sm"
          style={{ borderRadius: 4 }}
          bg="var(--mantine-color-default-hover)"
        >
          <Group justify="space-between" wrap="wrap" gap="sm">
            <Group gap="xs" wrap="wrap">
              {showDefaultSummary && deviceDefault ? (
                <>
                  <Text size="sm" c="dimmed" span>
                    {t('defaultQuota')}:
                  </Text>
                  {isReducedColumns ? (
                    <Text size="sm" span>
                      <BlockSize size={deviceDefault.block_hard_limit * 1024} />
                    </Text>
                  ) : (
                    <>
                      <Text size="sm" span>
                        {t('blockSoft')}{' '}
                        <BlockSize size={deviceDefault.block_soft_limit * 1024} />
                        {' · '}
                        {t('blockHard')}{' '}
                        <BlockSize size={deviceDefault.block_hard_limit * 1024} />
                      </Text>
                      <Text size="sm" span>
                        {t('inodeSoft')}{' '}
                        <INodeSize size={deviceDefault.inode_soft_limit} />
                        {' · '}
                        {t('inodeHard')}{' '}
                        <INodeSize size={deviceDefault.inode_hard_limit} />
                      </Text>
                    </>
                  )}
                </>
              ) : (
                <Text size="sm" c="dimmed">
                  {t('defaultQuotaNotSet')}
                </Text>
              )}
            </Group>
            <Button
              leftSection={<IconSettings size={16} />}
              variant="light"
              size="xs"
              onClick={() => setDefaultQuotaOpened(true)}
            >
              {showDefaultSummary ? t('edit') : t('defaultQuota')}
            </Button>
          </Group>
        </Box>
      )}

      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>
              <Group
                gap={4}
                style={{ cursor: 'pointer', userSelect: 'none' }}
                onClick={() => handleSort('uid')}
              >
                {t('uid')}
                {effectiveSortBy === 'uid' && (
                  <Text size="xs" c="dimmed">
                    {sortDirection === 'asc' ? '▲' : '▼'}
                  </Text>
                )}
              </Group>
            </Table.Th>
            <Table.Th>
              <Group
                gap={4}
                style={{ cursor: 'pointer', userSelect: 'none' }}
                onClick={() => handleSort('name')}
              >
                {t('name')}
                {effectiveSortBy === 'name' && (
                  <Text size="xs" c="dimmed">
                    {sortDirection === 'asc' ? '▲' : '▼'}
                  </Text>
                )}
              </Group>
            </Table.Th>
            <Table.Th>
              <Group
                gap={4}
                style={{ cursor: 'pointer', userSelect: 'none' }}
                onClick={() => handleSort('block_current')}
              >
                {t('blockUsed')}
                {effectiveSortBy === 'block_current' && (
                  <Text size="xs" c="dimmed">
                    {sortDirection === 'asc' ? '▲' : '▼'}
                  </Text>
                )}
              </Group>
            </Table.Th>
            {!isReducedColumns && (
              <Table.Th>
                <Group
                  gap={4}
                  style={{ cursor: 'pointer', userSelect: 'none' }}
                  onClick={() => handleSort('block_soft_limit')}
                >
                  {t('blockSoft')}
                  {effectiveSortBy === 'block_soft_limit' && (
                    <Text size="xs" c="dimmed">
                      {sortDirection === 'asc' ? '▲' : '▼'}
                    </Text>
                  )}
                </Group>
              </Table.Th>
            )}
            <Table.Th>
              <Group
                gap={4}
                style={{ cursor: 'pointer', userSelect: 'none' }}
                onClick={() => handleSort('block_hard_limit')}
              >
                {t('blockHard')}
                {effectiveSortBy === 'block_hard_limit' && (
                  <Text size="xs" c="dimmed">
                    {sortDirection === 'asc' ? '▲' : '▼'}
                  </Text>
                )}
              </Group>
            </Table.Th>
            {!isReducedColumns && (
              <>
                <Table.Th>
                  <Group
                    gap={4}
                    style={{ cursor: 'pointer', userSelect: 'none' }}
                    onClick={() => handleSort('inode_current')}
                  >
                    {t('inodeUsed')}
                    {effectiveSortBy === 'inode_current' && (
                      <Text size="xs" c="dimmed">
                        {sortDirection === 'asc' ? '▲' : '▼'}
                      </Text>
                    )}
                  </Group>
                </Table.Th>
                <Table.Th>
                  <Group
                    gap={4}
                    style={{ cursor: 'pointer', userSelect: 'none' }}
                    onClick={() => handleSort('inode_soft_limit')}
                  >
                    {t('inodeSoft')}
                    {effectiveSortBy === 'inode_soft_limit' && (
                      <Text size="xs" c="dimmed">
                        {sortDirection === 'asc' ? '▲' : '▼'}
                      </Text>
                    )}
                  </Group>
                </Table.Th>
                <Table.Th>
                  <Group
                    gap={4}
                    style={{ cursor: 'pointer', userSelect: 'none' }}
                    onClick={() => handleSort('inode_hard_limit')}
                  >
                    {t('inodeHard')}
                    {effectiveSortBy === 'inode_hard_limit' && (
                      <Text size="xs" c="dimmed">
                        {sortDirection === 'asc' ? '▲' : '▼'}
                      </Text>
                    )}
                  </Group>
                </Table.Th>
              </>
            )}
            <Table.Th>
              <Group
                gap={4}
                style={{ cursor: 'pointer', userSelect: 'none' }}
                onClick={() => handleSort('status')}
              >
                {t('status')}
                {effectiveSortBy === 'status' && (
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
            const def = showDefaultSummary ? deviceDefault ?? null : null
            const blockSoftAbove = !!(
              def &&
              !isReducedColumns &&
              def.block_soft_limit > 0 &&
              q.block_soft_limit > def.block_soft_limit
            )
            const blockHardAbove = !!(
              def &&
              def.block_hard_limit > 0 &&
              q.block_hard_limit > def.block_hard_limit
            )
            const inodeSoftAbove = !!(
              def &&
              !isReducedColumns &&
              def.inode_soft_limit > 0 &&
              q.inode_soft_limit > def.inode_soft_limit
            )
            const inodeHardAbove = !!(
              def &&
              !isReducedColumns &&
              def.inode_hard_limit > 0 &&
              q.inode_hard_limit > def.inode_hard_limit
            )
            const limitCellStyle = (above: boolean) =>
              above
                ? { backgroundColor: 'var(--mantine-color-yellow-0)' }
                : undefined
            const wrapLimit = (above: boolean, content: React.ReactNode) =>
              above ? (
                <Tooltip label={t('aboveDefault')} withArrow openDelay={300}>
                  <span style={{ display: 'inline-block' }}>{content}</span>
                </Tooltip>
              ) : (
                content
              )
            return (
              <Table.Tr key={q.uid}>
                <Table.Td>{q.uid}</Table.Td>
                <Table.Td>{q.name}</Table.Td>
                <Table.Td>
                  <BlockSize size={q.block_current} />
                </Table.Td>
                {!isReducedColumns && (
                  <Table.Td style={limitCellStyle(blockSoftAbove)}>
                    {wrapLimit(
                      blockSoftAbove,
                      <BlockSize size={q.block_soft_limit * 1024} />
                    )}
                  </Table.Td>
                )}
                <Table.Td style={limitCellStyle(blockHardAbove)}>
                  {wrapLimit(
                    blockHardAbove,
                    <BlockSize size={q.block_hard_limit * 1024} />
                  )}
                </Table.Td>
                {!isReducedColumns && (
                  <>
                    <Table.Td>
                      <INodeSize size={q.inode_current} />
                    </Table.Td>
                    <Table.Td style={limitCellStyle(inodeSoftAbove)}>
                      {wrapLimit(
                        inodeSoftAbove,
                        <INodeSize size={q.inode_soft_limit} />
                      )}
                    </Table.Td>
                    <Table.Td style={limitCellStyle(inodeHardAbove)}>
                      {wrapLimit(
                        inodeHardAbove,
                        <INodeSize size={q.inode_hard_limit} />
                      )}
                    </Table.Td>
                  </>
                )}
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
