import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { Stack, Text, Card, Loader, Alert, Group, Badge } from '@mantine/core'
import { fetchQuotas } from '../api'
import { useI18n } from '../i18n'
import { getQuotaStatus } from '../utils/quotaStatus'

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
      <Text size="lg" fw={600}>
        {hostId} – {t('hostDevicesTitle')}
      </Text>
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
              <Group justify="space-between">
                <div>
                  <Text fw={500}>{dev.name}</Text>
                  <Text size="sm" c="dimmed">
                    {dev.fstype} · {dev.mount_points.join(', ')}
                  </Text>
                </div>
                <Group gap="xs">
                  <Badge variant="light">{users.length} {t('userCount')}</Badge>
                  {attention > 0 && (
                    <Badge color={overHard > 0 ? 'red' : 'yellow'}>
                      {attention} {t('needAttentionCount')}
                    </Badge>
                  )}
                </Group>
              </Group>
            </Card>
          )
        })}
      </Stack>
    </Stack>
  )
}
