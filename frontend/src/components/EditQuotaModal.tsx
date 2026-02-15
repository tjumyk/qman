import { useState, useEffect } from 'react'
import { Modal, Stack, NumberInput, Group, Button, Text } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { notifications } from '@mantine/notifications'
import { setUserQuota, getErrorMessage } from '../api'
import { useI18n } from '../i18n'
import { BlockLimitEditor } from './BlockLimitEditor'
import type { UserQuota, SetUserQuotaBody } from '../api/schemas'

interface EditQuotaModalProps {
  opened: boolean
  onClose: () => void
  hostId: string
  deviceName: string
  quota: UserQuota | null
  /** When "zfs", inode fields are hidden (ZFS user quotas are space-only). */
  userQuotaFormat?: string
}

export function EditQuotaModal({
  opened,
  onClose,
  hostId,
  deviceName,
  quota,
  userQuotaFormat,
}: EditQuotaModalProps) {
  const isZfs = userQuotaFormat === 'zfs'
  const queryClient = useQueryClient()
  const { t } = useI18n()
  const [blockSoft, setBlockSoft] = useState(0)
  const [blockHard, setBlockHard] = useState(0)
  const [inodeSoft, setInodeSoft] = useState(0)
  const [inodeHard, setInodeHard] = useState(0)

  useEffect(() => {
    if (quota) {
      setBlockSoft(quota.block_soft_limit)
      setBlockHard(quota.block_hard_limit)
      setInodeSoft(quota.inode_soft_limit)
      setInodeHard(quota.inode_hard_limit)
    }
  }, [quota])

  const mutation = useMutation({
    mutationFn: (body: SetUserQuotaBody) =>
      setUserQuota(hostId, quota!.uid, deviceName, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quotas'] })
      notifications.show({ message: t('quotaUpdated'), color: 'green' })
      onClose()
    },
    onError: (err: unknown) => {
      notifications.show({
        message: getErrorMessage(err, t('failedToUpdateQuota')),
        color: 'red',
      })
    },
  })

  if (!quota) return null

  const handleSave = () => {
    mutation.mutate({
      block_soft_limit: blockSoft,
      block_hard_limit: blockHard,
      inode_soft_limit: isZfs ? 0 : inodeSoft,
      inode_hard_limit: isZfs ? 0 : inodeHard,
    })
  }

  return (
    <Modal opened={opened} onClose={onClose} title={`${t('editQuota')}: ${quota.name} (uid ${quota.uid})`} size="sm">
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          {hostId} / {deviceName}
        </Text>
        <div>
          <Text size="sm" fw={500} mb={4}>
            {t('blockSoftLimit1k')}
          </Text>
          <BlockLimitEditor initValue={blockSoft} onChange={setBlockSoft} />
        </div>
        <div>
          <Text size="sm" fw={500} mb={4}>
            {t('blockHardLimit1k')}
          </Text>
          <BlockLimitEditor initValue={blockHard} onChange={setBlockHard} />
        </div>
        {!isZfs && (
          <>
            <NumberInput
              label={t('inodeSoftLimit')}
              min={0}
              value={inodeSoft}
              onChange={(v) => setInodeSoft(typeof v === 'string' ? parseInt(v, 10) || 0 : v)}
            />
            <NumberInput
              label={t('inodeHardLimit')}
              min={0}
              value={inodeHard}
              onChange={(v) => setInodeHard(typeof v === 'string' ? parseInt(v, 10) || 0 : v)}
            />
          </>
        )}
        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={onClose}>
            {t('cancel')}
          </Button>
          <Button loading={mutation.isPending} onClick={handleSave}>
            {t('save')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
