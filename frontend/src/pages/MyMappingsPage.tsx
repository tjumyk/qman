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
} from '@mantine/core'
import { IconLink, IconPlus, IconTrash } from '@tabler/icons-react'
import { Link } from 'react-router-dom'
import { Anchor } from '@mantine/core'
import { useState } from 'react'
import {
  fetchMe,
  fetchMeMappings,
  fetchHosts,
  fetchHostUsers,
  postMeMapping,
  deleteMeMapping,
  getErrorMessage,
} from '../api'
import { useI18n } from '../i18n'
import { notifications } from '@mantine/notifications'

export function MyMappingsPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [selectedHostId, setSelectedHostId] = useState<string | null>(null)
  const [selectedHostUserName, setSelectedHostUserName] = useState<string | null>(null)

  const { data: mappings, isLoading, error } = useQuery({
    queryKey: ['me-mappings'],
    queryFn: fetchMeMappings,
  })
  const { data: me } = useQuery({ queryKey: ['me'], queryFn: fetchMe })
  const { data: hosts } = useQuery({ queryKey: ['hosts'], queryFn: fetchHosts })
  const { data: hostUsers, isLoading: hostUsersLoading } = useQuery({
    queryKey: ['hosts', selectedHostId, 'users'],
    queryFn: () => fetchHostUsers(selectedHostId!),
    enabled: !!selectedHostId,
  })

  const addMutation = useMutation({
    mutationFn: ({ hostId, hostUserName }: { hostId: string; hostUserName: string }) =>
      postMeMapping(hostId, hostUserName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['me-mappings'] })
      queryClient.invalidateQueries({ queryKey: ['me-quotas'] })
      setAddOpen(false)
      setSelectedHostId(null)
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
    mutationFn: ({ hostId, hostUserName }: { hostId: string; hostUserName: string }) =>
      deleteMeMapping(hostId, hostUserName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['me-mappings'] })
      queryClient.invalidateQueries({ queryKey: ['me-quotas'] })
    },
    onError: (err: unknown) => {
      notifications.show({
        title: t('error'),
        message: getErrorMessage(err, t('failedToRemoveMapping')),
        color: 'red',
      })
    },
  })

  if (isLoading) {
    return (
      <Stack align="center" gap="md" py="xl">
        <Loader size="lg" />
        <Text c="dimmed">{t('loading')}</Text>
      </Stack>
    )
  }
  if (error) {
    return (
      <Alert color="red" title={t('error')}>
        {error instanceof Error ? error.message : t('failedToLoadMappings')}
      </Alert>
    )
  }
  const list = mappings ?? []

  const hostOptions = (hosts ?? []).map((h) => ({ value: h.id, label: h.id }))
  const hostUserOptions = (hostUsers ?? [])
    .map((u) => ({ value: u.host_user_name, label: u.host_user_name }))
    .sort((a, b) => {
      if (!me?.name) return 0
      const exactA = a.value === me.name ? 1 : 0
      const exactB = b.value === me.name ? 1 : 0
      if (exactA !== exactB) return exactB - exactA
      const ciA = a.value.toLowerCase() === me.name.toLowerCase() ? 1 : 0
      const ciB = b.value.toLowerCase() === me.name.toLowerCase() ? 1 : 0
      if (ciA !== ciB) return ciB - ciA
      return 0
    })

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Group gap="sm">
          <IconLink size={24} />
          <Text size="lg" fw={600}>
            {t('myMappings')}
          </Text>
        </Group>
        <Button leftSection={<IconPlus size={16} />} variant="light" onClick={() => setAddOpen(true)}>
          {t('addMapping')}
        </Button>
      </Group>
      <Text size="sm" c="dimmed">
        {t('myMappingsDescription')}{' '}
        <Anchor component={Link} to="/my-usage">
          {t('myUsage')}
        </Anchor>
      </Text>
      {list.length === 0 ? (
        <Alert color="blue" title={t('noMappings')}>
          {t('noMappingsMessage')}
        </Alert>
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('host')}</Table.Th>
              <Table.Th>{t('hostUser')}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {list.map((m) => (
              <Table.Tr key={`${m.host_id}-${m.host_user_name}`}>
                <Table.Td>{m.host_id}</Table.Td>
                <Table.Td>{m.host_user_name}</Table.Td>
                <Table.Td>
                  <Button
                    size="xs"
                    variant="subtle"
                    color="red"
                    leftSection={<IconTrash size={14} />}
                    loading={deleteMutation.isPending}
                    onClick={() =>
                      deleteMutation.mutate({ hostId: m.host_id, hostUserName: m.host_user_name })
                    }
                  >
                    {t('removeMapping')}
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Modal opened={addOpen} onClose={() => setAddOpen(false)} title={t('addMapping')} centered>
        <Stack gap="md">
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
                ? hostUsersLoading
                  ? t('loading')
                  : t('selectHostUser')
                : t('selectHostFirst')
            }
            disabled={!selectedHostId}
            renderOption={({ option }) => {
              const isSuggested =
                me?.name &&
                (option.value === me.name ||
                  option.value.toLowerCase() === me.name.toLowerCase())
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
              disabled={!selectedHostId || !selectedHostUserName || hostUsersLoading}
              onClick={() => {
                if (selectedHostId && selectedHostUserName)
                  addMutation.mutate({ hostId: selectedHostId, hostUserName: selectedHostUserName })
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
