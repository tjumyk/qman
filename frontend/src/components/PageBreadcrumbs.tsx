import { Breadcrumbs, Anchor, Text } from '@mantine/core'
import { useLocation, useParams, Link } from 'react-router-dom'
import { useI18n } from '../i18n'

type BreadcrumbItem = { path: string; label: string; current: boolean }

function buildBreadcrumbItems(pathname: string, params: { hostId?: string; deviceName?: string }, t: (key: string) => string): BreadcrumbItem[] {
  const path = pathname.replace(/\/$/, '') || '/'
  if (path === '/') return []

  if (path === '/my-usage') {
    return [{ path: '/my-usage', label: t('myUsage'), current: true }]
  }

  if (path === '/my-mappings') {
    return [{ path: '/my-mappings', label: t('myMappings'), current: true }]
  }

  if (path === '/manage') {
    return [{ path: '/manage', label: t('dashboard'), current: true }]
  }

  if (path === '/manage/hosts') {
    return [
      { path: '/manage', label: t('dashboard'), current: false },
      { path: '/manage/hosts', label: t('hostList'), current: true },
    ]
  }

  if (path === '/manage/mappings') {
    return [
      { path: '/manage', label: t('dashboard'), current: false },
      { path: '/manage/mappings', label: t('userMappings'), current: true },
    ]
  }

  const { hostId, deviceName } = params
  // Path from useLocation is encoded; params from useParams are decoded
  const pathSegments = path.split('/').filter(Boolean)
  const isHostDetail = pathSegments[0] === 'manage' && pathSegments[1] === 'hosts' && pathSegments.length === 3
  if (hostId && isHostDetail) {
    return [
      { path: '/manage', label: t('dashboard'), current: false },
      { path: '/manage/hosts', label: t('hostList'), current: false },
      { path: `/manage/hosts/${encodeURIComponent(hostId)}`, label: hostId, current: true },
    ]
  }

  const isDevicePage = pathSegments[0] === 'manage' && pathSegments[1] === 'hosts' && pathSegments[3] === 'devices' && pathSegments.length === 5
  if (hostId && deviceName && isDevicePage) {
    return [
      { path: '/manage', label: t('dashboard'), current: false },
      { path: '/manage/hosts', label: t('hostList'), current: false },
      { path: `/manage/hosts/${encodeURIComponent(hostId)}`, label: hostId, current: false },
      { path: `/manage/hosts/${encodeURIComponent(hostId)}/devices/${encodeURIComponent(deviceName)}`, label: deviceName, current: true },
    ]
  }

  return []
}

export function PageBreadcrumbs() {
  const location = useLocation()
  const params = useParams<{ hostId?: string; deviceName?: string }>()
  const { t } = useI18n()
  const items = buildBreadcrumbItems(location.pathname, params, t)

  if (items.length <= 1) return null

  return (
    <Breadcrumbs separator="/" separatorMargin="xs" mb="md">
      {items.map((item) =>
        item.current ? (
          <Text key={item.path} size="sm" fw={500} c="dimmed">
            {item.label}
          </Text>
        ) : (
          <Anchor key={item.path} size="sm" component={Link} to={item.path} c="dimmed">
            {item.label}
          </Anchor>
        )
      )}
    </Breadcrumbs>
  )
}
