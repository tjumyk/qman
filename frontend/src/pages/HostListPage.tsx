import { useQuery } from '@tanstack/react-query'
import { Stack, Text, Card, Loader, Alert, Group, Badge } from '@mantine/core'
import { IconServer } from '@tabler/icons-react'
import { useNavigate } from 'react-router-dom'
import { fetchQuotas } from '../api'
import { useI18n } from '../i18n'

export function HostListPage() {
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

  const hostIds = Object.keys(data).sort()

  return (
    <Stack gap="md">
      <Group gap="sm">
        <IconServer size={24} />
        <Text size="lg" fw={600}>
          {t('hosts')}
        </Text>
      </Group>
      <Stack gap="xs">
        {hostIds.map((hostId) => {
          const payload = data[hostId]
          const hasError = !!payload.error
          const deviceCount = payload.results?.length ?? 0
          return (
            <Card
              key={hostId}
              shadow="sm"
              padding="md"
              radius="md"
              withBorder
              style={{ cursor: hasError ? 'default' : 'pointer' }}
              onClick={() => !hasError && deviceCount > 0 && navigate(`/manage/hosts/${encodeURIComponent(hostId)}`)}
            >
              <Group justify="space-between">
                <Text fw={500}>{hostId}</Text>
                {hasError ? (
                  <Badge color="red">{t('error')}</Badge>
                ) : (
                  <Badge variant="light">{deviceCount} {t('deviceCount')}</Badge>
                )}
              </Group>
            </Card>
          )
        })}
      </Stack>
    </Stack>
  )
}
