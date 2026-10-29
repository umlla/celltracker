export function fmtNum(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (Number.isNaN(number)) return '—'
  return number.toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  })
}

export function fmtInt(value) {
  if (value === null || value === undefined || value === '') return '—'
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

export function fmtPct(value) {
  if (value === null || value === undefined) return '—'
  return `${(Number(value) * 100).toFixed(0)}%`
}

export function todayISO() {
  const now = new Date()
  const offset = now.getTimezoneOffset()
  return new Date(now.getTime() - offset * 60 * 1000).toISOString().slice(0, 10)
}

export function daysFromToday(dateString) {
  if (!dateString) return null
  const target = new Date(`${dateString}T00:00:00`)
  const today = new Date(`${todayISO()}T00:00:00`)
  return Math.round((target - today) / 86400000)
}

export function remainingMeta(days) {
  if (days === null || days === undefined) {
    return { text: '未设置', type: 'info', color: 'muted' }
  }
  if (days < 0) return { text: `逾期 ${Math.abs(days)} 天`, type: 'danger', color: 'danger' }
  if (days === 0) return { text: '今天传代', type: 'danger', color: 'danger' }
  if (days <= 2) return { text: `还剩 ${days} 天`, type: 'warning', color: 'warning' }
  return { text: `还剩 ${days} 天`, type: 'success', color: 'success' }
}

export function statusTagType(status) {
  return {
    良好: 'success',
    一般: 'warning',
    较差: 'danger',
    污染: 'danger',
    在库: 'success',
    已复苏: 'warning',
    已丢弃: 'info',
  }[status] || 'info'
}

export function cellStatusClass(status) {
  return {
    良好: 'good',
    一般: 'fair',
    较差: 'poor',
    污染: 'contaminated',
  }[status] || 'muted'
}

export function initials(name) {
  const text = String(name || '').trim()
  return text.slice(0, 2).toUpperCase()
}

export function sumBy(list, key) {
  return (list || []).reduce((total, item) => total + (Number(item[key]) || 0), 0)
}

export function downloadUrl(url) {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

export function boxLabel(box) {
  return box ? box : '未命名冻存盒'
}
