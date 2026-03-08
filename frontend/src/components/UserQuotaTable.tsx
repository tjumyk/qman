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
  MultiSelect,
  ScrollArea,
  Card,
} from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
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
import { GraceDuration } from './GraceDuration'
import { QuotaGraceDisplay } from './QuotaGraceDisplay'
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

function compareQuota(
  a: UserQuota,
  b: UserQuota,
  col: SortColumn,
  dir: 'asc' | 'desc',
  statusByUid?: Map<number, QuotaStatus>
): number {
  let cmp = 0
  if (col === 'status') {
    const statusA = statusByUid?.get(a.uid) ?? getQuotaStatus(a)
    const statusB = statusByUid?.get(b.uid) ?? getQuotaStatus(b)
    cmp = STATUS_ORDER[statusA] - STATUS_ORDER[statusB]
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
  const [statusFilter, setStatusFilter] = useState<QuotaStatus[]>([])

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

  const statusByUid = useMemo(() => {
    const list = device.user_quotas ?? []
    return new Map(list.map((q) => [q.uid, getQuotaStatus(q)]))
  }, [device.user_quotas])

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

  const filteredByStatus = useMemo(() => {
    if (statusFilter.length === 0) return users
    const set = new Set(statusFilter)
    return users.filter((q) => {
      const st = statusByUid.get(q.uid)
      return st !== undefined && set.has(st)
    })
  }, [users, statusFilter, statusByUid])

  const sortedUsers = useMemo(() => {
    return [...filteredByStatus].sort((a, b) =>
      compareQuota(a, b, effectiveSortBy, sortDirection, statusByUid)
    )
  }, [filteredByStatus, effectiveSortBy, sortDirection, statusByUid])

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

  const hasDeviceGrace =
    !isReducedColumns &&
    device.user_quota_info &&
    (device.user_quota_info.block_grace > 0 || device.user_quota_info.inode_grace > 0)

  const showDeviceSummaryBox = deviceDefault !== undefined || hasDeviceGrace
  const isMobile = useMediaQuery('(max-width: 36em)')

  return (
    <Stack gap="md">
      {showDeviceSummaryBox && (
        <Box
          py="xs"
          px="sm"
          style={{ borderRadius: 4 }}
          bg="var(--mantine-color-default-hover)"
        >
          {deviceDefault !== undefined && (
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
                {showDefaultSummary ? t('editDefaultQuota') : t('defaultQuota')}
              </Button>
            </Group>
          )}
          {hasDeviceGrace && (
            <Group gap="md" wrap="wrap" mt={deviceDefault !== undefined ? 'xs' : 0}>
              {device.user_quota_info!.block_grace > 0 && (
                <Text size="sm" span>
                  <Text component="span" c="dimmed" inherit>
                    {t('blockGrace')}:
                  </Text>{' '}
                  <GraceDuration seconds={device.user_quota_info!.block_grace} />
                </Text>
              )}
              {device.user_quota_info!.inode_grace > 0 && (
                <Text size="sm" span>
                  <Text component="span" c="dimmed" inherit>
                    {t('inodeGrace')}:
                  </Text>{' '}
                  <GraceDuration seconds={device.user_quota_info!.inode_grace} />
                </Text>
              )}
            </Group>
          )}
        </Box>
      )}

      <Group gap="sm" wrap="wrap" align="flex-end">
        <TextInput
          placeholder={t('searchByNameOrUid')}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          w={{ base: '100%', sm: 300 }}
        />
        <MultiSelect
          placeholder={t('filterByStatus')}
          clearable
          data={[
            { value: 'ok', label: t('statusOk') },
            { value: 'warning', label: t('statusNearLimit') },
            { value: 'over', label: t('statusOverLimit') },
          ]}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v as QuotaStatus[])}
          style={{ minWidth: 160 }}
          w={{ base: '100%', sm: undefined }}
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

      {isMobile ? (
        sortedUsers.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t('noUsersMatch')}
          </Text>
        ) : (
          <Stack gap="xs">
            {sortedUsers.map((q) => {
              const status = statusByUid.get(q.uid) ?? getQuotaStatus(q)
              return (
                <Card key={q.uid} padding="sm" withBorder>
                  <Group justify="space-between" wrap="nowrap" align="flex-start">
                    <Stack gap={4} style={{ minWidth: 0 }}>
                      <Text fw={500} truncate>
                        {q.name}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {t('uid')} {q.uid}
                      </Text>
                      <Group gap="sm" wrap="wrap">
                        <Text size="sm">
                          {t('blockUsed')} <BlockSize size={q.block_current} />
                        </Text>
                        <Text size="sm">
                          {t('blockHard')} <BlockSize size={q.block_hard_limit * 1024} />
                        </Text>
                      </Group>
                      <Badge size="sm" color={getQuotaStatusColor(status)} variant="light">
                        {t(getQuotaStatusLabelKey(status))}
                      </Badge>
                      <QuotaGraceDisplay quota={q} />
                    </Stack>
                    <Button size="xs" variant="light" onClick={() => setEditQuota(q)}>
                      {t('edit')}
                    </Button>
                  </Group>
                </Card>
              )
            })}
          </Stack>
        )
      ) : (
        <ScrollArea>
          <Box style={{ minWidth: 800 }}>
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
                  const status = statusByUid.get(q.uid) ?? getQuotaStatus(q)
                  const def = showDefaultSummary ? deviceDefault ?? null : null
                  const blockSoftAbove = !!(
                    def &&
                    !isReducedColumns &&
                    def.block_soft_limit > 0 &&
                    (q.block_soft_limit > def.block_soft_limit || q.block_soft_limit === 0)
                  )
                  const blockHardAbove = !!(
                    def &&
                    def.block_hard_limit > 0 &&
                    (q.block_hard_limit > def.block_hard_limit || q.block_hard_limit === 0)
                  )
                  const inodeSoftAbove = !!(
                    def &&
                    !isReducedColumns &&
                    def.inode_soft_limit > 0 &&
                    (q.inode_soft_limit > def.inode_soft_limit || q.inode_soft_limit === 0)
                  )
                  const inodeHardAbove = !!(
                    def &&
                    !isReducedColumns &&
                    def.inode_hard_limit > 0 &&
                    (q.inode_hard_limit > def.inode_hard_limit || q.inode_hard_limit === 0)
                  )
                  const limitCellStyle = (above: boolean) =>
                    above
                      ? { backgroundColor: 'var(--mantine-color-yellow-light)' }
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
                        <Stack gap={2}>
                          <Badge size="sm" color={getQuotaStatusColor(status)} variant="light">
                            {t(getQuotaStatusLabelKey(status))}
                          </Badge>
                          <QuotaGraceDisplay quota={q} />
                        </Stack>
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
          </Box>
        </ScrollArea>
      )}
      {!isMobile && sortedUsers.length === 0 && (
        <Text size="sm" c="dimmed">
          {t('noUsersMatch')}
        </Text>
      )}
      <Modal
        opened={addQuotaOpened}
        onClose={() => setAddQuotaOpened(false)}
        title={t('addQuotaForUser')}
        size="sm"
        fullScreen={isMobile}
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
          <Group justify="flex-end" gap="sm" wrap="wrap">
            <Button variant="default" onClick={() => setAddQuotaOpened(false)} w={{ base: '100%', xs: 'auto' }}>
              {t('cancel')}
            </Button>
            <Button
              loading={addQuotaResolving}
              onClick={handleAddQuotaContinue}
              disabled={!addQuotaUsername.trim()}
              w={{ base: '100%', xs: 'auto' }}
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
