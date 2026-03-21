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

export const batchQuotaRequestSchema = z.object({
  device: z.string(),
  block_hard_limit: z.number().optional(),
  block_soft_limit: z.number().optional(),
  inode_hard_limit: z.number().optional(),
  inode_soft_limit: z.number().optional(),
  preserve_if_nonzero: z.boolean().optional(),
  preserve_if_usage_exceeds: z.boolean().optional(),
})
export type BatchQuotaRequest = z.infer<typeof batchQuotaRequestSchema>

export const batchQuotaResultSchema = z.object({
  total_users: z.number(),
  updated_users: z.number(),
  skipped_users: z.number(),
  errors: z.array(z.string()),
})
export type BatchQuotaResult = z.infer<typeof batchQuotaResultSchema>

export const deviceDefaultQuotaSchema = z.object({
  device_name: z.string(),
  block_soft_limit: z.number(),
  block_hard_limit: z.number(),
  inode_soft_limit: z.number(),
  inode_hard_limit: z.number(),
})
export type DeviceDefaultQuota = z.infer<typeof deviceDefaultQuotaSchema>

export const setDeviceDefaultQuotaBodySchema = z.object({
  block_soft_limit: z.number().optional(),
  block_hard_limit: z.number().optional(),
  inode_soft_limit: z.number().optional(),
  inode_hard_limit: z.number().optional(),
})
export type SetDeviceDefaultQuotaBody = z.infer<typeof setDeviceDefaultQuotaBodySchema>

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
  puller_host_user_name: z.string().nullable().optional(),
  puller_uid: z.number().nullable().optional(),
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
  total_layer_bytes: z.number(),
  attributed_layer_bytes: z.number(),
  unattributed_layer_bytes: z.number(),
  layers_by_user: z.record(z.string(), z.number()),
})
export type DockerImagesResponse = z.infer<typeof dockerImagesResponseSchema>

// Docker volume detail
export const dockerVolumeSchema = z.object({
  volume_name: z.string(),
  size_bytes: z.number(),
  reported_size_bytes: z.number().optional(),
  actual_disk_bytes: z.number().nullable().optional(),
  host_user_name: z.string().nullable(),
  uid: z.number().nullable(),
  attribution_source: z.string().nullable(),
  ref_count: z.number(),
  first_seen_at: z.string().nullable(),
  last_mounted_at: z.string().nullable().optional(),
  scan_started_at: z.string().nullable().optional(),
  scan_finished_at: z.string().nullable().optional(),
  pending_scan_started_at: z.string().nullable().optional(),
  last_scan_started_at: z.string().nullable().optional(),
  last_scan_finished_at: z.string().nullable().optional(),
  last_scan_status: z.string().nullable().optional(),
})
export type DockerVolume = z.infer<typeof dockerVolumeSchema>

export const dockerVolumesResponseSchema = z.object({
  volumes: z.array(dockerVolumeSchema),
  total_bytes: z.number(),
  attributed_bytes: z.number(),
  unattributed_bytes: z.number(),
})
export type DockerVolumesResponse = z.infer<typeof dockerVolumesResponseSchema>

// Notification center
export const notificationLogEntrySchema = z.object({
  id: z.number(),
  created_at: z.string().nullable(),
  oauth_user_id: z.number().nullable(),
  email: z.string().nullable(),
  host_id: z.string().nullable(),
  host_user_name: z.string().nullable(),
  device_name: z.string().nullable(),
  quota_type: z.string(),
  event_type: z.string(),
  subject: z.string().nullable(),
  send_status: z.string(),
  error_message: z.string().nullable(),
  batch_id: z.string().nullable(),
  // Detailed view may include associated events; keep shape loose here and model
  // the richer structure separately in the page component when needed.
})
export type NotificationLogEntry = z.infer<typeof notificationLogEntrySchema>

export const notificationEventSchema = z.object({
  id: z.number(),
  created_at: z.string().nullable(),
  oauth_user_id: z.number().nullable(),
  email: z.string().nullable(),
  host_id: z.string().nullable(),
  host_user_name: z.string().nullable(),
  device_name: z.string().nullable(),
  quota_type: z.string(),
  event_type: z.string(),
  payload: z.string().nullable(),
  state_key: z.string().nullable(),
})
export type NotificationEvent = z.infer<typeof notificationEventSchema>

