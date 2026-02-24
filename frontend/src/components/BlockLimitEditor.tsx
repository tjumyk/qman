import { useState, useEffect } from 'react'
import { Group, NumberInput, Select, Button, Stack } from '@mantine/core'

interface BlockLimitEditorProps {
  /** Controlled value in 1K blocks. When provided, the editor syncs to this value. */
  value: number
  onChange: (value: number) => void
  /** Current usage in 1K blocks, used for "Match Usage" preset */
  currentUsage1k?: number
  /** Show preset buttons (default: false) */
  showPresets?: boolean
}

const units = ['KB', 'MB', 'GB', 'TB']
const GB_IN_1K = 1024 * 1024

function toValueAndUnit(blocks: number): { value: number; unitIndex: number } {
  let value = blocks
  let unitIndex = 0
  while (value > 0 && value % 1024 === 0 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return { value, unitIndex }
}

function toBlocks(value: number, unitIndex: number): number {
  let v = value
  let u = unitIndex
  while (u > 0) {
    v *= 1024
    u -= 1
  }
  return Math.round(v)
}

export function BlockLimitEditor({ value, onChange, currentUsage1k, showPresets }: BlockLimitEditorProps) {
  const [num, setNum] = useState(() => toValueAndUnit(value).value)
  const [unit, setUnit] = useState(() => toValueAndUnit(value).unitIndex)

  useEffect(() => {
    const currentBlocks = toBlocks(num, unit)
    if (currentBlocks !== value) {
      const { value: newNum, unitIndex: newUnit } = toValueAndUnit(value)
      setNum(newNum)
      setUnit(newUnit)
    }
  }, [value, num, unit])

  const notify = (n: number, u: number) => onChange(toBlocks(n, u))

  const handleNumChange = (val: string | number) => {
    const n = typeof val === 'string' ? parseFloat(val) || 0 : val
    setNum(n)
    notify(n, unit)
  }

  const handleUnitChange = (newUnitIndex: number) => {
    setUnit(newUnitIndex)
    notify(num, newUnitIndex)
  }

  const presets = showPresets ? (
    <Group gap={4} wrap="wrap">
      <Button
        size="compact-xs"
        variant={value === 0 ? 'filled' : 'light'}
        onClick={() => onChange(0)}
      >
        No Limit
      </Button>
      {currentUsage1k !== undefined && currentUsage1k > 0 && (
        <Button
          size="compact-xs"
          variant={value === currentUsage1k ? 'filled' : 'light'}
          onClick={() => onChange(currentUsage1k)}
        >
          = Usage
        </Button>
      )}
      <Button
        size="compact-xs"
        variant="light"
        onClick={() => onChange(Math.max(0, value - 2 * GB_IN_1K))}
        disabled={value === 0}
      >
        −2G
      </Button>
      <Button
        size="compact-xs"
        variant="light"
        onClick={() => onChange(value + 2 * GB_IN_1K)}
      >
        +2G
      </Button>
      <Button
        size="compact-xs"
        variant="light"
        onClick={() => onChange(Math.max(0, value - 10 * GB_IN_1K))}
        disabled={value === 0}
      >
        −10G
      </Button>
      <Button
        size="compact-xs"
        variant="light"
        onClick={() => onChange(value + 10 * GB_IN_1K)}
      >
        +10G
      </Button>
      <Button
        size="compact-xs"
        variant="light"
        onClick={() => onChange(value * 2)}
        disabled={value === 0}
      >
        2×
      </Button>
    </Group>
  ) : null

  return (
    <Stack gap={4}>
      <Group gap="xs" wrap="nowrap">
        <NumberInput
          size="xs"
          min={0}
          value={num}
          onChange={handleNumChange}
          style={{ width: 90 }}
        />
        <Select
          size="xs"
          data={units.map((label, idx) => ({ value: String(idx), label }))}
          value={String(unit)}
          onChange={(val) => val != null && handleUnitChange(parseInt(val, 10))}
          style={{ width: 70 }}
        />
      </Group>
      {presets}
    </Stack>
  )
}
