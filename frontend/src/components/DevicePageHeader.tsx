import { Group, Text } from '@mantine/core'
import { IconDisc } from '@tabler/icons-react'

export interface DevicePageHeaderProps {
  hostId: string
  deviceName: string
}

export function DevicePageHeader({ hostId, deviceName }: DevicePageHeaderProps) {
  return (
    <Group justify="space-between" gap="sm">
      <Group gap="sm">
        <IconDisc size={24} />
        <Text size="lg" fw={600}>
          {hostId} › {deviceName}
        </Text>
      </Group>
    </Group>
  )
}