export const notificationDetailSchema = z.object({
  id: z.number(),
  created_at: z.string().nullable(),
  updated_at: z.string().nullable(),
  oauth_user_id: z.number().nullable(),
  email: z.string().nullable(),
  host_id: z.string().nullable(),
  host_user_name: z.string().nullable(),
  device_name: z.string().nullable(),
  quota_type: z.string(),
  event_type: z.string(),
  subject: z.string().nullable(),
  body_preview: z.string().nullable(),
  body_html: z.string().nullable(),
  send_status: z.string(),
  error_message: z.string().nullable(),
  dedupe_key: z.string().nullable(),
  last_state: z.string().nullable(),
  batch_id: z.string().nullable(),
  events: z.array(notificationEventSchema),
})
export type NotificationDetail = z.infer<typeof notificationDetailSchema>

export const notificationLogListResponseSchema = z.object({
  items: z.array(notificationLogEntrySchema),
  total: z.number(),
  page: z.number(),
  page_size: z.number(),
})
export type NotificationLogListResponse = z.infer<typeof notificationLogListResponseSchema>

// Admin Docker usage review (master proxies to slave)
export const dockerUsageReviewQueueItemSchema = z.discriminatedUnion('entity_type', [
  z.object({
    entity_type: z.literal('container'),
    container_id: z.string(),
    host_user_name: z.string().nullable().optional(),
    uid: z.number().nullable().optional(),
    created_at: z.string().nullable().optional(),
    unresolved_events: z.number(),
  }),
  z.object({
    entity_type: z.literal('image'),
    image_id: z.string(),
    puller_host_user_name: z.string().nullable().optional(),
    puller_uid: z.number().nullable().optional(),
    created_at: z.string().nullable().optional(),
    unresolved_events: z.number(),
  }),
  z.object({
    entity_type: z.literal('volume'),
    volume_name: z.string(),
    host_user_name: z.string().nullable().optional(),
    uid: z.number().nullable().optional(),
    first_seen_at: z.string().nullable().optional(),
    unresolved_events: z.number(),
  }),
])
export type DockerUsageReviewQueueItem = z.infer<typeof dockerUsageReviewQueueItemSchema>

export const dockerUsageReviewQueueResponseSchema = z.object({
  items: z.array(dockerUsageReviewQueueItemSchema),
  total: z.number(),
  page: z.number(),
  page_size: z.number(),
})
export type DockerUsageReviewQueueResponse = z.infer<typeof dockerUsageReviewQueueResponseSchema>

export const dockerUsageReviewEventSchema = z
  .object({
    id: z.number(),
    source: z.enum(['audit', 'docker']),
    event_ts: z.string().nullable().optional(),
    created_at: z.string().nullable().optional(),
    used_for_auto_attribution: z.boolean(),
    manual_resolved_at: z.string().nullable().optional(),
    manual_resolved_by_oauth_user_id: z.number().nullable().optional(),
    payload: z.string(),
  })
  .passthrough()
export type DockerUsageReviewEvent = z.infer<typeof dockerUsageReviewEventSchema>

export const dockerUsageReviewEventsResponseSchema = z.object({
  events: z.array(dockerUsageReviewEventSchema),
})
export type DockerUsageReviewEventsResponse = z.infer<typeof dockerUsageReviewEventsResponseSchema>

export const dockerUsageAttributeOkSchema = z.object({
  status: z.literal('ok'),
})
export type DockerUsageAttributeOk = z.infer<typeof dockerUsageAttributeOkSchema>

export const dockerInspectResponseSchema = z.object({
  inspect: z.record(z.string(), z.unknown()),
})
export type DockerInspectResponse = z.infer<typeof dockerInspectResponseSchema>

export const dockerAttributionDetailSchema = z.object({
  auto: z.record(z.string(), z.unknown()).nullable(),
  override: z.record(z.string(), z.unknown()).nullable(),
})
export type DockerAttributionDetail = z.infer<typeof dockerAttributionDetailSchema>
