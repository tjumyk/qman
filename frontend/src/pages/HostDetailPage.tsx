import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { Stack, Text, Card, Loader, Alert, Group, Badge } from '@mantine/core'
import { IconServer } from '@tabler/icons-react'
import { fetchQuotas } from '../api'
import { useI18n } from '../i18n'
import { getQuotaStatus } from '../utils/quotaStatus'
import { DeviceUsage } from '../components/DeviceUsage'

export function HostDetailPage() {
  const { hostId } = useParams<{ hostId: string }>()
  const navigate = useNavigate()
  const { t } = useI18n()
  const { data, isLoading, error } = useQuery({ queryKey: ['quotas'], queryFn: fetchQuotas })

  if (!hostId) return <Alert color="red">{t('missingHost')}</Alert>
  if (isLoading) {
    return (
      <Stack align="center" gap="md" py="xl">
        <Loader size="lg" />
        <Text c="dimmed">{t('loading')}</Text>
      </Stack>
    )
  }
  if (error || !data) {
    return (
      <Alert color="red" title={t('error')}>
        {error instanceof Error ? error.message : t('failedToLoadQuotas')}
      </Alert>
    )
  }

  const payload = data[hostId]
  if (!payload || payload.error) {
    return <Alert color="red">{t('hostNotFoundOrError')}</Alert>
  }
  const devices = payload.results || []

  return (
    <Stack gap="md">
      <Group gap="sm">
        <IconServer size={24} />
        <Text size="lg" fw={600}>
          {hostId}
        </Text>
      </Group>
      <Stack gap="xs">
        {devices.map((dev) => {
          const users = dev.user_quotas || []
          const overSoft = users.filter((q) => getQuotaStatus(q) === 'warning').length
          const overHard = users.filter((q) => getQuotaStatus(q) === 'over').length
          const attention = overSoft + overHard
          return (
            <Card
              key={dev.name}
              shadow="sm"
              padding="md"
              radius="md"
              withBorder
              style={{ cursor: 'pointer' }}
              onClick={() =>
                navigate(
                  `/manage/hosts/${encodeURIComponent(hostId)}/devices/${encodeURIComponent(dev.name)}`
                )
              }
            >
              <Stack gap="sm">
                <Group justify="space-between" align="flex-start">
                  <Text fw={600} size="md">{dev.name}</Text>
                  <Group gap="xs">
                    <Badge variant="light" size="sm">{users.length} {t('userCount')}</Badge>
                    {attention > 0 && (
                      <Badge color={overHard > 0 ? 'red' : 'yellow'} size="sm">
                        {attention} {t('needAttentionCount')}
                      </Badge>
                    )}
                  </Group>
                </Group>
                <Text size="sm" c="dimmed">
                  {dev.fstype === 'docker' ? t('deviceTypeDocker') : dev.fstype} · {dev.mount_points.join(', ')}
                </Text>
                {dev.usage && (
                  <DeviceUsage
                    usage={dev.usage}
                    userQuotas={dev.user_quotas}
                  />
                )}
              </Stack>
            </Card>
          )
        })}
      </Stack>
    </Stack>
  )
}
