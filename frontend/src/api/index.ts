import axios, { isAxiosError } from 'axios'
import { z } from 'zod'
import {
  meMappingSchema,
  meSchema,
  quotasResponseSchema,
  userQuotaSchema,
  resolveUserResponseSchema,
  dockerContainersResponseSchema,
  dockerImagesResponseSchema,
  dockerVolumesResponseSchema,
  batchQuotaResultSchema,
  deviceDefaultQuotaSchema,
  notificationLogListResponseSchema,
  notificationDetailSchema,
  dockerUsageReviewQueueResponseSchema,
  dockerUsageReviewEventsResponseSchema,
  dockerUsageAttributeOkSchema,
} from './schemas'
import type {
  Me,
  MeMapping,
  QuotasResponse,
  ResolveUserResponse,
  SetUserQuotaBody,
  UserQuota,
  DockerContainersResponse,
  DockerImagesResponse,
  DockerVolumesResponse,
  BatchQuotaRequest,
  BatchQuotaResult,
  DeviceDefaultQuota,
  SetDeviceDefaultQuotaBody,
  NotificationLogListResponse,
  NotificationDetail,
  DockerUsageReviewQueueResponse,
  DockerUsageReviewEventsResponse,
  DockerUsageAttributeOk,
} from './schemas'

const meMappingsResponseSchema = meMappingSchema.array()

// Timeout configuration (in milliseconds) matching backend operation-specific timeouts
// Note: axios timeout is total timeout (connect + read), not separate like requests library
const TIMEOUT_PING = 5000 // 5s for health checks
const TIMEOUT_QUOTA = 180000 // 180s for quota fetching (Docker operations can take ~1 min)
const TIMEOUT_USER_RESOLVE = 10000 // 10s for user resolution
const TIMEOUT_SET_QUOTA = 120000 // 120s for setting quota (Docker quota setting can be slow)
const TIMEOUT_DEFAULT = 60000 // 60s default for other operations

const api = axios.create({
  baseURL: '/api',
  timeout: TIMEOUT_DEFAULT,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
})

// When backend returns 401 with redirect_url (OAuth required), send user to OAuth server
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const redirectUrl = error.response?.data?.redirect_url
    if (error.response?.status === 401 && typeof redirectUrl === 'string' && redirectUrl) {
      window.location.href = redirectUrl
      return Promise.reject(error) // keep rejecting so callers don't run with stale state
    }
    return Promise.reject(error)
  }
)

/** Prefer backend error msg from response.data.msg, else error.message, else fallback. */
export function getErrorMessage(err: unknown, fallback: string): string {
  if (isAxiosError(err) && err.response?.data && typeof err.response.data === 'object' && 'msg' in err.response.data && typeof (err.response.data as { msg?: unknown }).msg === 'string') {
    return (err.response.data as { msg: string }).msg
  }
  if (err instanceof Error && err.message) return err.message
  return fallback
}

export async function fetchMe(): Promise<Me> {
  const { data } = await api.get<unknown>('me')
  return meSchema.parse(data)
}

export async function fetchMeMappings(): Promise<MeMapping[]> {
  const { data } = await api.get<unknown>('me/mappings')
  return meMappingsResponseSchema.parse(data)
}

export type MeQuotasParams = { hostId?: string; hostUserName?: string }

export async function fetchMeQuotas(params?: MeQuotasParams): Promise<QuotasResponse> {
  const searchParams = new URLSearchParams()
  if (params?.hostId) searchParams.set('host_id', params.hostId)
  if (params?.hostUserName) searchParams.set('host_user_name', params.hostUserName)
  const qs = searchParams.toString()
  const url = qs ? `me/quotas?${qs}` : 'me/quotas'
  const { data } = await api.get<unknown>(url, { timeout: TIMEOUT_QUOTA })
  return quotasResponseSchema.parse(data)
}

