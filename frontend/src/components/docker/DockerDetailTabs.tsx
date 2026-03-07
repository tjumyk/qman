import { useState } from 'react'
import { Tabs, Stack } from '@mantine/core'
import { IconUsers, IconBox, IconPhoto, IconDatabase } from '@tabler/icons-react'
import { useI18n } from '../../i18n'
import { DeviceInfo } from '../DeviceInfo'
import { UserQuotaTable } from '../UserQuotaTable'
import { ContainersTab } from './ContainersTab'
import { ImagesTab } from './ImagesTab'
import { VolumesTab } from './VolumesTab'
import type { DeviceQuota } from '../../api/schemas'

interface DockerDetailTabsProps {
  hostId: string
  device: DeviceQuota
}

export function DockerDetailTabs({ hostId, device }: DockerDetailTabsProps) {
  const { t } = useI18n()
  const [activeTab, setActiveTab] = useState<string | null>('users')

  return (
    <Stack gap="md">
      <DeviceInfo device={device} />

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
          <UserQuotaTable hostId={hostId} device={device} />
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
    </Stack>
  )
}
