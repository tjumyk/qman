import { useState } from 'react'
import { Group, NumberInput, Select } from '@mantine/core'

interface BlockLimitEditorProps {
  initValue: number
  onChange: (value: number) => void
}

const units = ['KB', 'MB', 'GB', 'TB']

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

export function BlockLimitEditor({ initValue, onChange }: BlockLimitEditorProps) {
  const [num, setNum] = useState(() => toValueAndUnit(initValue).value)
  const [unit, setUnit] = useState(() => toValueAndUnit(initValue).unitIndex)

  const notify = (n: number, u: number) => onChange(toBlocks(n, u))

  const handleNumChange = (val: string | number) => {
    const n = typeof val === 'string' ? parseFloat(val) || 0 : val
    setNum(n)
    notify(n, unit)
  }

  const handleUnitChange = (newUnitIndex: number) => {
    let v = num
    let u = unit
    if (u < newUnitIndex) {
      while (u < newUnitIndex) {
        v /= 1024
        u += 1
      }
      v = Math.round(v * 100) / 100
    } else if (u > newUnitIndex) {
      while (u > newUnitIndex) {
        v *= 1024
        u -= 1
      }
    }
    setNum(v)
    setUnit(newUnitIndex)
    notify(v, newUnitIndex)
  }

  return (
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
  )
}
