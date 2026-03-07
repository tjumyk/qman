import { useState, useEffect, useMemo } from 'react'
import {
  Modal,
  Stack,
  Group,
  Button,
  Text,
  Checkbox,
  Alert,
  Progress,
  Loader,
  NumberInput,
} from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { notifications } from '@mantine/notifications'
import { IconAlertTriangle } from '@tabler/icons-react'
import { fetchHostUsers, setBatchQuota, getErrorMessage } from '../api'
import { useI18n } from '../i18n'
import { BlockLimitEditor } from './BlockLimitEditor'
import { BlockSize } from './BlockSize'
import type { DeviceQuota, UserQuota, BatchQuotaRequest, DeviceDefaultQuota } from '../api/schemas'
import { isDeviceDefaultNonEmpty } from './DefaultQuotaModal'

interface BatchQuotaModalProps {
  opened: boolean
  onClose: () => void
  hostId: string
  device: DeviceQuota
  /** When set and non-empty, show "Fill from default" button to populate form. */
  deviceDefault?: DeviceDefaultQuota | null
}

export function BatchQuotaModal({
  opened,
  onClose,
  hostId,
  device,
  deviceDefault,
}: BatchQuotaModalProps) {
  const isZfs = device.user_quota_format === 'zfs'
  const isDocker = device.user_quota_format === 'docker'
  const isSingleLimitFormat = isZfs || isDocker
  const queryClient = useQueryClient()
  const { t } = useI18n()

  const [blockSoft, setBlockSoft] = useState(0)
  const [blockHard, setBlockHard] = useState(0)
  const [inodeSoft, setInodeSoft] = useState(0)
  const [inodeHard, setInodeHard] = useState(0)
  const [preserveNonzero, setPreserveNonzero] = useState(true)
  const [preserveUsageExceeds, setPreserveUsageExceeds] = useState(true)

  // Reset form when modal opens
  useEffect(() => {
    if (opened) {
      setBlockSoft(0)
      setBlockHard(0)
      setInodeSoft(0)
      setInodeHard(0)
      setPreserveNonzero(true)
      setPreserveUsageExceeds(true)
    }
  }, [opened])

  // Fetch all host users
  const { data: hostUsers, isLoading: loadingUsers } = useQuery({
    queryKey: ['hostUsers', hostId],
    queryFn: () => fetchHostUsers(hostId),
    enabled: opened,
  })

  // Build a map of current quotas by username
  const currentQuotasByName = useMemo(() => {
    const map = new Map<string, UserQuota>()
    for (const q of device.user_quotas ?? []) {
      map.set(q.name, q)
    }
    return map
  }, [device.user_quotas])

  // Calculate preview metrics
  const preview = useMemo(() => {
    if (!hostUsers) {
      return {
        totalUsers: 0,
        affectedUsers: 0,
        skippedUsers: 0,
        totalAllocation: 0,
        overSalePercent: 0,
      }
    }

    let affectedUsers = 0
    let skippedUsers = 0
    let totalAllocation = 0

    for (const user of hostUsers) {
      const current = currentQuotasByName.get(user.host_user_name)

      // Check preserve conditions
      let skip = false

      if (preserveNonzero && current) {
        if (
          current.block_hard_limit > 0 ||
          current.block_soft_limit > 0 ||
          current.inode_hard_limit > 0 ||
          current.inode_soft_limit > 0
        ) {
          skip = true
        }
      }

      if (preserveUsageExceeds && current && !skip) {
        const blockCurrentKb = current.block_current / 1024
        if (blockHard > 0 && blockCurrentKb > blockHard) {
          skip = true
        } else if (blockSoft > 0 && blockCurrentKb > blockSoft) {
          skip = true
        }
      }

      if (skip) {
        skippedUsers++
        // Add existing quota to total allocation
        if (current) {
          totalAllocation += (current.block_hard_limit || current.block_soft_limit) * 1024
        }
      } else {
        affectedUsers++
        // Add new quota to total allocation
        totalAllocation += (blockHard || blockSoft) * 1024
      }
    }

    const deviceTotal = device.usage?.total ?? 0
    const overSalePercent =
      deviceTotal > 0 ? ((totalAllocation / deviceTotal) * 100 - 100) : 0

    return {
      totalUsers: hostUsers.length,
      affectedUsers,
      skippedUsers,
      totalAllocation,
      overSalePercent,
    }
  }, [
    hostUsers,
    currentQuotasByName,
    preserveNonzero,
    preserveUsageExceeds,
    blockSoft,
    blockHard,
  ])

  const mutation = useMutation({
    mutationFn: (body: BatchQuotaRequest) => setBatchQuota(hostId, body),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['quotas'] })
      notifications.show({
        message: t('batchQuotaSuccess')
          .replace('{updated}', String(result.updated_users))
          .replace('{total}', String(result.total_users)),
        color: 'green',
      })
      onClose()
    },
    onError: (err: unknown) => {
      notifications.show({
        message: getErrorMessage(err, t('batchQuotaFailed')),
        color: 'red',
      })
    },
  })

  const handleApply = () => {
    const body: BatchQuotaRequest = {
      device: device.name,
      block_soft_limit: isSingleLimitFormat ? blockHard : blockSoft,
      block_hard_limit: blockHard,
      inode_soft_limit: isSingleLimitFormat ? 0 : inodeSoft,
      inode_hard_limit: isSingleLimitFormat ? 0 : inodeHard,
      preserve_if_nonzero: preserveNonzero,
      preserve_if_usage_exceeds: preserveUsageExceeds,
    }
    mutation.mutate(body)
  }

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

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('batchSetQuota')}
      size="lg"
    >
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          {hostId} / {device.name}
        </Text>

        {isDeviceDefaultNonEmpty(deviceDefault) && (
          <Button
            variant="light"
            size="sm"
            onClick={() => {
              if (isSingleLimitFormat) {
                setBlockHard(deviceDefault!.block_hard_limit)
                setBlockSoft(deviceDefault!.block_hard_limit)
              } else {
                setBlockSoft(deviceDefault!.block_soft_limit)
                setBlockHard(deviceDefault!.block_hard_limit)
                setInodeSoft(deviceDefault!.inode_soft_limit)
                setInodeHard(deviceDefault!.inode_hard_limit)
              }
            }}
          >
            {t('fillFromDefault')}
          </Button>
        )}

        {loadingUsers ? (
          <Group justify="center" py="md">
            <Loader size="sm" />
            <Text size="sm" c="dimmed">{t('loading')}</Text>
          </Group>
        ) : (
          <>
            {/* Quota limit editors */}
            {isSingleLimitFormat ? (
              <div>
                <Text size="sm" fw={500} mb={4}>
                  {t('quotaLimit')}
                </Text>
                <BlockLimitEditor value={blockHard} onChange={(v) => {
                  setBlockHard(v)
                  setBlockSoft(v)
                }} />
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

            {/* Preserve options */}
            <Stack gap="xs">
              <Text size="sm" fw={500}>{t('preserveOptions')}</Text>
              <Checkbox
                label={t('preserveIfNonzero')}
                checked={preserveNonzero}
                onChange={(e) => setPreserveNonzero(e.currentTarget.checked)}
              />
              <Checkbox
                label={t('preserveIfUsageExceeds')}
                checked={preserveUsageExceeds}
                onChange={(e) => setPreserveUsageExceeds(e.currentTarget.checked)}
              />
            </Stack>

            {/* Validation error */}
            {softHardError && (
              <Alert color="red" variant="light">
                {softHardError}
              </Alert>
            )}

            {/* Preview section */}
            <Alert
              variant="light"
              color={preview.overSalePercent > 0 ? 'yellow' : 'blue'}
              icon={preview.overSalePercent > 0 ? <IconAlertTriangle size={16} /> : undefined}
              title={t('preview')}
            >
              <Stack gap="xs">
                <Group gap="lg">
                  <Text size="sm">
                    {t('totalHostUsers')}: <strong>{preview.totalUsers}</strong>
                  </Text>
                  <Text size="sm">
                    {t('usersToUpdate')}: <strong>{preview.affectedUsers}</strong>
                  </Text>
                  <Text size="sm">
                    {t('usersToSkip')}: <strong>{preview.skippedUsers}</strong>
                  </Text>
                </Group>

                <Group gap="lg">
                  <Text size="sm">
                    {t('totalQuotaAllocation')}:{' '}
                    <strong><BlockSize size={preview.totalAllocation} /></strong>
                  </Text>
                  <Text size="sm">
                    {t('deviceTotal')}:{' '}
                    <strong><BlockSize size={device.usage?.total ?? 0} /></strong>
                  </Text>
                </Group>

                {preview.totalAllocation > 0 && device.usage?.total && (
                  <>
                    <Progress
                      value={Math.min((preview.totalAllocation / device.usage.total) * 100, 100)}
                      color={preview.overSalePercent > 0 ? 'yellow' : 'blue'}
                      size="sm"
                    />
                    {preview.overSalePercent > 0 ? (
                      <Text size="sm" c="yellow.7" fw={500}>
                        {t('overSoldLabel')}: {preview.overSalePercent.toFixed(1)}%
                      </Text>
                    ) : (
                      <Text size="sm" c="dimmed">
                        {t('utilizationPercent')}: {((preview.totalAllocation / device.usage.total) * 100).toFixed(1)}%
                      </Text>
                    )}
                  </>
                )}
              </Stack>
            </Alert>

            {/* Action buttons */}
            <Group justify="flex-end" mt="md">
              <Button variant="default" onClick={onClose}>
                {t('cancel')}
              </Button>
              <Button
                loading={mutation.isPending}
                onClick={handleApply}
                disabled={!!softHardError || preview.affectedUsers === 0}
              >
                {t('apply')} ({preview.affectedUsers} {t('userCount')})
              </Button>
            </Group>
          </>
        )}
      </Stack>
    </Modal>
  )
}
