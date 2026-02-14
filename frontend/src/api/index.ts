import axios from 'axios'
import { meSchema, quotasResponseSchema, userQuotaSchema } from './schemas'
import type { Me, QuotasResponse, SetUserQuotaBody, UserQuota } from './schemas'

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

export async function fetchMeQuotas(): Promise<QuotasResponse> {
  const { data } = await api.get<unknown>('me/quotas')
  return quotasResponseSchema.parse(data)
}

export async function fetchQuotas(): Promise<QuotasResponse> {
  const { data } = await api.get<unknown>('quotas')
  return quotasResponseSchema.parse(data)
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
