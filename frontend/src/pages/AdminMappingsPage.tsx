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
} from '@mantine/core'
import { IconLink, IconPlus, IconTrash, IconUsers } from '@tabler/icons-react'
import { useState } from 'react'
import {
  fetchAdminMappings,
  fetchAdminHostUsers,
  fetchAdminOAuthUsers,
  fetchHosts,
  fetchHostUsers,
  postAdminMapping,
  deleteAdminMapping,
  getErrorMessage,
} from '../api'
import { useI18n } from '../i18n'
import { notifications } from '@mantine/notifications'
import type { AdminMapping, AdminHostUser } from '../api'

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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-mappings'] })
      queryClient.invalidateQueries({ queryKey: ['admin-host-users'] })
      setAddOpen(false)
      setSelectedHostId(null)
      setSelectedOAuthUserId(null)
      setSelectedHostUserName(null)
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
      <Group justify="space-between">
        <Group gap="sm">
          <IconLink size={24} />
          <Text size="lg" fw={600}>
            {t('userMappings')}
          </Text>
        </Group>
        <Button leftSection={<IconPlus size={16} />} variant="light" onClick={() => setAddOpen(true)}>
          {t('addMapping')}
        </Button>
      </Group>
      <Text size="sm" c="dimmed">
        {t('userMappingsDescription')}
      </Text>
      {rows.length === 0 ? (
        <Alert color="blue" title={t('noMappings')}>
          {t('noAdminMappingsMessage')}
        </Alert>
      ) : (
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
      )}

      <Modal opened={addOpen} onClose={() => setAddOpen(false)} title={t('addMapping')} centered>
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
          <Group justify="flex-end" mt="md">
            <Button variant="default" onClick={() => setAddOpen(false)}>
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
            >
              {t('addMapping')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