export async function fetchHosts(): Promise<{ id: string }[]> {
  const { data } = await api.get<unknown>('hosts')
  return z.array(z.object({ id: z.string() })).parse(data)
}

export async function fetchHostUsers(hostId: string): Promise<{ host_user_name: string }[]> {
  const { data } = await api.get<unknown>(`hosts/${encodeURIComponent(hostId)}/users`)
  return z.array(z.object({ host_user_name: z.string() })).parse(data)
}

export async function postMeMapping(hostId: string, hostUserName: string): Promise<MeMapping> {
  const { data } = await api.post<unknown>('me/mappings', { host_id: hostId, host_user_name: hostUserName })
  return meMappingSchema.parse(data)
}

export async function deleteMeMapping(hostId: string, hostUserName: string): Promise<void> {
  await api.delete('me/mappings', {
    params: { host_id: hostId, host_user_name: hostUserName },
  })
}

export async function fetchQuotas(): Promise<QuotasResponse> {
  const { data } = await api.get<unknown>('quotas', { timeout: TIMEOUT_QUOTA })
  return quotasResponseSchema.parse(data)
}

// Admin mapping APIs
export const adminMappingSchema = z.object({
  oauth_user_id: z.number(),
  oauth_user_name: z.string().nullable().optional(),
  host_id: z.string(),
  host_user_name: z.string(),
})
export type AdminMapping = z.infer<typeof adminMappingSchema>

export const adminHostUserSchema = z.object({
  host_id: z.string(),
  host_user_name: z.string(),
})
export type AdminHostUser = z.infer<typeof adminHostUserSchema>

export const adminOAuthUserSchema = z.object({
  id: z.number(),
  name: z.string(),
})
export type AdminOAuthUser = z.infer<typeof adminOAuthUserSchema>

export async function fetchAdminMappings(): Promise<AdminMapping[]> {
  const { data } = await api.get<unknown>('admin/mappings')
  return z.array(adminMappingSchema).parse(data)
}

export async function fetchAdminHostUsers(): Promise<AdminHostUser[]> {
  const { data } = await api.get<unknown>('admin/host-users', { timeout: TIMEOUT_QUOTA })
  return z.array(adminHostUserSchema).parse(data)
}

export async function fetchAdminOAuthUsers(): Promise<AdminOAuthUser[]> {
  const { data } = await api.get<unknown>('admin/oauth-users')
  return z.array(adminOAuthUserSchema).parse(data)
}

export async function postAdminMapping(
  oauthUserId: number,
  hostId: string,
  hostUserName: string
): Promise<AdminMapping> {
  const { data } = await api.post<unknown>('admin/mappings', {
    oauth_user_id: oauthUserId,
    host_id: hostId,
    host_user_name: hostUserName,
  })
  return adminMappingSchema.parse(data)
}

export async function deleteAdminMapping(
  oauthUserId: number,
  hostId: string,
  hostUserName: string
): Promise<void> {
  await api.delete('admin/mappings', {
    params: { oauth_user_id: oauthUserId, host_id: hostId, host_user_name: hostUserName },
  })
}

export type BatchMappingInput = {
  oauth_user_id: number
  host_id: string
  host_user_name: string
}

export type BatchMappingResult = {
  added: BatchMappingInput[]
  skipped: BatchMappingInput[]
}

export async function postAdminMappingsBatch(
  mappings: BatchMappingInput[]
): Promise<BatchMappingResult> {
  const { data } = await api.post<unknown>('admin/mappings/batch', { mappings })
  return z.object({
    added: z.array(z.object({
      oauth_user_id: z.number(),
      host_id: z.string(),
      host_user_name: z.string(),
    })),
    skipped: z.array(z.object({
      oauth_user_id: z.number(),
      host_id: z.string(),
      host_user_name: z.string(),
    })),
  }).parse(data)
}

