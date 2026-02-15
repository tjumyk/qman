import axios from 'axios'
import { z } from 'zod'
import { meMappingSchema, meSchema, quotasResponseSchema, userQuotaSchema } from './schemas'
import type { Me, MeMapping, QuotasResponse, SetUserQuotaBody, UserQuota } from './schemas'

const meMappingsResponseSchema = meMappingSchema.array()

const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
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
  const { data } = await api.get<unknown>(url)
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
  const { data } = await api.get<unknown>('quotas')
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
  const { data } = await api.get<unknown>('admin/host-users')
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

export async function setUserQuota(
  host: string,
  uid: number,
  device: string,
  body: SetUserQuotaBody
): Promise<UserQuota> {
  const { data } = await api.put<unknown>(
    `quotas/${encodeURIComponent(host)}/users/${uid}?device=${encodeURIComponent(device)}`,
    body
  )
  return userQuotaSchema.parse(data)
}
