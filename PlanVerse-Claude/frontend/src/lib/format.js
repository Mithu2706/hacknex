export const fmtM = (v, d = 2) => (v == null || Number.isNaN(v) ? '—' : `${v.toFixed(d)} m`)
export const fmtM2 = (v) => (v == null ? '—' : `${v.toFixed(1)} m²`)
export const pct = (v, d = 1) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)

export const SCALE_STATUS = {
  auto: { label: 'Automatically calibrated', short: 'Auto-calibrated', tone: 'ok' },
  manual: { label: 'Manually calibrated', short: 'Manual', tone: 'accent' },
  estimated: { label: 'Estimated — not calibrated', short: 'Estimated', tone: 'warn' },
}

export const TONE = {
  ok: 'bg-ok/10 text-ok',
  accent: 'bg-accent-soft text-accent-dark',
  warn: 'bg-warn/10 text-warn',
  bad: 'bg-bad/10 text-bad',
  mute: 'bg-paper text-ink-mute border border-line',
}

export const ROOM_COLORS = {
  bedroom: '#C9B79A', living: '#D2BE9C', dining: '#CDB894', kitchen: '#D9D2C4', bathroom: '#C9D4DA',
  circulation: '#DAD3C6', garage: '#C9C6BF', outdoor: '#C4CABB', study: '#CFC0A6', utility: '#D3CEC4', unknown: '#DCD5C8',
}

export const ROOM_TYPE_LABEL = {
  bedroom: 'Bedroom', living: 'Living', dining: 'Dining', kitchen: 'Kitchen', bathroom: 'Bathroom',
  circulation: 'Circulation', garage: 'Garage', outdoor: 'Outdoor', study: 'Study', utility: 'Utility', unknown: 'Unclassified',
}
