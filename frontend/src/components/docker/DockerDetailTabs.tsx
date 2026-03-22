import { useCallback, useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Tabs, Stack } from '@mantine/core'
import { IconUsers, IconBox, IconPhoto, IconDatabase } from '@tabler/icons-react'
import { useI18n } from '../../i18n'
import { DeviceInfo } from '../DeviceInfo'
import { UserQuotaTable } from '../UserQuotaTable'
import { ContainersTab } from './ContainersTab'
import { ImagesTab } from './ImagesTab'
import { VolumesTab } from './VolumesTab'
import type { DeviceQuota } from '../../api/schemas'

const DOCKER_DETAIL_TABS = ['users', 'containers', 'images', 'volumes'] as const
type DockerDetailTab = (typeof DOCKER_DETAIL_TABS)[number]

function isDockerDetailTab(v: string | null): v is DockerDetailTab {
  return v != null && (DOCKER_DETAIL_TABS as readonly string[]).includes(v)
}

interface DockerDetailTabsProps {
  hostId: string
  device: DeviceQuota
}

export function DockerDetailTabs({ hostId, device }: DockerDetailTabsProps) {
  const { t } = useI18n()
  const [searchParams, setSearchParams] = useSearchParams()

  const activeTab = useMemo((): DockerDetailTab => {
    const raw = searchParams.get('tab')
    return isDockerDetailTab(raw) ? raw : 'users'
  }, [searchParams])

  useEffect(() => {
    const raw = searchParams.get('tab')
    if (raw != null && !isDockerDetailTab(raw)) {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          next.delete('tab')
          return next
        },
        { replace: true },
      )
    }
  }, [searchParams, setSearchParams])

  const handleTabChange = useCallback(
    (value: string | null) => {
      if (!isDockerDetailTab(value)) return
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (value === 'users') next.delete('tab')
          else next.set('tab', value)
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  return (
    <Stack gap="md">
      <DeviceInfo device={device} />

      <Tabs value={activeTab} onChange={handleTabChange} keepMounted={false}>
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
