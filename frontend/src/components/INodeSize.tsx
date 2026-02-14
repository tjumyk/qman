interface INodeSizeProps {
  size: number
}

export function INodeSize({ size }: INodeSizeProps) {
  let num = size
  if (num > 10000) {
    num = Math.round(num / 1000)
    return <>{num}k</>
  }
  return <>{num}</>
}
