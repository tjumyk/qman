import { useQuery } from '@tanstack/react-query'
import { Stack, Text, Card, Loader, Alert, Group, Badge } from '@mantine/core'
import { IconServer, IconCheck, IconX } from '@tabler/icons-react'
import { useNavigate } from 'react-router-dom'
import { fetchQuotas, pingHosts, type HostPingStatus } from '../api'
import { useI18n } from '../i18n'

export function HostListPage() {
  const navigate = useNavigate()
  const { t } = useI18n()
  const { data, isLoading, error } = useQuery({ queryKey: ['quotas'], queryFn: fetchQuotas })
  const { data: pingData } = useQuery({
    queryKey: ['hosts-ping'],
    queryFn: pingHosts,
    refetchInterval: 10000, // Ping every 10 seconds
    refetchIntervalInBackground: true, // Continue pinging when tab is in background
  })

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
          const pingStatus: HostPingStatus | undefined = pingData?.[hostId]
          const isOnline = pingStatus?.status === 'ok'
          const latency = pingStatus?.latency_ms
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
                <Group gap="sm">
                  <Text fw={500}>{hostId}</Text>
                  {pingStatus && (
                    <Group gap={4}>
                      {isOnline ? (
                        <Badge
                          color="green"
                          variant="light"
                          leftSection={<IconCheck size={12} />}
                        >
                          {latency !== undefined ? `${latency}ms` : t('online')}
                        </Badge>
                      ) : (
                        <Badge
                          color="red"
                          variant="light"
                          leftSection={<IconX size={12} />}
                        >
                          {pingStatus.error || t('offline')}
                        </Badge>
                      )}
                    </Group>
                  )}
                </Group>
                <Group gap="xs">
                  {hasError ? (
                    <Badge color="red">{t('error')}</Badge>
                  ) : (
                    <Badge variant="light">{deviceCount} {t('deviceCount')}</Badge>
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
