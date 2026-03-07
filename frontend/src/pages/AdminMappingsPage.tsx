import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Stack,
  Text,
  Loader,
  Alert,
  Group,
  Button,
  Table,
  Modal,
  Select,
  ActionIcon,
  Checkbox,
  ScrollArea,
  Box,
} from '@mantine/core'
import { IconLink, IconPlus, IconTrash, IconUsers, IconWand } from '@tabler/icons-react'
import { useState, useMemo } from 'react'
import { useMediaQuery } from '@mantine/hooks'
import {
  fetchAdminMappings,
  fetchAdminHostUsers,
  fetchAdminOAuthUsers,
  fetchHosts,
  fetchHostUsers,
  postAdminMapping,
  deleteAdminMapping,
  postAdminMappingsBatch,
  getErrorMessage,
} from '../api'
import { useI18n } from '../i18n'
import { notifications } from '@mantine/notifications'
import type { AdminMapping, AdminHostUser, AdminOAuthUser } from '../api'

type CandidateMapping = {
  hostId: string
  hostUserName: string
  oauthUserId: number
  oauthUserName: string
}

function buildRows(
  hostUsers: AdminHostUser[],
  mappings: AdminMapping[]
): { host_id: string; host_user_name: string; oauthMappings: AdminMapping[] }[] {
  const byKey = new Map<string, AdminMapping[]>()
  for (const m of mappings) {
    const key = `${m.host_id}\t${m.host_user_name}`
    if (!byKey.has(key)) byKey.set(key, [])
    byKey.get(key)!.push(m)
  }
  const rows: { host_id: string; host_user_name: string; oauthMappings: AdminMapping[] }[] = []
  const seen = new Set<string>()
  for (const hu of hostUsers) {
    const key = `${hu.host_id}\t${hu.host_user_name}`
    if (seen.has(key)) continue
    seen.add(key)
    rows.push({
      host_id: hu.host_id,
      host_user_name: hu.host_user_name,
      oauthMappings: byKey.get(key) ?? [],
    })
  }
  for (const m of mappings) {
    const key = `${m.host_id}\t${m.host_user_name}`
    if (seen.has(key)) continue
    seen.add(key)
    rows.push({
      host_id: m.host_id,
      host_user_name: m.host_user_name,
      oauthMappings: byKey.get(key) ?? [],
    })
  }
  rows.sort((a, b) => a.host_id.localeCompare(b.host_id) || a.host_user_name.localeCompare(b.host_user_name))
  return rows
}

