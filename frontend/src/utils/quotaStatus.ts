import type { UserQuota } from '../api/schemas'

export type QuotaStatus = 'ok' | 'warning' | 'over'

/** Block limits are in 1K blocks; block_current is in bytes (pyquota convention). */
export function getQuotaStatus(quota: UserQuota): QuotaStatus {
  const overSoft =
    (quota.block_soft_limit > 0 && quota.block_current >= quota.block_soft_limit * 1024) ||
    (quota.inode_soft_limit > 0 && quota.inode_current >= quota.inode_soft_limit)
  const overHard =
    (quota.block_hard_limit > 0 && quota.block_current >= quota.block_hard_limit * 1024) ||
    (quota.inode_hard_limit > 0 && quota.inode_current >= quota.inode_hard_limit)
  if (overHard) return 'over'
  if (overSoft) return 'warning'
  return 'ok'
}

export function getQuotaStatusColor(status: QuotaStatus): string {
  switch (status) {
    case 'over':
      return 'red'
    case 'warning':
      return 'yellow'
    default:
      return 'green'
  }
}

/** Returns i18n key for the status label (use with t()). */
export function getQuotaStatusLabelKey(status: QuotaStatus): string {
  switch (status) {
    case 'over':
      return 'statusOverHardLimit'
    case 'warning':
      return 'statusOverSoftLimit'
    default:
      return 'statusOk'
  }
}
