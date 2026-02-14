import { Alert } from '@mantine/core'
import type { BasicError } from '../api/schemas'

interface ErrorMessageProps {
  error: BasicError
}

export function ErrorMessage({ error }: ErrorMessageProps) {
  return (
    <Alert color="red" title={error.msg}>
      {error.detail}
    </Alert>
  )
}
