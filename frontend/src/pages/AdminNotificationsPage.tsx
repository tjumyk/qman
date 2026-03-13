import { useQuery } from '@tanstack/react-query'
import { Stack, Text, Loader, Alert, Group, Card, Table, ScrollArea, Badge, Select, TextInput, Pagination, Modal, Box } from '@mantine/core'
import { IconBell } from '@tabler/icons-react'
import { useState } from 'react'
import DOMPurify from 'dompurify'
import { fetchAdminNotifications, fetchAdminNotificationDetail } from '../api'
import type { NotificationLogEntry, NotificationDetail } from '../api/schemas'
import { useI18n } from '../i18n'

export function AdminNotificationsPage() {
  const { t } = useI18n()
  const [page, setPage] = useState(1)
  const [hostFilter, setHostFilter] = useState('')
  const [emailFilter, setEmailFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | null>(null)
  const [selected, setSelected] = useState<NotificationLogEntry | null>(null)

  const { data: detail } = useQuery({
    queryKey: ['admin-notification-detail', selected?.id],
    queryFn: (): Promise<NotificationDetail> => fetchAdminNotificationDetail(selected!.id),
    enabled: !!selected,
  })

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin-notifications', page, hostFilter, emailFilter, statusFilter],
    queryFn: () =>
      fetchAdminNotifications({
        page,
        pageSize: 50,
        hostId: hostFilter.trim() || undefined,
        email: emailFilter.trim() || undefined,
        sendStatus: statusFilter || undefined,
      }),
    keepPreviousData: true,
  })

  if (isLoading && !data) {
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
        {error instanceof Error ? error.message : t('failedToLoadNotifications')}
      </Alert>
    )
  }

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const pageSize = data?.page_size ?? 50
  const totalPages = total > 0 ? Math.ceil(total / pageSize) : 1

  return (
    <Stack gap="md">
      <Group gap="sm">
        <IconBell size={24} />
        <Text size="lg" fw={600}>
          {t('notificationCenter')}
        </Text>
      </Group>
      <Text size="sm" c="dimmed">
        {t('notificationCenterDescription')}
      </Text>
      <Card withBorder padding="sm">
        <Group gap="sm" wrap="wrap">
          <TextInput
            label={t('host')}
            placeholder={t('host')}
            value={hostFilter}
            onChange={(e) => {
              setPage(1)
              setHostFilter(e.currentTarget.value)
            }}
            w={{ base: '100%', sm: 200 }}
          />
          <TextInput
            label={t('email')}
            placeholder={t('email')}
            value={emailFilter}
            onChange={(e) => {
              setPage(1)
              setEmailFilter(e.currentTarget.value)
            }}
            w={{ base: '100%', sm: 260 }}
          />
          <Select
            label={t('sendStatus')}
            placeholder={t('sendStatus')}
            data={[
              { value: 'success', label: t('sendStatusSuccess') },
              { value: 'failed', label: t('sendStatusFailed') },
              { value: 'skipped', label: t('sendStatusSkipped') },
            ]}
            value={statusFilter}
            onChange={(v) => {
              setPage(1)
              setStatusFilter(v)
            }}
            clearable
            w={{ base: '100%', sm: 200 }}
          />
        </Group>
      </Card>
      {items.length === 0 ? (
        <Alert color="blue" title={t('notifications')}>
          {t('noNotifications')}
        </Alert>
      ) : (
        <Card withBorder padding="xs">
          <ScrollArea.Autosize mah={500}>
            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('time')}</Table.Th>
                  <Table.Th>{t('email')}</Table.Th>
                  <Table.Th>{t('host')}</Table.Th>
                  <Table.Th>{t('eventType')}</Table.Th>
                  <Table.Th>{t('sendStatus')}</Table.Th>
                  <Table.Th>{t('subject')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {items.map((n) => (
                  <Table.Tr key={n.id} onClick={() => setSelected(n)} style={{ cursor: 'pointer' }}>
                    <Table.Td>{n.created_at ?? ''}</Table.Td>
                    <Table.Td>{n.email ?? ''}</Table.Td>
                    <Table.Td>
                      {n.host_id ?? ''} {n.host_user_name ? ` / ${n.host_user_name}` : ''}
                    </Table.Td>
                    <Table.Td>{n.event_type}</Table.Td>
                    <Table.Td>
                      <Badge
                        size="sm"
                        color={
                          n.send_status === 'success'
                            ? 'green'
                            : n.send_status === 'failed'
                            ? 'red'
                            : 'yellow'
                        }
                        variant="light"
                      >
                        {n.send_status}
                      </Badge>
                    </Table.Td>
                    <Table.Td>{n.subject ?? ''}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea.Autosize>
          {totalPages > 1 && (
            <Group justify="flex-end" mt="sm">
              <Pagination value={page} onChange={setPage} total={totalPages} size="sm" />
            </Group>
          )}
        </Card>
      )}

      <Modal opened={selected !== null} onClose={() => setSelected(null)} title={t('details')} size="xl" centered>
        {selected && (
          <Stack gap="sm">
            <Text size="sm">
              <strong>{t('time')}:</strong> {selected.created_at ?? ''}
            </Text>
            <Text size="sm">
              <strong>{t('email')}:</strong> {selected.email ?? ''}
            </Text>
            <Text size="sm">
              <strong>{t('host')}:</strong> {selected.host_id ?? ''}{' '}
              {selected.host_user_name ? ` / ${selected.host_user_name}` : ''}
            </Text>
            <Text size="sm">
              <strong>{t('eventType')}:</strong> {selected.event_type}
            </Text>
            <Text size="sm">
              <strong>{t('sendStatus')}:</strong> {selected.send_status}
            </Text>
            {selected.error_message && (
              <Text size="sm" c="red">
                <strong>{t('error')}:</strong> {selected.error_message}
              </Text>
            )}
            <Box mt="sm">
              <Text size="sm" fw={500} mb={4}>
                {t('subject')}
              </Text>
              <Text size="sm">{selected.subject ?? ''}</Text>
            </Box>
            {detail && (
              <>
                <Box mt="sm">
                  <Text size="sm" fw={500} mb={4}>
                    {t('bodyPreview')}
                  </Text>
                  <Box
                    style={{
                      backgroundColor: 'var(--mantine-color-default-hover)',
                      padding: 8,
                      borderRadius: 4,
                      maxHeight: 260,
                      overflowY: 'auto',
                    }}
                  >
                    <div
                      dangerouslySetInnerHTML={{
                        __html: DOMPurify.sanitize(detail.body_html ?? detail.body_preview ?? ''),
                      }}
                    />
                  </Box>
                </Box>
                {detail.events.length > 0 && (
                  <Box mt="sm">
                    <Text size="sm" fw={500} mb={4}>
                      {t('notifications')}
                    </Text>
                    <ScrollArea.Autosize mah={260}>
                      <Table striped highlightOnHover withColumnBorders>
                        <Table.Thead>
                          <Table.Tr>
                            <Table.Th>{t('time')}</Table.Th>
                            <Table.Th>{t('host')}</Table.Th>
                            <Table.Th>{t('eventType')}</Table.Th>
                            <Table.Th>{t('subject')}</Table.Th>
                          </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                          {detail.events.map((ev) => (
                            <Table.Tr key={ev.id}>
                              <Table.Td>{ev.created_at ?? ''}</Table.Td>
                              <Table.Td>
                                {ev.host_id ?? ''} {ev.host_user_name ? ` / ${ev.host_user_name}` : ''}
                              </Table.Td>
                              <Table.Td>{ev.event_type}</Table.Td>
                              <Table.Td>{detail.subject ?? ''}</Table.Td>
                            </Table.Tr>
                          ))}
                        </Table.Tbody>
                      </Table>
                    </ScrollArea.Autosize>
                  </Box>
                )}
                {detail.events.length > 0 && (
                  <Box mt="sm">
                    <Text size="sm" fw={500} mb={4}>
                      {t('payloadJson')}
                    </Text>
                    <ScrollArea.Autosize mah={260}>
                      <Box
                        component="pre"
                        style={{
                          whiteSpace: 'pre-wrap',
                          backgroundColor: 'var(--mantine-color-default-hover)',
                          padding: 8,
                          borderRadius: 4,
                        }}
                      >
                        {JSON.stringify(
                          detail.events.map((ev) => {
                            try {
                              return ev.payload ? JSON.parse(ev.payload) : null
                            } catch {
                              return ev.payload
                            }
                          }),
                          null,
                          2,
                        )}
                      </Box>
                    </ScrollArea.Autosize>
                  </Box>
                )}
              </>
            )}
          </Stack>
        )}
      </Modal>
    </Stack>
  )
}

