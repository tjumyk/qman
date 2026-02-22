import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Stack,
  Text,
  Table,
  Loader,
  Alert,
  TextInput,
  Badge,
  Group,
  Accordion,
} from '@mantine/core'
import { fetchDockerImages } from '../../api'
import { BlockSize } from '../BlockSize'
import { useI18n } from '../../i18n'
import { UsageSummaryCards } from './UsageSummaryCard'
import type { DockerImage, DockerLayer } from '../../api/schemas'

interface ImagesTabProps {
  hostId: string
}

type ImageSortField = 'tags' | 'size_bytes' | 'created'
type LayerSortField = 'first_puller_host_user_name' | 'size_bytes' | 'creation_method' | 'first_seen_at'
type SortDirection = 'asc' | 'desc'

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  try {
    return new Date(dateStr).toLocaleDateString()
  } catch {
    return dateStr
  }
}

function getCreationMethodColor(method: string | null): string {
  switch (method?.toLowerCase()) {
    case 'pull':
      return 'blue'
    case 'build':
      return 'green'
    case 'commit':
      return 'orange'
    case 'import':
    case 'load':
      return 'grape'
    default:
      return 'gray'
  }
}

export function ImagesTab({ hostId }: ImagesTabProps) {
  const { t } = useI18n()
  const [imageSearch, setImageSearch] = useState('')
  const [layerSearch, setLayerSearch] = useState('')
  const [imageSortField, setImageSortField] = useState<ImageSortField>('size_bytes')
  const [imageSortDirection, setImageSortDirection] = useState<SortDirection>('desc')
  const [layerSortField, setLayerSortField] = useState<LayerSortField>('size_bytes')
  const [layerSortDirection, setLayerSortDirection] = useState<SortDirection>('desc')

  const { data, isLoading, error } = useQuery({
    queryKey: ['docker-images', hostId],
    queryFn: () => fetchDockerImages(hostId),
  })

  const handleImageSort = (field: ImageSortField) => {
    if (imageSortField === field) {
      setImageSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setImageSortField(field)
      setImageSortDirection('asc')
    }
  }

  const handleLayerSort = (field: LayerSortField) => {
    if (layerSortField === field) {
      setLayerSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setLayerSortField(field)
      setLayerSortDirection('asc')
    }
  }

  const filteredImages = useMemo(() => {
    if (!data) return []
    let list = data.images
    if (imageSearch.trim()) {
      const s = imageSearch.trim().toLowerCase()
      list = list.filter(
        (img) =>
          img.tags.some((tag) => tag.toLowerCase().includes(s)) ||
          img.image_id.toLowerCase().includes(s)
      )
    }
    return [...list].sort((a, b) => {
      const dir = imageSortDirection === 'asc' ? 1 : -1
      switch (imageSortField) {
        case 'tags':
          return (a.tags[0] || '').localeCompare(b.tags[0] || '') * dir
        case 'size_bytes':
          return (a.size_bytes - b.size_bytes) * dir
        case 'created':
          return ((a.created || '').localeCompare(b.created || '')) * dir
        default:
          return 0
      }
    })
  }, [data, imageSearch, imageSortField, imageSortDirection])

  const filteredLayers = useMemo(() => {
    if (!data) return []
    let list = data.layers
    if (layerSearch.trim()) {
      const s = layerSearch.trim().toLowerCase()
      list = list.filter(
        (layer) =>
          layer.layer_id.toLowerCase().includes(s) ||
          (layer.first_puller_host_user_name?.toLowerCase() || '').includes(s) ||
          (layer.creation_method?.toLowerCase() || '').includes(s)
      )
    }
    return [...list].sort((a, b) => {
      const dir = layerSortDirection === 'asc' ? 1 : -1
      switch (layerSortField) {
        case 'first_puller_host_user_name':
          return ((a.first_puller_host_user_name || '') as string).localeCompare(
            b.first_puller_host_user_name || ''
          ) * dir
        case 'size_bytes':
          return (a.size_bytes - b.size_bytes) * dir
        case 'creation_method':
          return ((a.creation_method || '') as string).localeCompare(b.creation_method || '') * dir
        case 'first_seen_at':
          return ((a.first_seen_at || '') as string).localeCompare(b.first_seen_at || '') * dir
        default:
          return 0
      }
    })
  }, [data, layerSearch, layerSortField, layerSortDirection])

  const ImageSortableHeader = ({
    field,
    children,
  }: {
    field: ImageSortField
    children: React.ReactNode
  }) => (
    <Table.Th style={{ cursor: 'pointer', userSelect: 'none' }} onClick={() => handleImageSort(field)}>
      <Group gap={4}>
        {children}
        {imageSortField === field && (
          <Text size="xs" c="dimmed">
            {imageSortDirection === 'asc' ? '▲' : '▼'}
          </Text>
        )}
      </Group>
    </Table.Th>
  )

  const LayerSortableHeader = ({
    field,
    children,
  }: {
    field: LayerSortField
    children: React.ReactNode
  }) => (
    <Table.Th style={{ cursor: 'pointer', userSelect: 'none' }} onClick={() => handleLayerSort(field)}>
      <Group gap={4}>
        {children}
        {layerSortField === field && (
          <Text size="xs" c="dimmed">
            {layerSortDirection === 'asc' ? '▲' : '▼'}
          </Text>
        )}
      </Group>
    </Table.Th>
  )

  if (isLoading) {
    return (
      <Stack align="center" gap="md" py="xl">
        <Loader size="lg" />
        <Text c="dimmed">{t('loading')}</Text>
      </Stack>
    )
  }

  if (error || !data) {
    return (
      <Alert color="red" title={t('error')}>
        {error instanceof Error ? error.message : t('failedToLoadDockerImages')}
      </Alert>
    )
  }

  return (
    <Stack gap="md">
      <UsageSummaryCards
        totalBytes={data.total_image_bytes}
        attributedBytes={data.attributed_layer_bytes}
        unattributedBytes={data.unattributed_layer_bytes}
      />

      <Accordion defaultValue={['images', 'layers']} multiple>
        <Accordion.Item value="images">
          <Accordion.Control>
            <Group gap="sm">
              <Text fw={500}>{t('imagesSection')}</Text>
              <Badge size="sm" variant="light">
                {data.images.length}
              </Badge>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <Stack gap="md">
              <TextInput
                placeholder={t('searchImages')}
                value={imageSearch}
                onChange={(e) => setImageSearch(e.currentTarget.value)}
                style={{ maxWidth: 300 }}
              />

              <Table striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{t('imageId')}</Table.Th>
                    <ImageSortableHeader field="tags">{t('imageTags')}</ImageSortableHeader>
                    <ImageSortableHeader field="size_bytes">{t('size')}</ImageSortableHeader>
                    <ImageSortableHeader field="created">{t('created')}</ImageSortableHeader>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {filteredImages.map((img: DockerImage) => (
                    <Table.Tr key={img.image_id}>
                      <Table.Td>
                        <Text size="xs" ff="monospace" c="dimmed">
                          {img.image_id.replace('sha256:', '').slice(0, 12)}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        {img.tags.length > 0 ? (
                          <Stack gap={2}>
                            {img.tags.slice(0, 3).map((tag) => (
                              <Text key={tag} size="sm" style={{ maxWidth: 250 }} truncate>
                                {tag}
                              </Text>
                            ))}
                            {img.tags.length > 3 && (
                              <Text size="xs" c="dimmed">
                                +{img.tags.length - 3} {t('more')}
                              </Text>
                            )}
                          </Stack>
                        ) : (
                          <Text size="sm" c="dimmed" fs="italic">
                            {t('noTags')}
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td>
                        <BlockSize size={img.size_bytes} />
                      </Table.Td>
                      <Table.Td>{formatDate(img.created)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>

              {filteredImages.length === 0 && (
                <Text size="sm" c="dimmed">
                  {t('noImagesMatch')}
                </Text>
              )}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="layers">
          <Accordion.Control>
            <Group gap="sm">
              <Text fw={500}>{t('layersSection')}</Text>
              <Badge size="sm" variant="light">
                {data.layers.length}
              </Badge>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <Stack gap="md">
              <TextInput
                placeholder={t('searchLayers')}
                value={layerSearch}
                onChange={(e) => setLayerSearch(e.currentTarget.value)}
                style={{ maxWidth: 300 }}
              />

              <Table striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{t('layerId')}</Table.Th>
                    <LayerSortableHeader field="first_puller_host_user_name">
                      {t('firstPuller')}
                    </LayerSortableHeader>
                    <LayerSortableHeader field="size_bytes">{t('size')}</LayerSortableHeader>
                    <LayerSortableHeader field="creation_method">
                      {t('creationMethod')}
                    </LayerSortableHeader>
                    <LayerSortableHeader field="first_seen_at">
                      {t('firstSeen')}
                    </LayerSortableHeader>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {filteredLayers.map((layer: DockerLayer) => (
                    <Table.Tr key={layer.layer_id}>
                      <Table.Td>
                        <Text size="xs" ff="monospace" c="dimmed">
                          {layer.layer_id.replace('sha256:', '').slice(0, 12)}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        {layer.first_puller_host_user_name ? (
                          <Text size="sm">{layer.first_puller_host_user_name}</Text>
                        ) : (
                          <Text size="sm" c="dimmed" fs="italic">
                            {t('unattributed')}
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td>
                        <BlockSize size={layer.size_bytes} />
                      </Table.Td>
                      <Table.Td>
                        {layer.creation_method ? (
                          <Badge
                            size="sm"
                            color={getCreationMethodColor(layer.creation_method)}
                            variant="light"
                          >
                            {layer.creation_method}
                          </Badge>
                        ) : (
                          <Text size="sm" c="dimmed">
                            -
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td>{formatDate(layer.first_seen_at)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>

              {filteredLayers.length === 0 && (
                <Text size="sm" c="dimmed">
                  {t('noLayersMatch')}
                </Text>
              )}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  )
}
