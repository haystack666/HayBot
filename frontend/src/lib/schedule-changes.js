export function mergeScheduleChanges(previous, incoming, day, generation) {
  return [...new Map([...previous, ...incoming].map(item => [item.id, item])).values()]
    .filter(item => item.day === day)
    .map(item => ({ ...item, current_generation: !!generation && item.generation_id === generation }))
    .sort((left, right) => right.id - left.id)
}
