import { useState } from 'react'
import { Tabs, Stack, Text, Table, Button, Badge, TextInput, Group, Modal } from '@mantine/core'
import { IconUsers, IconBox, IconPhoto, IconDatabase, IconPlus } from '@tabler/icons-react'
import { BlockSize } from '../BlockSize'
import { getQuotaStatus, getQuotaStatusColor, getQuotaStatusLabelKey } from '../../utils/quotaStatus'
import { useI18n } from '../../i18n'
import { EditQuotaModal } from '../EditQuotaModal'
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

export function DockerDetailTabs({ hostId, device }: DockerDetailTabsProps) {
  const { t } = useI18n()
  const [activeTab, setActiveTab] = useState<string | null>('users')
  const [search, setSearch] = useState('')
  const [editQuota, setEditQuota] = useState<UserQuota | null>(null)
  const [addQuotaOpened, setAddQuotaOpened] = useState(false)
  const [addQuotaUsername, setAddQuotaUsername] = useState('')
  const [addQuotaResolving, setAddQuotaResolving] = useState(false)
  const [addQuotaError, setAddQuotaError] = useState<string | null>(null)

  const users = device.user_quotas || []
  const filteredUsers = search.trim()
    ? users.filter(
        (q) =>
          q.name.toLowerCase().includes(search.trim().toLowerCase()) ||
          String(q.uid).includes(search.trim())
      )
    : users

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
        {device.usage && <DeviceUsage usage={device.usage} userQuotas={device.user_quotas} />}
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
            </Group>

            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('uid')}</Table.Th>
                  <Table.Th>{t('name')}</Table.Th>
                  <Table.Th>{t('blockUsed')}</Table.Th>
                  <Table.Th>{t('blockHard')}</Table.Th>
                  <Table.Th>{t('status')}</Table.Th>
                  <Table.Th>{t('actions')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {filteredUsers.map((q) => {
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
            {filteredUsers.length === 0 && (
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
      />
    </Stack>
  )
}
