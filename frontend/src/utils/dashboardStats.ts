import type { QuotasResponse } from '../api/schemas'
import { getQuotaStatus } from './quotaStatus'

export interface DashboardStats {
  hostCount: number
  deviceCount: number
  usersOverSoft: number
  usersOverHard: number
}

export interface NeedsAttentionItem {
  hostId: string
  deviceName: string
  uid: number
  name: string
  status: 'warning' | 'over'
}

export function computeDashboardStats(data: QuotasResponse): DashboardStats {
  let hostCount = 0
  let deviceCount = 0
  let usersOverSoft = 0
  let usersOverHard = 0
  for (const payload of Object.values(data)) {
    if (payload.error) continue
    hostCount += 1
    const devices = payload.results || []
    for (const dev of devices) {
      deviceCount += 1
      const users = dev.user_quotas || []
      for (const q of users) {
        const status = getQuotaStatus(q)
        if (status === 'warning') usersOverSoft += 1
        else if (status === 'over') usersOverHard += 1
      }
    }
  }
  return { hostCount, deviceCount, usersOverSoft, usersOverHard }
}

export function computeNeedsAttention(data: QuotasResponse, limit = 20): NeedsAttentionItem[] {
  const items: NeedsAttentionItem[] = []
  for (const [hostId, payload] of Object.entries(data)) {
    if (payload.error) continue
    const devices = payload.results || []
    for (const dev of devices) {
      const users = dev.user_quotas || []
      for (const q of users) {
        const status = getQuotaStatus(q)
        if (status === 'warning' || status === 'over') {
          items.push({
            hostId,
            deviceName: dev.name,
            uid: q.uid,
            name: q.name,
            status,
          })
          if (items.length >= limit) return items
        }
      }
    }
  }
  return items
}
