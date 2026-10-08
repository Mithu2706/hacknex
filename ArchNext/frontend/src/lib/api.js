async function handle(res) {
  if (!res.ok) {
    let msg = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (body?.detail) msg = typeof body.detail === 'string' ? body.detail : msg
    } catch { /* not JSON */ }
    if (res.status === 502 || res.status === 504) msg = 'The processing service is not reachable. Make sure it is running and try again.'
    throw new Error(msg)
  }
  return res.json()
}

async function request(url, opts) {
  try {
    return await handle(await fetch(url, opts))
  } catch (e) {
    if (e instanceof TypeError) throw new Error('The processing service is not reachable. Make sure it is running and try again.')
    throw e
  }
}

export const api = {
  upload(file) {
    const fd = new FormData()
    fd.append('file', file)
    return request('/api/plans', { method: 'POST', body: fd })
  },
  calibrate(id, p1, p2, distance, unit) {
    return request(`/api/plans/${id}/calibration`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ p1, p2, distance, unit }),
    })
  },
  resetCalibration(id) {
    return request(`/api/plans/${id}/calibration`, { method: 'DELETE' })
  },
  applyFix(id, key) {
    return request(`/api/plans/${id}/fixes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    })
  },
  undoFix(id) {
    return request(`/api/plans/${id}/fixes/undo`, { method: 'POST' })
  },
  evaluate(id, file) {
    const fd = new FormData()
    fd.append('file', file)
    return request(`/api/plans/${id}/evaluate`, { method: 'POST', body: fd })
  },
  benchmark() {
    return request('/api/benchmark')
  },
}