export function AdminMappingsPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const isMobile = useMediaQuery('(max-width: 36em)')
  const [addOpen, setAddOpen] = useState(false)
  const [selectedHostId, setSelectedHostId] = useState<string | null>(null)
  const [selectedOAuthUserId, setSelectedOAuthUserId] = useState<string | null>(null)
  const [selectedHostUserName, setSelectedHostUserName] = useState<string | null>(null)

  const { data: mappings, isLoading: mappingsLoading, error: mappingsError } = useQuery({
    queryKey: ['admin-mappings'],
    queryFn: fetchAdminMappings,
  })
  const { data: hostUsers, isLoading: hostUsersLoading } = useQuery({
    queryKey: ['admin-host-users'],
    queryFn: fetchAdminHostUsers,
  })
  const { data: oauthUsers, isLoading: oauthUsersLoading, refetch: refetchOAuthUsers } = useQuery({
    queryKey: ['admin-oauth-users'],
    queryFn: fetchAdminOAuthUsers,
  })
  const [inlineAddForRow, setInlineAddForRow] = useState<Record<string, string>>({})
  const [autoAssignOpen, setAutoAssignOpen] = useState(false)
  const [selectedCandidates, setSelectedCandidates] = useState<Set<string>>(new Set())
  const [suggestedMappingsOpen, setSuggestedMappingsOpen] = useState(false)
  const [suggestedMappings, setSuggestedMappings] = useState<CandidateMapping[]>([])
  const [selectedSuggested, setSelectedSuggested] = useState<Set<string>>(new Set())
  const [lastAddedMapping, setLastAddedMapping] = useState<{ oauthUserId: number; oauthUserName: string; hostUserName: string } | null>(null)
  const { data: hosts } = useQuery({ queryKey: ['hosts'], queryFn: fetchHosts })
  const { data: hostUsersForHost, isLoading: hostUsersForHostLoading } = useQuery({
    queryKey: ['hosts', selectedHostId, 'users'],
    queryFn: () => fetchHostUsers(selectedHostId!),
    enabled: !!selectedHostId,
  })

  const addMutation = useMutation({
    mutationFn: ({
      oauthUserId,
      hostId,
      hostUserName,
    }: {
      oauthUserId: number
      hostId: string
      hostUserName: string
    }) => postAdminMapping(oauthUserId, hostId, hostUserName),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['admin-mappings'] })
      queryClient.invalidateQueries({ queryKey: ['admin-host-users'] })
      setAddOpen(false)
      setSelectedHostId(null)
      setSelectedOAuthUserId(null)
      setSelectedHostUserName(null)
      checkAndShowSuggestedMappings(variables.oauthUserId, variables.hostId, variables.hostUserName)
    },
    onError: (err: unknown) => {
      notifications.show({
        title: t('error'),
        message: getErrorMessage(err, t('failedToAddMapping')),
        color: 'red',
      })
    },
  })
  const deleteMutation = useMutation({
    mutationFn: ({
      oauthUserId,
      hostId,
      hostUserName,
    }: {
      oauthUserId: number
      hostId: string
      hostUserName: string
    }) => deleteAdminMapping(oauthUserId, hostId, hostUserName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-mappings'] })
      queryClient.invalidateQueries({ queryKey: ['admin-host-users'] })
    },
    onError: (err: unknown) => {
      notifications.show({
        title: t('error'),
        message: getErrorMessage(err, t('failedToRemoveMapping')),
        color: 'red',
      })
    },
  })

  const candidateMappings = useMemo((): CandidateMapping[] => {
    if (!hostUsers || !oauthUsers || !mappings) return []
    const oauthUsersByName = new Map<string, AdminOAuthUser>()
    for (const u of oauthUsers) {
      oauthUsersByName.set(u.name, u)
    }
    const existingMappingKeys = new Set<string>()
    for (const m of mappings) {
      existingMappingKeys.add(`${m.oauth_user_id}|${m.host_id}|${m.host_user_name}`)
    }
    const candidates: CandidateMapping[] = []
    const seenHostUsers = new Set<string>()
    for (const hu of hostUsers) {
      const key = `${hu.host_id}|${hu.host_user_name}`
      if (seenHostUsers.has(key)) continue
      seenHostUsers.add(key)
      const matchingOAuthUser = oauthUsersByName.get(hu.host_user_name)
      if (matchingOAuthUser) {
        const mappingKey = `${matchingOAuthUser.id}|${hu.host_id}|${hu.host_user_name}`
        if (!existingMappingKeys.has(mappingKey)) {
          candidates.push({
            hostId: hu.host_id,
            hostUserName: hu.host_user_name,
            oauthUserId: matchingOAuthUser.id,
            oauthUserName: matchingOAuthUser.name,
          })
        }
      }
    }
    candidates.sort((a, b) => a.hostId.localeCompare(b.hostId) || a.hostUserName.localeCompare(b.hostUserName))
    return candidates
  }, [hostUsers, oauthUsers, mappings])

  const getCandidateKey = (c: CandidateMapping) => `${c.oauthUserId}|${c.hostId}|${c.hostUserName}`

  const computeSuggestedMappings = (
    oauthUserId: number,
    hostUserName: string,
    excludeHostId: string
  ): CandidateMapping[] => {
    if (!hostUsers || !oauthUsers || !mappings) return []
    const oauthUser = oauthUsers.find((u) => u.id === oauthUserId)
    if (!oauthUser) return []
    
    const existingMappingKeys = new Set<string>()
    for (const m of mappings) {
      existingMappingKeys.add(`${m.oauth_user_id}|${m.host_id}|${m.host_user_name}`)
    }
    existingMappingKeys.add(`${oauthUserId}|${excludeHostId}|${hostUserName}`)
    
    const suggested: CandidateMapping[] = []
    const seenHosts = new Set<string>()
    for (const hu of hostUsers) {
      if (hu.host_user_name !== hostUserName) continue
      if (hu.host_id === excludeHostId) continue
      if (seenHosts.has(hu.host_id)) continue
      seenHosts.add(hu.host_id)
      
      const mappingKey = `${oauthUserId}|${hu.host_id}|${hostUserName}`
      if (!existingMappingKeys.has(mappingKey)) {
        suggested.push({
          hostId: hu.host_id,
          hostUserName: hostUserName,
          oauthUserId: oauthUserId,
          oauthUserName: oauthUser.name,
        })
      }
    }
    suggested.sort((a, b) => a.hostId.localeCompare(b.hostId))
    return suggested
  }

  const handleOpenAutoAssign = () => {
    const allKeys = new Set(candidateMappings.map(getCandidateKey))
    setSelectedCandidates(allKeys)
    setAutoAssignOpen(true)
  }

  const handleToggleCandidate = (candidate: CandidateMapping) => {
    const key = getCandidateKey(candidate)
    setSelectedCandidates((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  const handleSelectAll = () => {
    setSelectedCandidates(new Set(candidateMappings.map(getCandidateKey)))
  }

  const handleDeselectAll = () => {
    setSelectedCandidates(new Set())
  }

  const handleToggleSuggested = (candidate: CandidateMapping) => {
    const key = getCandidateKey(candidate)
    setSelectedSuggested((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  const handleSelectAllSuggested = () => {
    setSelectedSuggested(new Set(suggestedMappings.map(getCandidateKey)))
  }

  const handleDeselectAllSuggested = () => {
    setSelectedSuggested(new Set())
  }

  const [isConfirming, setIsConfirming] = useState(false)
  const [isConfirmingSuggested, setIsConfirmingSuggested] = useState(false)

  const handleConfirmSuggested = async () => {
    const toAdd = suggestedMappings.filter((c) => selectedSuggested.has(getCandidateKey(c)))
    if (toAdd.length === 0) {
      setSuggestedMappingsOpen(false)
      return
    }
    setIsConfirmingSuggested(true)
    try {
      await postAdminMappingsBatch(
        toAdd.map((c) => ({
          oauth_user_id: c.oauthUserId,
          host_id: c.hostId,
          host_user_name: c.hostUserName,
        }))
      )
      queryClient.invalidateQueries({ queryKey: ['admin-mappings'] })
      queryClient.invalidateQueries({ queryKey: ['admin-host-users'] })
      setSuggestedMappingsOpen(false)
    } catch (err: unknown) {
      notifications.show({
        title: t('error'),
        message: getErrorMessage(err, t('failedToAddMapping')),
        color: 'red',
      })
    } finally {
      setIsConfirmingSuggested(false)
    }
  }

  const checkAndShowSuggestedMappings = (oauthUserId: number, hostId: string, hostUserName: string) => {
    const oauthUser = oauthUsers?.find((u) => u.id === oauthUserId)
    if (!oauthUser) return
    
    const suggested = computeSuggestedMappings(oauthUserId, hostUserName, hostId)
    if (suggested.length > 0) {
      setSuggestedMappings(suggested)
      setSelectedSuggested(new Set(suggested.map(getCandidateKey)))
      setLastAddedMapping({ oauthUserId, oauthUserName: oauthUser.name, hostUserName })
      setSuggestedMappingsOpen(true)
    }
  }

  const handleConfirmAutoAssign = async () => {
    const toAdd = candidateMappings.filter((c) => selectedCandidates.has(getCandidateKey(c)))
    if (toAdd.length === 0) {
      setAutoAssignOpen(false)
      return
    }
    setIsConfirming(true)
    try {
      await postAdminMappingsBatch(
        toAdd.map((c) => ({
          oauth_user_id: c.oauthUserId,
          host_id: c.hostId,
          host_user_name: c.hostUserName,
        }))
      )
      queryClient.invalidateQueries({ queryKey: ['admin-mappings'] })
      queryClient.invalidateQueries({ queryKey: ['admin-host-users'] })
      setAutoAssignOpen(false)
    } catch (err: unknown) {
      notifications.show({
        title: t('error'),
        message: getErrorMessage(err, t('failedToAddMapping')),
        color: 'red',
      })
    } finally {
      setIsConfirming(false)
    }
  }

  if (mappingsLoading || hostUsersLoading) {
    return (
      <Stack align="center" gap="md" py="xl">
        <Loader size="lg" />
        <Text c="dimmed">{t('loading')}</Text>
      </Stack>
    )
  }
  if (mappingsError) {
    return (
      <Alert color="red" title={t('error')}>
        {mappingsError instanceof Error ? mappingsError.message : t('failedToLoadMappings')}
      </Alert>
    )
  }

  const rows = buildRows(hostUsers ?? [], mappings ?? [])
  const hostOptions = (hosts ?? []).map((h) => ({ value: h.id, label: h.id }))
  const oauthUserOptions = (oauthUsers ?? []).map((u) => ({
    value: String(u.id),
    label: `${u.name} (${u.id})`,
  }))
  const selectedOAuthName =
    selectedOAuthUserId != null && selectedOAuthUserId !== ''
      ? oauthUsers?.find((u) => String(u.id) === selectedOAuthUserId)?.name
      : undefined
  const hostUserOptions = (hostUsersForHost ?? [])
    .map((u) => ({ value: u.host_user_name, label: u.host_user_name }))
    .sort((a, b) => {
      if (!selectedOAuthName) return 0
      const exactA = a.value === selectedOAuthName ? 1 : 0
      const exactB = b.value === selectedOAuthName ? 1 : 0
      if (exactA !== exactB) return exactB - exactA
      const ciA = a.value.toLowerCase() === selectedOAuthName.toLowerCase() ? 1 : 0
      const ciB = b.value.toLowerCase() === selectedOAuthName.toLowerCase() ? 1 : 0
      if (ciA !== ciB) return ciB - ciA
      return 0
    })

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="wrap" gap="sm">
        <Group gap="sm">
          <IconLink size={24} />
          <Text size="lg" fw={600}>
            {t('userMappings')}
          </Text>
        </Group>
        <Group gap="sm">
          <Button
            leftSection={<IconWand size={16} />}
            variant="light"
            onClick={handleOpenAutoAssign}
            disabled={oauthUsersLoading || hostUsersLoading || candidateMappings.length === 0}
          >
            {t('autoAssign')}
          </Button>
          <Button leftSection={<IconPlus size={16} />} variant="light" onClick={() => setAddOpen(true)}>
            {t('addMapping')}
          </Button>
        </Group>
      </Group>
      <Text size="sm" c="dimmed">
        {t('userMappingsDescription')}
      </Text>
      {rows.length === 0 ? (
        <Alert color="blue" title={t('noMappings')}>
          {t('noAdminMappingsMessage')}
        </Alert>
      ) : (
        <ScrollArea>
          <Box style={{ minWidth: 560 }}>
            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('host')}</Table.Th>
                  <Table.Th>{t('hostUser')}</Table.Th>
                  <Table.Th>{t('mappedOAuthUsers')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((row) => (
                  <Table.Tr key={`${row.host_id}-${row.host_user_name}`}>
                    <Table.Td>{row.host_id}</Table.Td>
                    <Table.Td>{row.host_user_name}</Table.Td>
                    <Table.Td>
                      <Group gap="xs" wrap="wrap" align="center">
                        {row.oauthMappings.length === 0 && !inlineAddForRow[`${row.host_id}|${row.host_user_name}`] ? (
                          <Text size="sm" c="dimmed">
                            —
                          </Text>
                        ) : null}
                        {row.oauthMappings.map((m) => (
                          <Group key={`${m.oauth_user_id}-${row.host_id}-${row.host_user_name}`} gap={4}>
                            <Text size="sm">{m.oauth_user_name ?? m.oauth_user_id}</Text>
                            <ActionIcon
                              size="sm"
                              variant="subtle"
                              color="red"
                              onClick={() =>
                                deleteMutation.mutate({
                                  oauthUserId: m.oauth_user_id,
                                  hostId: row.host_id,
                                  hostUserName: row.host_user_name,
                                })
                              }
                              loading={deleteMutation.isPending}
                            >
                              <IconTrash size={14} />
                            </ActionIcon>
                          </Group>
                        ))}
                        <Select
                          size="xs"
                          placeholder={oauthUsersLoading ? t('loading') : t('addUser')}
                          data={(oauthUserOptions ?? [])
                            .filter(
                              (opt) =>
                                !row.oauthMappings.some((m) => String(m.oauth_user_id) === opt.value)
                            )
                            .sort((a, b) => {
                              const nameA =
                                oauthUsers?.find((u) => String(u.id) === a.value)?.name ?? ''
                              const nameB =
                                oauthUsers?.find((u) => String(u.id) === b.value)?.name ?? ''
                              const exactA = nameA === row.host_user_name ? 1 : 0
                              const exactB = nameB === row.host_user_name ? 1 : 0
                              if (exactA !== exactB) return exactB - exactA
                              const ciA =
                                nameA.toLowerCase() === row.host_user_name.toLowerCase() ? 1 : 0
                              const ciB =
                                nameB.toLowerCase() === row.host_user_name.toLowerCase() ? 1 : 0
                              if (ciA !== ciB) return ciB - ciA
                              return nameA.localeCompare(nameB)
                            })}
                          value={inlineAddForRow[`${row.host_id}|${row.host_user_name}`] ?? null}
                          onChange={(v) => {
                            if (!v) return
                            const rowKey = `${row.host_id}|${row.host_user_name}`
                            setInlineAddForRow((prev) => ({ ...prev, [rowKey]: v }))
                            addMutation.mutate(
                              {
                                oauthUserId: Number(v),
                                hostId: row.host_id,
                                hostUserName: row.host_user_name,
                              },
                              {
                                onSettled: () =>
                                  setInlineAddForRow((prev) => {
                                    const next = { ...prev }
                                    delete next[rowKey]
                                    return next
                                  }),
                              }
                            )
                          }}
                          disabled={oauthUsersLoading || addMutation.isPending}
                          clearable={false}
                          style={{ minWidth: 140 }}
                          renderOption={({ option }) => {
                            const oauthName = oauthUsers?.find(
                              (u) => String(u.id) === option.value
                            )?.name
                            const isSuggested =
                              oauthName &&
                              (oauthName === row.host_user_name ||
                                oauthName.toLowerCase() === row.host_user_name.toLowerCase())
                            return (
                              <>
                                {option.label}
                                {isSuggested && (
                                  <>
                                    {' '}
                                    <Text component="span" c="dimmed" size="sm">
                                      ({t('suggested')})
                                    </Text>
                                  </>
                                )}
                              </>
                            )
                          }}
                        />
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Box>
        </ScrollArea>
      )}

      <Modal opened={addOpen} onClose={() => setAddOpen(false)} title={t('addMapping')} centered fullScreen={isMobile}>
        <Stack gap="md">
          <Group>
            <Select
              label={t('oauthUser')}
              data={oauthUserOptions}
              value={selectedOAuthUserId}
              onChange={setSelectedOAuthUserId}
              placeholder={oauthUsersLoading ? t('loading') : t('loadOAuthUsersFirst')}
              disabled={!oauthUsers?.length}
              style={{ flex: 1 }}
            />
            <Button
              variant="subtle"
              mt="xl"
              leftSection={<IconUsers size={16} />}
              loading={oauthUsersLoading}
              onClick={() => refetchOAuthUsers()}
            >
              {t('loadOAuthUsers')}
            </Button>
          </Group>
          <Select
            label={t('host')}
            data={hostOptions}
            value={selectedHostId}
            onChange={(v) => {
              setSelectedHostId(v)
              setSelectedHostUserName(null)
            }}
            placeholder={t('selectHost')}
          />
          <Select
            label={t('hostUser')}
            data={hostUserOptions}
            value={selectedHostUserName}
            onChange={setSelectedHostUserName}
            placeholder={
              selectedHostId
                ? hostUsersForHostLoading
                  ? t('loading')
                  : t('selectHostUser')
                : t('selectHostFirst')
            }
            disabled={!selectedHostId}
            renderOption={({ option }) => {
              const isSuggested =
                selectedOAuthName &&
                (option.value === selectedOAuthName ||
                  option.value.toLowerCase() === selectedOAuthName.toLowerCase())
              return (
                <>
                  {option.label}
                  {isSuggested && (
                    <>
                      {' '}
                      <Text component="span" c="dimmed" size="sm">
                        ({t('suggested')})
                      </Text>
                    </>
                  )}
                </>
              )
            }}
          />
          <Group justify="flex-end" mt="md" wrap="wrap">
            <Button variant="default" onClick={() => setAddOpen(false)} w={{ base: '100%', xs: 'auto' }}>
              {t('cancel')}
            </Button>
            <Button
              loading={addMutation.isPending}
              disabled={
                !selectedOAuthUserId ||
                !selectedHostId ||
                !selectedHostUserName ||
                hostUsersForHostLoading
              }
              onClick={() => {
                if (selectedOAuthUserId && selectedHostId && selectedHostUserName)
                  addMutation.mutate({
                    oauthUserId: Number(selectedOAuthUserId),
                    hostId: selectedHostId,
                    hostUserName: selectedHostUserName,
                  })
              }}
              w={{ base: '100%', xs: 'auto' }}
            >
              {t('addMapping')}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={autoAssignOpen}
        onClose={() => setAutoAssignOpen(false)}
        title={t('autoAssignMappings')}
        centered
        size="lg"
        fullScreen={isMobile}
      >
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            {t('autoAssignDescription')}
          </Text>
          {candidateMappings.length === 0 ? (
            <Alert color="blue">{t('noCandidateMappings')}</Alert>
          ) : (
            <>
              <Group justify="space-between">
                <Text size="sm">
                  {t('candidateMappingsCount').replace('{count}', String(candidateMappings.length))}
                </Text>
                <Group gap="xs">
                  <Button variant="subtle" size="xs" onClick={handleSelectAll}>
                    {t('selectAll')}
                  </Button>
                  <Button variant="subtle" size="xs" onClick={handleDeselectAll}>
                    {t('deselectAll')}
                  </Button>
                </Group>
              </Group>
              <ScrollArea.Autosize mah={400}>
                <Table striped highlightOnHover>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th style={{ width: 40 }} />
                      <Table.Th>{t('host')}</Table.Th>
                      <Table.Th>{t('hostUser')}</Table.Th>
                      <Table.Th>{t('oauthUser')}</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {candidateMappings.map((candidate) => {
                      const key = getCandidateKey(candidate)
                      return (
                        <Table.Tr key={key}>
                          <Table.Td>
                            <Checkbox
                              checked={selectedCandidates.has(key)}
                              onChange={() => handleToggleCandidate(candidate)}
                            />
                          </Table.Td>
                          <Table.Td>{candidate.hostId}</Table.Td>
                          <Table.Td>{candidate.hostUserName}</Table.Td>
                          <Table.Td>
                            {candidate.oauthUserName} ({candidate.oauthUserId})
                          </Table.Td>
                        </Table.Tr>
                      )
                    })}
                  </Table.Tbody>
                </Table>
              </ScrollArea.Autosize>
            </>
          )}
          <Group justify="flex-end" mt="md" wrap="wrap">
            <Button variant="default" onClick={() => setAutoAssignOpen(false)} w={{ base: '100%', xs: 'auto' }}>
              {t('cancel')}
            </Button>
            <Button
              loading={isConfirming}
              disabled={selectedCandidates.size === 0 || candidateMappings.length === 0}
              onClick={handleConfirmAutoAssign}
              w={{ base: '100%', xs: 'auto' }}
            >
              {t('confirmMappings')} ({selectedCandidates.size})
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={suggestedMappingsOpen}
        onClose={() => setSuggestedMappingsOpen(false)}
        title={t('suggestedMappings')}
        centered
        size="lg"
        fullScreen={isMobile}
      >
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            {t('suggestedMappingsDescription')
              .replace('{oauthUser}', lastAddedMapping?.oauthUserName ?? '')
              .replace('{hostUser}', lastAddedMapping?.hostUserName ?? '')}
          </Text>
          <Group justify="space-between">
            <Text size="sm">
              {t('candidateMappingsCount').replace('{count}', String(suggestedMappings.length))}
            </Text>
            <Group gap="xs">
              <Button variant="subtle" size="xs" onClick={handleSelectAllSuggested}>
                {t('selectAll')}
              </Button>
              <Button variant="subtle" size="xs" onClick={handleDeselectAllSuggested}>
                {t('deselectAll')}
              </Button>
            </Group>
          </Group>
          <ScrollArea.Autosize mah={400}>
            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th style={{ width: 40 }} />
                  <Table.Th>{t('host')}</Table.Th>
                  <Table.Th>{t('hostUser')}</Table.Th>
                  <Table.Th>{t('oauthUser')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {suggestedMappings.map((candidate) => {
                  const key = getCandidateKey(candidate)
                  return (
                    <Table.Tr key={key}>
                      <Table.Td>
                        <Checkbox
                          checked={selectedSuggested.has(key)}
                          onChange={() => handleToggleSuggested(candidate)}
                        />
                      </Table.Td>
                      <Table.Td>{candidate.hostId}</Table.Td>
                      <Table.Td>{candidate.hostUserName}</Table.Td>
                      <Table.Td>
                        {candidate.oauthUserName} ({candidate.oauthUserId})
                      </Table.Td>
                    </Table.Tr>
                  )
                })}
              </Table.Tbody>
            </Table>
          </ScrollArea.Autosize>
          <Group justify="flex-end" mt="md" wrap="wrap">
            <Button variant="default" onClick={() => setSuggestedMappingsOpen(false)} w={{ base: '100%', xs: 'auto' }}>
              {t('cancel')}
            </Button>
            <Button
              loading={isConfirmingSuggested}
              disabled={selectedSuggested.size === 0}
              onClick={handleConfirmSuggested}
              w={{ base: '100%', xs: 'auto' }}
            >
              {t('confirmMappings')} ({selectedSuggested.size})
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
