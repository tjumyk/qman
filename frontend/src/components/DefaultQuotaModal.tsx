import { useState, useEffect, useMemo } from 'react'
import { Modal, Stack, Group, Button, Text, NumberInput, Loader, Alert } from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { notifications } from '@mantine/notifications'
import { getDeviceDefaultQuota, setDeviceDefaultQuota, getErrorMessage } from '../api'
import { useI18n } from '../i18n'
import { BlockLimitEditor } from './BlockLimitEditor'
import type { DeviceQuota, DeviceDefaultQuota, SetDeviceDefaultQuotaBody } from '../api/schemas'

interface DefaultQuotaModalProps {
  opened: boolean
  onClose: () => void
  hostId: string
  device: DeviceQuota
}

const isSingleLimitFormat = (format?: string) => format === 'zfs' || format === 'docker'

export function DefaultQuotaModal({
  opened,
  onClose,
  hostId,
  device,
}: DefaultQuotaModalProps) {
  const { t } = useI18n()
  const isSingle = isSingleLimitFormat(device.user_quota_format)
  const queryClient = useQueryClient()

  const [blockSoft, setBlockSoft] = useState(0)
  const [blockHard, setBlockHard] = useState(0)
  const [inodeSoft, setInodeSoft] = useState(0)
  const [inodeHard, setInodeHard] = useState(0)

  const { data: currentDefault, isLoading } = useQuery({
    queryKey: ['deviceDefaultQuota', hostId, device.name],
    queryFn: () => getDeviceDefaultQuota(hostId, device.name),
    enabled: opened && !!hostId && !!device.name,
  })

  useEffect(() => {
    if (currentDefault) {
      setBlockSoft(currentDefault.block_soft_limit)
      setBlockHard(currentDefault.block_hard_limit)
      setInodeSoft(currentDefault.inode_soft_limit)
      setInodeHard(currentDefault.inode_hard_limit)
    } else if (opened && !currentDefault && !isLoading) {
      setBlockSoft(0)
      setBlockHard(0)
      setInodeSoft(0)
      setInodeHard(0)
    }
  }, [currentDefault, opened, isLoading])

  const softHardError = useMemo(() => {
    if (isSingle) return null
    if (blockSoft > 0 && blockHard > 0 && blockSoft > blockHard) {
      return t('softExceedsHardError')
    }
    if (inodeSoft > 0 && inodeHard > 0 && inodeSoft > inodeHard) {
      return t('softExceedsHardError')
    }
    return null
  }, [isSingle, blockSoft, blockHard, inodeSoft, inodeHard, t])

  const mutation = useMutation({
    mutationFn: (body: SetDeviceDefaultQuotaBody) =>
      setDeviceDefaultQuota(hostId, device.name, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deviceDefaultQuota', hostId, device.name] })
      queryClient.invalidateQueries({ queryKey: ['quotas'] })
      notifications.show({ message: t('defaultQuotaSaved'), color: 'green' })
      onClose()
    },
    onError: (err: unknown) => {
      notifications.show({
        message: getErrorMessage(err, t('defaultQuotaSaveFailed')),
        color: 'red',
      })
    },
  })

  const handleSave = () => {
    if (softHardError) return
    mutation.mutate({
      block_soft_limit: isSingle ? blockHard : blockSoft,
      block_hard_limit: blockHard,
      inode_soft_limit: isSingle ? 0 : inodeSoft,
      inode_hard_limit: isSingle ? 0 : inodeHard,
    })
  }

  const isMobile = useMediaQuery('(max-width: 36em)')
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('defaultQuota')}
      size="sm"
      fullScreen={isMobile}
    >
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          {hostId} / {device.name}
        </Text>
        <Alert variant="light" color="gray" py="xs">
          <Text size="sm" c="dimmed">
            {t('defaultQuotaUsageMessage')}
          </Text>
        </Alert>
        {isLoading ? (
          <Group justify="center" py="md">
            <Loader size="sm" />
          </Group>
        ) : (
          <>
            {currentDefault === null && (
              <Text size="sm" c="dimmed">
                {t('defaultQuotaNotSet')}
              </Text>
            )}
            {isSingle ? (
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
                />
              </div>
            ) : (
              <>
                <div>
                  <Text size="sm" fw={500} mb={4}>
                    {t('blockSoftLimit1k')}
                  </Text>
                  <BlockLimitEditor value={blockSoft} onChange={setBlockSoft} />
                </div>
                <div>
                  <Text size="sm" fw={500} mb={4}>
                    {t('blockHardLimit1k')}
                  </Text>
                  <BlockLimitEditor value={blockHard} onChange={setBlockHard} />
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
          </>
        )}
        {softHardError && (
          <Alert color="red" variant="light">
            {softHardError}
          </Alert>
        )}
        <Group justify="flex-end" mt="md" wrap="wrap">
          <Button variant="default" onClick={onClose} w={{ base: '100%', xs: 'auto' }}>
            {t('cancel')}
          </Button>
          <Button
            loading={mutation.isPending}
            onClick={handleSave}
            disabled={!!softHardError}
            w={{ base: '100%', xs: 'auto' }}
          >
            {t('save')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

export function isDeviceDefaultNonEmpty(d: DeviceDefaultQuota | null | undefined): boolean {
  if (!d) return false
  return (
    d.block_soft_limit > 0 ||
    d.block_hard_limit > 0 ||
    d.inode_soft_limit > 0 ||
    d.inode_hard_limit > 0
  )
}