export async function setUserQuota(
  host: string,
  uid: number,
  device: string,
  body: SetUserQuotaBody
): Promise<UserQuota> {
  const { data } = await api.put<unknown>(
    `quotas/${encodeURIComponent(host)}/users/${uid}?device=${encodeURIComponent(device)}`,
    body,
    { timeout: TIMEOUT_SET_QUOTA }
  )
  return userQuotaSchema.parse(data)
}

export async function resolveHostUser(hostId: string, username: string): Promise<ResolveUserResponse> {
  const { data } = await api.get<unknown>(
    `quotas/${encodeURIComponent(hostId)}/users/resolve`,
    { params: { username: username.trim() }, timeout: TIMEOUT_USER_RESOLVE }
  )
  return resolveUserResponseSchema.parse(data)
}

export async function setBatchQuota(
  hostId: string,
  body: BatchQuotaRequest
): Promise<BatchQuotaResult> {
  const { data } = await api.post<unknown>(
    `quotas/${encodeURIComponent(hostId)}/batch`,
    body,
    { timeout: TIMEOUT_SET_QUOTA }
  )
  return batchQuotaResultSchema.parse(data)
}

export async function getDeviceDefaultQuota(
  hostId: string,
  device: string
): Promise<DeviceDefaultQuota | null> {
  const { data } = await api.get<unknown>(
    `quotas/${encodeURIComponent(hostId)}/default-quota`,
    { params: { device }, timeout: TIMEOUT_QUOTA }
  )
  if (data == null) return null
  return deviceDefaultQuotaSchema.parse(data)
}

export async function setDeviceDefaultQuota(
  hostId: string,
  device: string,
  body: SetDeviceDefaultQuotaBody
): Promise<DeviceDefaultQuota> {
  const { data } = await api.put<unknown>(
    `quotas/${encodeURIComponent(hostId)}/default-quota`,
    body,
    { params: { device }, timeout: TIMEOUT_SET_QUOTA }
  )
  return deviceDefaultQuotaSchema.parse(data)
}

export type HostPingStatus = {
  status: 'ok' | 'error'
  latency_ms?: number
  error?: string
}

export type HostPingResponse = Record<string, HostPingStatus>

export async function pingHosts(): Promise<HostPingResponse> {
  const { data } = await api.get<unknown>('hosts/ping', { timeout: TIMEOUT_PING })
  return z.record(
    z.string(),
    z.object({
      status: z.enum(['ok', 'error']),
      latency_ms: z.number().optional(),
      error: z.string().optional(),
    })
  ).parse(data)
}

// Docker detail APIs
export async function fetchDockerContainers(hostId: string): Promise<DockerContainersResponse> {
  const { data } = await api.get<unknown>(
    `quotas/${encodeURIComponent(hostId)}/docker/containers`,
    { timeout: TIMEOUT_QUOTA }
  )
  return dockerContainersResponseSchema.parse(data)
}

export async function fetchDockerImages(hostId: string): Promise<DockerImagesResponse> {
  const { data } = await api.get<unknown>(
    `quotas/${encodeURIComponent(hostId)}/docker/images`,
    { timeout: TIMEOUT_QUOTA }
  )
  return dockerImagesResponseSchema.parse(data)
}

export async function fetchDockerVolumes(hostId: string): Promise<DockerVolumesResponse> {
  const { data } = await api.get<unknown>(
    `quotas/${encodeURIComponent(hostId)}/docker/volumes`,
    { timeout: TIMEOUT_QUOTA }
  )
  return dockerVolumesResponseSchema.parse(data)
}

