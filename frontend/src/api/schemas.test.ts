import { describe, it, expect } from 'vitest'
import {
  basicErrorSchema,
  diskUsageSchema,
  hostQuotaSchema,
  quotasResponseSchema,
  userQuotaSchema,
} from './schemas'

describe('schemas', () => {
  it('parses BasicError', () => {
    expect(basicErrorSchema.parse({ msg: 'error' })).toEqual({ msg: 'error' })
    expect(basicErrorSchema.parse({ msg: 'x', detail: 'y' })).toEqual({ msg: 'x', detail: 'y' })
  })

  it('rejects invalid BasicError', () => {
    expect(() => basicErrorSchema.parse({})).toThrow()
    expect(() => basicErrorSchema.parse({ detail: 'only' })).toThrow()
  })

  it('parses DiskUsage', () => {
    const u = { free: 0, used: 1, total: 1, percent: 100 }
    expect(diskUsageSchema.parse(u)).toEqual(u)
  })

  it('parses UserQuota', () => {
    const q = {
      block_hard_limit: 0,
      block_soft_limit: 0,
      block_current: 0,
      inode_hard_limit: 0,
      inode_soft_limit: 0,
      inode_current: 0,
      block_time_limit: 0,
      inode_time_limit: 0,
      uid: 1000,
      name: 'user',
    }
    expect(userQuotaSchema.parse(q)).toEqual(q)
  })

  it('parses HostQuota with error', () => {
    expect(hostQuotaSchema.parse({ error: { msg: 'fail' } })).toEqual({
      error: { msg: 'fail' },
    })
  })

  it('parses QuotasResponse', () => {
    const r = { host1: { results: [] }, host2: { error: { msg: 'x' } } }
    expect(quotasResponseSchema.parse(r)).toEqual(r)
  })
})
