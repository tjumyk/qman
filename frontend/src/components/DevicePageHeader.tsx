import { Group, Text } from '@mantine/core'
import { IconDisc } from '@tabler/icons-react'

export interface DevicePageHeaderProps {
  hostId: string
  deviceName: string
}

export function DevicePageHeader({ hostId, deviceName }: DevicePageHeaderProps) {
  return (
    <Group justify="space-between" gap="sm" wrap="wrap">
      <Group gap="sm" style={{ minWidth: 0 }}>
        <IconDisc size={24} />
        <Text size="lg" fw={600} style={{ wordBreak: 'break-word' }}>
          {hostId} › {deviceName}
        </Text>
      </Group>
    </Group>
  )
}
