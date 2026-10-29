export const viewingDefaults = {preview_enabled:true,preview_after_minutes:3,max_video_minutes:60,segment_seconds:15,skip_seconds:0}
export const viewingFields = [
  ['preview_after_minutes','超过此时长跳看（分钟）',1,120],
  ['max_video_minutes','最长视频时长（分钟）',1,120],
  ['segment_seconds','每段观看（秒）',3,30],
  ['skip_seconds','两段之间跳过（秒，0 为自动）',0,3600],
]
export function viewingError(value) {
  for(const [key,label,min,max] of viewingFields) {
    if(!Number.isInteger(value[key])||value[key]<min||value[key]>max)return `${label}须为 ${min}–${max} 的整数`
  }
  if(value.preview_enabled&&value.preview_after_minutes>value.max_video_minutes)return '跳看起始时长不能大于最长视频时长'
  return ''
}
