import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  AreaChart, Area, CartesianGrid, XAxis, YAxis, Tooltip,
  ResponsiveContainer, LineChart, Line, BarChart, Bar
} from 'recharts'
import Sidebar from './components/Sidebar'
import Topbar from './components/Topbar'
import { useAppStore } from './store/useAppStore'

const API = 'http://localhost:8000'
const WS = 'ws://localhost:8000/ws'

export default function App() {
  const page = useAppStore((s) => s.page)
  const theme = useAppStore((s) => s.theme)
  const setPage = useAppStore((s) => s.setPage)

  const [wsState, setWsState] = useState('connecting')
  const [summary, setSummary] = useState({ devices_total: 0, online_devices: 0, sensors_total: 0, active_alarms: 0, latest: [] })
  const [devices, setDevices] = useState([])
  const [sensors, setSensors] = useState([])
  const [alarms, setAlarms] = useState([])
  const [history, setHistory] = useState([])
  const [events, setEvents] = useState([])
  const [selectedDevice, setSelectedDevice] = useState(null)
  const [selectedSensors, setSelectedSensors] = useState([])
  const [range, setRange] = useState('24h')
  const [mapBg, setMapBg] = useState(localStorage.getItem('rms_map_bg') || '')
  const [mapZoom, setMapZoom] = useState(1)
  const [deviceFilter, setDeviceFilter] = useState({ status: 'all', zone: 'all', type: 'all' })
  const [systemSettings, setSystemSettings] = useState(() => JSON.parse(localStorage.getItem('rms_settings') || '{"timezone":"UTC","units":"C"}'))

  useEffect(() => { document.documentElement.setAttribute('data-theme', theme) }, [theme])

  const loadAll = async () => {
    const [s, d, sn, a, h, e] = await Promise.all([
      fetch(`${API}/dashboard/summary`).then(r => r.json()),
      fetch(`${API}/devices`).then(r => r.json()),
      fetch(`${API}/sensors`).then(r => r.json()),
      fetch(`${API}/alarms/events?active_only=true`).then(r => r.json()),
      fetch(`${API}/data/history?agg=1m`).then(r => r.json()),
      fetch(`${API}/events?limit=200`).then(r => r.json())
    ])
    setSummary(s); setDevices(d); setSensors(sn); setAlarms(a); setHistory(h); setEvents(e)
    setSelectedDevice((p) => p || d[0]?.id || null)
    setSelectedSensors((p) => p.length ? p : sn.slice(0, 8).map(x => x.id))
  }

  useEffect(() => { loadAll(); const t = setInterval(loadAll, 15000); return () => clearInterval(t) }, [])

  useEffect(() => {
    let ws, ping
    const connect = () => {
      ws = new WebSocket(WS)
      ws.onopen = () => { setWsState('connected'); ping = setInterval(() => ws.readyState === 1 && ws.send('ping'), 10000) }
      ws.onclose = () => { setWsState('reconnecting'); clearInterval(ping); setTimeout(connect, 1200) }
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'alarm') loadAll()
        if (msg.type === 'measurement') setHistory((prev) => [...prev.slice(-3000), { timestamp: msg.timestamp, sensor_id: msg.sensor_id, avg_value: msg.value, quality: msg.quality }])
      }
    }
    connect()
    return () => { clearInterval(ping); ws?.close() }
  }, [])

  const deviceStatus = (d) => {
    const hasAlarm = alarms.some((a) => sensors.find((s) => s.id === a.sensor_id)?.device_id === d.id)
    if (hasAlarm) return 'ALARM'
    if (d.status !== 'ONLINE') return 'OFFLINE'
    return 'OK'
  }

  const filteredDevices = useMemo(() => devices.filter((d) => {
    const st = deviceStatus(d)
    const zone = d.port || 'unknown'
    const sensorTypes = sensors.filter(s => s.device_id === d.id).map(s => s.data_type)
    return (deviceFilter.status === 'all' || st === deviceFilter.status)
      && (deviceFilter.zone === 'all' || zone === deviceFilter.zone)
      && (deviceFilter.type === 'all' || sensorTypes.includes(deviceFilter.type))
  }), [devices, sensors, alarms, deviceFilter])

  const series = useMemo(() => {
    const windowMap = { '1h': 1, '24h': 24, '7d': 24 * 7 }
    const hours = windowMap[range] || 24
    const cutoff = Date.now() - hours * 3600 * 1000
    return history
      .filter((h) => selectedSensors.includes(h.sensor_id) && new Date(h.timestamp).getTime() >= cutoff)
      .map((h) => ({ ...h, t: new Date(h.timestamp).toLocaleString() }))
  }, [history, selectedSensors, range])

  const kpi = useMemo(() => {
    const vals = series.map(x => Number(x.avg_value)).filter(x => !Number.isNaN(x))
    const avg = vals.length ? (vals.reduce((a, b) => a + b, 0) / vals.length) : 0
    return { avg: avg.toFixed(2), min: vals.length ? Math.min(...vals).toFixed(2) : '-', max: vals.length ? Math.max(...vals).toFixed(2) : '-' }
  }, [series])

  const saveSettings = () => localStorage.setItem('rms_settings', JSON.stringify(systemSettings))
  const uploadMap = (e) => { const f = e.target.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = () => { setMapBg(r.result); localStorage.setItem('rms_map_bg', r.result) }; r.readAsDataURL(f) }

  const ack = (id) => fetch(`${API}/alarms/ack`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event_id: id }) }).then(loadAll)
  const closeAlarm = (id) => fetch(`${API}/alarms/events/${id}/close`, { method: 'POST' }).then(loadAll)
  const commentAlarm = (id) => {
    const c = prompt('Коментар до тривоги:')
    if (!c) return
    fetch(`${API}/alarms/events/${id}/comment`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ comment: c }) }).then(loadAll)
  }

  const pages = {
    dashboard: (
      <div className='grid-2'>
        <div className='kpi-grid'>
          <div className='kpi card'><div className='kpi-value'>{summary.sensors_total}</div><div>Активні датчики</div></div>
          <div className='kpi card danger'><div className='kpi-value'>{summary.active_alarms}</div><div>Тривоги зараз</div></div>
          <div className='kpi card'><div className='kpi-value'>{kpi.avg}</div><div>Середня t°</div></div>
          <div className='kpi card'><div className='kpi-value'>{kpi.min} / {kpi.max}</div><div>Min / Max</div></div>
        </div>
        <div className='card'><h3>Останні події</h3><div className='events-list'>{events.slice(0, 8).map(e => <div key={e.id}>{e.type}: {e.description}</div>)}</div></div>
        <div className='card chart-card'>
          <h3>Температура за 24 години</h3>
          <ResponsiveContainer width='100%' height={280}><LineChart data={series.slice(-240)}><CartesianGrid strokeDasharray='3 3' /><XAxis dataKey='t' hide /><YAxis /><Tooltip /><Line type='monotone' dataKey='avg_value' stroke='#3B82F6' dot={false} /></LineChart></ResponsiveContainer>
        </div>
        <div className='card'>
          <h3>Топ проблемні точки</h3>
          {alarms.length === 0 ? <div className='muted'>Немає активних тривог</div> : alarms.slice(0, 6).map(a => <div className='alarm-item' key={a.id}>Sensor {a.sensor_id}: {a.message}</div>)}
          <button onClick={() => setPage('map')}>Відкрити карту</button>
        </div>
      </div>
    ),
    devices: (
      <div className='card'>
        <h3>Обладнання / Датчики</h3>
        <div className='row wrap'>
          <select value={deviceFilter.status} onChange={(e) => setDeviceFilter(v => ({ ...v, status: e.target.value }))}><option value='all'>Статус: всі</option><option value='OK'>🟢 Норма</option><option value='ALARM'>🔴 Аварія</option><option value='OFFLINE'>⚪ Offline</option></select>
          <select value={deviceFilter.zone} onChange={(e) => setDeviceFilter(v => ({ ...v, zone: e.target.value }))}><option value='all'>Зона: всі</option>{[...new Set(devices.map(d => d.port))].map(z => <option key={z} value={z}>{z}</option>)}</select>
          <select value={deviceFilter.type} onChange={(e) => setDeviceFilter(v => ({ ...v, type: e.target.value }))}><option value='all'>Тип: всі</option>{[...new Set(sensors.map(s => s.data_type))].map(t => <option key={t} value={t}>{t}</option>)}</select>
        </div>
        <table className='table'>
          <thead><tr><th>Назва</th><th>Типи датчиків</th><th>Поточне</th><th>Статус</th><th>Оновлено</th><th>Дії</th></tr></thead>
          <tbody>
            {filteredDevices.map(d => {
              const st = deviceStatus(d)
              const colorClass = st === 'ALARM' ? 'danger' : st === 'OFFLINE' ? 'muted' : 'success'
              const vals = history.filter(h => sensors.find(s => s.id === h.sensor_id)?.device_id === d.id).slice(-1)[0]
              return <tr key={d.id}><td>{d.name}</td><td>{[...new Set(sensors.filter(s => s.device_id === d.id).map(s => s.data_type))].join(', ')}</td><td>{vals?.avg_value ?? '--'}</td><td className={colorClass}>{st}</td><td>{(vals?.timestamp || d.last_seen || '--').toString().slice(0,19)}</td><td><button onClick={() => { setSelectedDevice(d.id); setPage('analytics') }}>Графік</button></td></tr>
            })}
          </tbody>
        </table>
      </div>
    ),
    analytics: (
      <div className='grid-2'>
        <div className='card'>
          <h3>Аналітика / Graphs</h3>
          <div className='row wrap'>
            <select value={range} onChange={(e) => setRange(e.target.value)}><option value='1h'>1 година</option><option value='24h'>24 години</option><option value='7d'>7 днів</option></select>
            <select multiple value={selectedSensors.map(String)} onChange={(e) => setSelectedSensors([...e.target.selectedOptions].map(o => Number(o.value)))}>
              {sensors.map(s => <option key={s.id} value={s.id}>{s.id} / {s.name}</option>)}
            </select>
          </div>
          <ResponsiveContainer width='100%' height={320}><LineChart data={series}><CartesianGrid strokeDasharray='3 3' /><XAxis dataKey='t' hide /><YAxis /><Tooltip /><Line type='monotone' dataKey='avg_value' stroke='#2563EB' dot={false} /></LineChart></ResponsiveContainer>
        </div>
        <div className='card'>
          <h3>Експорт</h3>
          <button onClick={() => window.open(`${API}/reports/csv?hours=24`, '_blank')}>CSV</button>
          <button onClick={() => window.open(`${API}/reports/pdf?hours=24`, '_blank')}>PDF</button>
          <ResponsiveContainer width='100%' height={220}><AreaChart data={series.slice(-100)}><Area dataKey='avg_value' stroke='#22C55E' fill='#22C55E33' /></AreaChart></ResponsiveContainer>
        </div>
      </div>
    ),
    alarms: (
      <div className='card'>
        <h3>Тривоги / Events</h3>
        <table className='table'><thead><tr><th>Датчик</th><th>Тип</th><th>Початок</th><th>Кінець</th><th>Статус</th><th>Дії</th></tr></thead><tbody>
          {alarms.map(a => <tr key={a.id}><td>{a.sensor_id}</td><td>{a.message}</td><td>{a.start_time?.slice(0,19)}</td><td>{a.end_time?.slice(0,19) || '-'}</td><td>{a.status}</td><td className='row wrap'><button onClick={() => ack(a.id)}>ACK</button><button onClick={() => commentAlarm(a.id)}>Коментар</button><button onClick={() => closeAlarm(a.id)}>Закрити</button></td></tr>)}
        </tbody></table>
      </div>
    ),
    map: (
      <div className='card'>
        <h3>Maps / Layout</h3>
        <div className='row wrap'><input type='file' accept='image/*' onChange={uploadMap} /><label>Zoom {mapZoom.toFixed(1)}x</label><input type='range' min='0.5' max='2' step='0.1' value={mapZoom} onChange={(e) => setMapZoom(Number(e.target.value))} /></div>
        <div className='map-legend sticky'>🟢 Норма | 🟡 Попередження | 🔴 Аварія</div>
        <div className='map-stage' style={{ backgroundImage: mapBg ? `url(${mapBg})` : 'none', transform: `scale(${mapZoom})`, transformOrigin: 'top left' }}>
          {devices.map((d, idx) => {
            const st = deviceStatus(d)
            const dot = st === 'ALARM' ? '🔴' : st === 'OFFLINE' ? '⚪' : '🟢'
            return <motion.button drag dragMomentum={false} key={d.id} className='map-marker' style={{ left: 30 + idx * 65, top: 25 + idx * 38 }} onClick={() => { setSelectedDevice(d.id); setPage('analytics') }} title={`${d.name}`}>{dot} {d.name}</motion.button>
          })}
        </div>
      </div>
    ),
    reports: (
      <div className='grid-2'>
        <div className='card'><h3>ISO / HACCP звіти</h3><p>Денний / Місячний / По датчику</p><button onClick={() => window.open(`${API}/reports/csv?hours=24`, '_blank')}>Денний CSV</button><button onClick={() => window.open(`${API}/reports/pdf?hours=24`, '_blank')}>Денний PDF</button><button onClick={() => window.open(`${API}/backup/export`, '_blank')}>Backup JSON</button></div>
        <div className='card'><h3>Статистика подій</h3><ResponsiveContainer width='100%' height={260}><BarChart data={events.slice(0, 50).map((e, i) => ({ i, v: 1 }))}><CartesianGrid strokeDasharray='3 3' /><XAxis dataKey='i' /><YAxis /><Tooltip /><Bar dataKey='v' fill='#3B82F6' /></BarChart></ResponsiveContainer></div>
      </div>
    ),
    settings: (
      <div className='card'>
        <h3>Налаштування</h3>
        <div className='grid-2'>
          <div className='card'><h4>Система</h4><label>Timezone</label><input value={systemSettings.timezone} onChange={(e) => setSystemSettings(v => ({ ...v, timezone: e.target.value }))} /><label>Одиниці</label><select value={systemSettings.units} onChange={(e) => setSystemSettings(v => ({ ...v, units: e.target.value }))}><option value='C'>°C</option><option value='F'>°F</option></select><button onClick={saveSettings}>Зберегти</button></div>
          <div className='card'><h4>Інтеграції</h4><p>Email / Telegram / SMS конфігуруються через ENV backend.</p><button onClick={() => fetch(`${API}/integrations/status`).then(r => r.json()).then(d => alert(JSON.stringify(d, null, 2)))}>Перевірити статус</button></div>
        </div>
      </div>
    )
  }

  return (
    <div className='app-shell'>
      <Sidebar />
      <main>
        <Topbar wsState={wsState} />
        <AnimatePresence mode='wait'>
          <motion.section key={page} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: .2 }} className='page-wrap'>
            {pages[page]}
          </motion.section>
        </AnimatePresence>
      </main>
      <nav className='mobile-nav'>{['dashboard','devices','analytics','alarms','map','reports','settings'].map(p => <button key={p} className={page === p ? 'active' : ''} onClick={() => setPage(p)}>{p}</button>)}</nav>
    </div>
  )
}
