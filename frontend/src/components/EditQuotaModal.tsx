import { useState, useEffect, useMemo } from 'react'
import { Modal, Stack, NumberInput, Group, Button, Text, Progress, Alert, Box } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { notifications } from '@mantine/notifications'
import { setUserQuota, getErrorMessage } from '../api'
import { useI18n } from '../i18n'
import { BlockLimitEditor } from './BlockLimitEditor'
import { BlockSize } from './BlockSize'
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
  const isDocker = userQuotaFormat === 'docker'
  const isSingleLimitFormat = isZfs || isDocker
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

  const currentUsageBytes = quota?.block_current ?? 0
  const currentUsage1k = Math.ceil(currentUsageBytes / 1024)

  const effectiveLimit = isSingleLimitFormat ? blockHard : Math.max(blockSoft, blockHard)
  const effectiveLimitBytes = effectiveLimit * 1024
  const usagePercent = effectiveLimitBytes > 0
    ? Math.min(100, (currentUsageBytes / effectiveLimitBytes) * 100)
    : 0
  const isOverLimit = effectiveLimit > 0 && currentUsageBytes > effectiveLimitBytes
  const isUnlimited = effectiveLimit === 0

  const softHardError = useMemo(() => {
    if (isSingleLimitFormat) return null
    if (blockSoft > 0 && blockHard > 0 && blockSoft > blockHard) {
      return t('softExceedsHardError')
    }
    if (inodeSoft > 0 && inodeHard > 0 && inodeSoft > inodeHard) {
      return t('softExceedsHardError')
    }
    return null
  }, [isSingleLimitFormat, blockSoft, blockHard, inodeSoft, inodeHard, t])

  if (!quota) return null

  const handleSave = () => {
    if (softHardError) return
    mutation.mutate({
      block_soft_limit: isSingleLimitFormat ? blockHard : blockSoft,
      block_hard_limit: blockHard,
      inode_soft_limit: isSingleLimitFormat ? 0 : inodeSoft,
      inode_hard_limit: isSingleLimitFormat ? 0 : inodeHard,
    })
  }

  return (
    <Modal opened={opened} onClose={onClose} title={`${t('editQuota')}: ${quota.name} (uid ${quota.uid})`} size="sm">
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          {hostId} / {deviceName}
        </Text>

        <Box>
          <Text size="sm" fw={500} mb={4}>
            {t('currentUsage')}
          </Text>
          <Text size="sm">
            <BlockSize size={currentUsageBytes} />
          </Text>
        </Box>

        {isSingleLimitFormat ? (
          <div>
            <Text size="sm" fw={500} mb={4}>
              {t('quotaLimit')}
            </Text>
            <BlockLimitEditor
              value={blockHard}
              onChange={(v) => {
                setBlockHard(v)
                setBlockSoft(v)
              }}
              currentUsage1k={currentUsage1k}
              showPresets
            />
          </div>
        ) : (
          <>
            <div>
              <Text size="sm" fw={500} mb={4}>
                {t('blockSoftLimit1k')}
              </Text>
              <BlockLimitEditor
                value={blockSoft}
                onChange={setBlockSoft}
                currentUsage1k={currentUsage1k}
                showPresets
              />
            </div>
            <div>
              <Text size="sm" fw={500} mb={4}>
                {t('blockHardLimit1k')}
              </Text>
              <BlockLimitEditor
                value={blockHard}
                onChange={setBlockHard}
                currentUsage1k={currentUsage1k}
                showPresets
              />
            </div>
            <NumberInput
              label={t('inodeSoftLimit')}
              min={0}
              value={inodeSoft}
              onChange={(v) => setInodeSoft(typeof v === 'string' ? parseInt(v, 10) || 0 : v)}
              thousandSeparator
            />
            <NumberInput
              label={t('inodeHardLimit')}
              min={0}
              value={inodeHard}
              onChange={(v) => setInodeHard(typeof v === 'string' ? parseInt(v, 10) || 0 : v)}
              thousandSeparator
            />
          </>
        )}

        {!isUnlimited && (
          <Box>
            <Text size="xs" c="dimmed" mb={4}>
              {t('usageVsNewLimit')}
            </Text>
            <Progress
              value={usagePercent}
              color={isOverLimit ? 'red' : 'blue'}
              size="sm"
            />
            <Text size="xs" c={isOverLimit ? 'red' : 'dimmed'} mt={4}>
              <BlockSize size={currentUsageBytes} /> / <BlockSize size={effectiveLimitBytes} />
              {' '}({Math.round(usagePercent)}%)
              {isOverLimit && ` - ${t('overLimitWarning')}`}
            </Text>
          </Box>
        )}

        {softHardError && (
          <Alert color="red" variant="light">
            {softHardError}
          </Alert>
        )}

        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={onClose}>
            {t('cancel')}
          </Button>
          <Button
            loading={mutation.isPending}
            onClick={handleSave}
            disabled={!!softHardError}
          >
            {t('save')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
