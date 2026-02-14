import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BlockSize } from './BlockSize'

describe('BlockSize', () => {
  it('formats bytes', () => {
    render(<BlockSize size={0} />)
    expect(screen.getByText('0B')).toBeInTheDocument()
  })

  it('formats KB', () => {
    render(<BlockSize size={1024} />)
    expect(screen.getByText('1KB')).toBeInTheDocument()
  })

  it('formats MB', () => {
    render(<BlockSize size={1024 * 1024} />)
    expect(screen.getByText('1MB')).toBeInTheDocument()
  })
})