export async function fetchAdminNotifications(
  params: {
    page?: number
    pageSize?: number
    hostId?: string
    deviceName?: string
    oauthUserId?: number
    email?: string
    eventType?: string
    sendStatus?: string
    batchId?: string
  } = {}
): Promise<NotificationLogListResponse> {
  const search = new URLSearchParams()
  if (params.page && params.page > 1) search.set('page', String(params.page))
  if (params.pageSize) search.set('page_size', String(params.pageSize))
  if (params.hostId) search.set('host_id', params.hostId)
  if (params.deviceName) search.set('device_name', params.deviceName)
  if (typeof params.oauthUserId === 'number') search.set('oauth_user_id', String(params.oauthUserId))
  if (params.email) search.set('email', params.email)
  if (params.eventType) search.set('event_type', params.eventType)
  if (params.sendStatus) search.set('send_status', params.sendStatus)
  if (params.batchId) search.set('batch_id', params.batchId)
  const qs = search.toString()
  const url = qs ? `admin/notifications?${qs}` : 'admin/notifications'
  const { data } = await api.get<unknown>(url)
  return notificationLogListResponseSchema.parse(data)
}

export async function fetchAdminNotificationDetail(id: number): Promise<NotificationDetail> {
  const { data } = await api.get<unknown>(`admin/notifications/${id}`)
  return notificationDetailSchema.parse(data)
}

export type DockerUsageEntityType = 'container' | 'image' | 'volume'

export async function fetchAdminDockerUsageReviewQueue(
  hostId: string,
  params: { entityType: DockerUsageEntityType; page?: number; pageSize?: number }
): Promise<DockerUsageReviewQueueResponse> {
  const search = new URLSearchParams({ host_id: hostId, entity_type: params.entityType })
  if (params.page && params.page > 1) search.set('page', String(params.page))
  if (params.pageSize) search.set('page_size', String(params.pageSize))
  const { data } = await api.get<unknown>(`admin/docker/usage/review-queue?${search}`, {
    timeout: TIMEOUT_DEFAULT,
  })
  return dockerUsageReviewQueueResponseSchema.parse(data)
}

export async function fetchAdminDockerUsageEvents(
  hostId: string,
  params: {
    entityType: DockerUsageEntityType
    entityId: string
    includeUsed?: boolean
    volumeName?: string
  }
): Promise<DockerUsageReviewEventsResponse> {
  const search = new URLSearchParams({ host_id: hostId, entity_type: params.entityType })
  if (params.entityType === 'volume') {
    search.set('volume_name', params.volumeName ?? params.entityId)
  } else {
    search.set('entity_id', params.entityId)
  }
  if (params.includeUsed) search.set('include_used', 'true')
  const { data } = await api.get<unknown>(`admin/docker/usage/events?${search}`, {
    timeout: TIMEOUT_DEFAULT,
  })
  return dockerUsageReviewEventsResponseSchema.parse(data)
}

export type PostAdminDockerUsageAttributeBody = {
  entity_type: DockerUsageEntityType
  oauth_user_id: number
  host_user_name: string
  cascade?: boolean
  container_id?: string
  image_id?: string
  volume_name?: string
}

export async function postAdminDockerUsageAttribute(
  hostId: string,
  body: PostAdminDockerUsageAttributeBody
): Promise<DockerUsageAttributeOk> {
  const { data } = await api.post<unknown>(
    `admin/docker/usage/attribute?host_id=${encodeURIComponent(hostId)}`,
    body,
    { timeout: TIMEOUT_DEFAULT }
  )
  return dockerUsageAttributeOkSchema.parse(data)
}

export async function deleteAdminDockerUsageAttribute(
  hostId: string,
  params: {
    entityType: DockerUsageEntityType
    entityId: string
    cascade?: boolean
    volumeName?: string
  }
): Promise<DockerUsageAttributeOk> {
  const search = new URLSearchParams({
    host_id: hostId,
    entity_type: params.entityType,
  })
  if (params.entityType === 'volume') {
    search.set('volume_name', params.volumeName ?? params.entityId)
  } else {
    search.set('entity_id', params.entityId)
  }
  if (params.cascade) search.set('cascade', 'true')
  const { data } = await api.delete<unknown>(`admin/docker/usage/attribute?${search}`, {
    timeout: TIMEOUT_DEFAULT,
  })
  return dockerUsageAttributeOkSchema.parse(data)
}
