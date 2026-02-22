import { z } from 'zod'

export const basicErrorSchema = z.object({
  msg: z.string(),
  detail: z.string().optional(),
})
export type BasicError = z.infer<typeof basicErrorSchema>

export const diskUsageSchema = z.object({
  free: z.number(),
  used: z.number(),
  total: z.number(),
  percent: z.number(),
})
export type DiskUsage = z.infer<typeof diskUsageSchema>

export const quotaInfoSchema = z.object({
  block_grace: z.number(),
  inode_grace: z.number(),
  flags: z.number(),
})
export type QuotaInfo = z.infer<typeof quotaInfoSchema>

export const quotaSchema = z.object({
  block_hard_limit: z.number(),
  block_soft_limit: z.number(),
  block_current: z.number(),
  inode_hard_limit: z.number(),
  inode_soft_limit: z.number(),
  inode_current: z.number(),
  block_time_limit: z.number(),
  inode_time_limit: z.number(),
})
export type Quota = z.infer<typeof quotaSchema>

export const userQuotaSchema = quotaSchema.extend({
  name: z.string(),
  uid: z.number(),
})
export type UserQuota = z.infer<typeof userQuotaSchema>

export const groupQuotaSchema = quotaSchema.extend({
  name: z.string(),
  gid: z.number(),
})
export type GroupQuota = z.infer<typeof groupQuotaSchema>

export const deviceQuotaSchema = z.object({
  fstype: z.string(),
  mount_points: z.array(z.string()),
  name: z.string(),
  opts: z.array(z.string()),
  usage: diskUsageSchema,
  user_quota_format: z.string().optional(),
  user_quota_info: quotaInfoSchema.optional(),
  user_quotas: z.array(userQuotaSchema).optional(),
  group_quota_format: z.string().optional(),
  group_quota_info: quotaInfoSchema.optional(),
  group_quotas: z.array(groupQuotaSchema).optional(),
  /** Docker: bytes not attributed to any user (containers without qman.user). */
  unattributed_usage: z.number().optional(),
})
export type DeviceQuota = z.infer<typeof deviceQuotaSchema>

export const hostQuotaSchema = z.object({
  results: z.array(deviceQuotaSchema).optional(),
  error: basicErrorSchema.optional(),
})
export type HostQuota = z.infer<typeof hostQuotaSchema>

export const quotasResponseSchema = z.record(z.string(), hostQuotaSchema)
export type QuotasResponse = z.infer<typeof quotasResponseSchema>

export const setUserQuotaBodySchema = z.object({
  block_hard_limit: z.number().optional(),
  block_soft_limit: z.number().optional(),
  inode_hard_limit: z.number().optional(),
  inode_soft_limit: z.number().optional(),
})
export type SetUserQuotaBody = z.infer<typeof setUserQuotaBodySchema>

export const resolveUserResponseSchema = z.object({
  uid: z.number(),
  name: z.string(),
})
export type ResolveUserResponse = z.infer<typeof resolveUserResponseSchema>

export const meSchema = z.object({
  uid: z.number(),
  name: z.string(),
  is_admin: z.boolean(),
})
export type Me = z.infer<typeof meSchema>

export const meMappingSchema = z.object({
  host_id: z.string(),
  host_user_name: z.string(),
})
export type MeMapping = z.infer<typeof meMappingSchema>

// Docker container detail
export const dockerContainerSchema = z.object({
  container_id: z.string(),
  name: z.string(),
  image: z.string(),
  status: z.string(),
  host_user_name: z.string().nullable(),
  uid: z.number().nullable(),
  size_bytes: z.number(),
  created_at: z.string().nullable(),
})
export type DockerContainer = z.infer<typeof dockerContainerSchema>

export const dockerContainersResponseSchema = z.object({
  containers: z.array(dockerContainerSchema),
  total_bytes: z.number(),
  attributed_bytes: z.number(),
  unattributed_bytes: z.number(),
})
export type DockerContainersResponse = z.infer<typeof dockerContainersResponseSchema>

// Docker image detail
export const dockerImageSchema = z.object({
  image_id: z.string(),
  tags: z.array(z.string()),
  size_bytes: z.number(),
  created: z.string().nullable(),
})
export type DockerImage = z.infer<typeof dockerImageSchema>

// Docker layer detail
export const dockerLayerSchema = z.object({
  layer_id: z.string(),
  size_bytes: z.number(),
  first_puller_host_user_name: z.string().nullable(),
  first_puller_uid: z.number().nullable(),
  creation_method: z.string().nullable(),
  first_seen_at: z.string().nullable(),
})
export type DockerLayer = z.infer<typeof dockerLayerSchema>

export const dockerImagesResponseSchema = z.object({
  images: z.array(dockerImageSchema),
  layers: z.array(dockerLayerSchema),
  total_image_bytes: z.number(),
  attributed_layer_bytes: z.number(),
  unattributed_layer_bytes: z.number(),
  layers_by_user: z.record(z.string(), z.number()),
})
export type DockerImagesResponse = z.infer<typeof dockerImagesResponseSchema>

// Docker volume detail
export const dockerVolumeSchema = z.object({
  volume_name: z.string(),
  size_bytes: z.number(),
  host_user_name: z.string().nullable(),
  uid: z.number().nullable(),
  attribution_source: z.string().nullable(),
  ref_count: z.number(),
  first_seen_at: z.string().nullable(),
})
export type DockerVolume = z.infer<typeof dockerVolumeSchema>

export const dockerVolumesResponseSchema = z.object({
  volumes: z.array(dockerVolumeSchema),
  total_bytes: z.number(),
  attributed_bytes: z.number(),
  unattributed_bytes: z.number(),
})
export type DockerVolumesResponse = z.infer<typeof dockerVolumesResponseSchema>
