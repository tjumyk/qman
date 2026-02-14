import { useQuery } from '@tanstack/react-query'
import { Stack, Text, SimpleGrid, Card, Badge, Loader, Alert, Anchor, Group } from '@mantine/core'
import { IconGauge } from '@tabler/icons-react'
import { useNavigate } from 'react-router-dom'
import { fetchQuotas } from '../api'
import { useI18n } from '../i18n'
import { computeDashboardStats, computeNeedsAttention } from '../utils/dashboardStats'
import { getQuotaStatusLabelKey } from '../utils/quotaStatus'

export function DashboardPage() {
  const navigate = useNavigate()
  const { t } = useI18n()
  const { data, isLoading, error } = useQuery({ queryKey: ['quotas'], queryFn: fetchQuotas })

  if (isLoading) {
    return (
      <Stack align="center" gap="md" py="xl">
        <Loader size="lg" />
        <Text c="dimmed">{t('loading')}</Text>
      </Stack>
    )
  }
  if (error) {
    return (
      <Alert color="red" title={t('error')}>
        {error instanceof Error ? error.message : t('failedToLoadQuotas')}
      </Alert>
    )
  }
  if (!data) return null

  const stats = computeDashboardStats(data)
  const attention = computeNeedsAttention(data, 20)

  return (
    <Stack gap="xl">
      <Group gap="sm">
        <IconGauge size={24} />
        <Text size="lg" fw={600}>
          {t('dashboard')}
        </Text>
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }} spacing="md">
        <Card shadow="sm" padding="lg" radius="md" withBorder>
          <Text size="sm" c="dimmed">
            {t('totalHosts')}
          </Text>
          <Text size="xl" fw={700}>
            {stats.hostCount}
          </Text>
        </Card>
        <Card shadow="sm" padding="lg" radius="md" withBorder>
          <Text size="sm" c="dimmed">
            {t('devicesWithQuota')}
          </Text>
          <Text size="xl" fw={700}>
            {stats.deviceCount}
          </Text>
        </Card>
        <Card shadow="sm" padding="lg" radius="md" withBorder>
          <Text size="sm" c="dimmed">
            {t('usersOverSoft')}
          </Text>
          <Text size="xl" fw={700} c="yellow.7">
            {stats.usersOverSoft}
          </Text>
        </Card>
        <Card shadow="sm" padding="lg" radius="md" withBorder>
          <Text size="sm" c="dimmed">
            {t('usersOverHard')}
          </Text>
          <Text size="xl" fw={700} c="red.7">
            {stats.usersOverHard}
          </Text>
        </Card>
      </SimpleGrid>
      <Card shadow="sm" padding="lg" radius="md" withBorder>
        <Text size="md" fw={600} mb="md">
          {t('needsAttention')}
        </Text>
        {attention.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t('noUsersOverLimit')}
          </Text>
        ) : (
          <Stack gap="xs">
            {attention.map((item) => (
              <Anchor
                key={`${item.hostId}-${item.deviceName}-${item.uid}`}
                size="sm"
                onClick={() =>
                  navigate(`/manage/hosts/${encodeURIComponent(item.hostId)}/devices/${encodeURIComponent(item.deviceName)}`)
                }
              >
                {item.name} (uid {item.uid}) on {item.hostId} / {item.deviceName}{' '}
                <Badge size="xs" color={item.status === 'over' ? 'red' : 'yellow'} variant="light">
                  {t(getQuotaStatusLabelKey(item.status))}
                </Badge>
              </Anchor>
            ))}
          </Stack>
        )}
      </Card>
    </Stack>
  )
}
