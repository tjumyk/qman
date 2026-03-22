import type { UserQuota } from '../api/schemas'

function pct(total: number, value: number): number {
  return total > 0 ? (value / total) * 100 : 0
}

export function hasDockerUsageBreakdown(q: UserQuota): boolean {
  return (
    typeof q.docker_container_bytes === 'number' &&
    typeof q.docker_image_layer_bytes === 'number' &&
    typeof q.docker_volume_bytes === 'number'
  )
}

/** True when the multi-segment Docker bar has at least one visible section. */
export function shouldRenderDockerQuotaBreakdownBar(q: UserQuota): boolean {
  if (!hasDockerUsageBreakdown(q)) return false
  const blockLimit = q.block_hard_limit > 0 ? q.block_hard_limit : q.block_soft_limit
  const blockLimitBytes = blockLimit * 1024
  const used = q.block_current
  const containerB = q.docker_container_bytes ?? 0
  const layerB = q.docker_image_layer_bytes ?? 0
  const volumeB = q.docker_volume_bytes ?? 0
  if (containerB + layerB + volumeB === 0 && used > 0) return false
  const maxBytes =
    blockLimitBytes > 0 ? Math.max(blockLimitBytes, used, 1) : Math.max(used, 1)
  const remaining = blockLimitBytes > 0 ? Math.max(0, blockLimitBytes - used) : 0
  return (
    pct(maxBytes, containerB) > 0 ||
    pct(maxBytes, layerB) > 0 ||
    pct(maxBytes, volumeB) > 0 ||
    (blockLimitBytes > 0 && pct(maxBytes, remaining) > 0)
  )
}
