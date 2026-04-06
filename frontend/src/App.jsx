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

const pageTransition = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
  transition: { duration: 0.2 }
}

export default function App() {
  const page = useAppStore((s) => s.page)
  const theme = useAppStore((s) => s.theme)

  const [wsState, setWsState] = useState('connecting')
  const [summary, setSummary] = useState({ devices_total: 0, online_devices: 0, sensors_total: 0, active_alarms: 0 })
  const [devices, setDevices] = useState([])
  const [alarms, setAlarms] = useState([])
  const [history, setHistory] = useState([])
  const [events, setEvents] = useState([])
  const [selectedDevice, setSelectedDevice] = useState(null)
  const [mapBg, setMapBg] = useState(localStorage.getItem('rms_map_bg') || '')

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  const loadAll = async () => {
    const [s, d, a, h, e] = await Promise.all([
      fetch(`${API}/dashboard/summary`).then(r => r.json()),
      fetch(`${API}/devices`).then(r => r.json()),
      fetch(`${API}/alarms/events?active_only=true`).then(r => r.json()),
      fetch(`${API}/data/history?agg=1m`).then(r => r.json()),
      fetch(`${API}/events?limit=200`).then(r => r.json())
    ])
    setSummary(s)
    setDevices(d)
    setAlarms(a)
    setHistory(h)
    setEvents(e)
    setSelectedDevice((prev) => prev || d[0]?.id || null)
  }

  useEffect(() => {
    loadAll()
    const t = setInterval(loadAll, 15000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    let ws
    let ping
    const connect = () => {
      ws = new WebSocket(WS)
      ws.onopen = () => {
        setWsState('connected')
        ping = setInterval(() => ws.readyState === 1 && ws.send('ping'), 10000)
      }
      ws.onclose = () => {
        setWsState('reconnecting')
        clearInterval(ping)
        setTimeout(connect, 1200)
      }
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'alarm') loadAll()
        if (msg.type === 'measurement') {
          setHistory((prev) => [...prev.slice(-400), { timestamp: msg.timestamp, sensor_id: msg.sensor_id, avg_value: msg.value, quality: msg.quality }])
        }
      }
    }
    connect()
    return () => { clearInterval(ping); ws?.close() }
  }, [])

  const deviceCardData = useMemo(() => devices.map((d, idx) => {
    const latest = history.filter((h) => h.sensor_id === idx + 1).slice(-1)[0]
    const hasAlarm = alarms.some((a) => a.sensor_id === idx + 1)
    const status = hasAlarm ? 'ALARM' : (d.status === 'ONLINE' ? 'OK' : 'OFFLINE')
    return {
      ...d,
      temp: latest?.avg_value?.toFixed?.(1) ?? '--',
      status,
      updated: latest?.timestamp || d.last_seen || '--'
    }
  }), [devices, history, alarms])

  const selectedSeries = useMemo(
    () => history.filter((h) => selectedDevice ? true : true).map((h) => ({ ...h, t: new Date(h.timestamp).toLocaleTimeString() })),
    [history, selectedDevice]
  )

  const uploadMap = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const fr = new FileReader()
    fr.onload = () => {
      setMapBg(fr.result)
      localStorage.setItem('rms_map_bg', fr.result)
    }
    fr.readAsDataURL(file)
  }

  const pageNode = {
    dashboard: (
      <div className="grid-2">
        <div className="kpi-grid">
          <div className="kpi card"><div className="kpi-value">{summary.devices_total}</div><div>Devices</div></div>
          <div className="kpi card"><div className="kpi-value">{summary.online_devices}</div><div>Online</div></div>
          <div className="kpi card"><div className="kpi-value">{summary.sensors_total}</div><div>Sensors</div></div>
          <div className="kpi card danger"><div className="kpi-value">{summary.active_alarms}</div><div>Active alarms</div></div>
        </div>
        <div className="card chart-card">
          <h3>Temperature / metrics (1m aggregation)</h3>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={selectedSeries.slice(-120)}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="t" hide />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="avg_value" stroke="#3B82F6" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <h3>Device cards</h3>
          <div className="device-grid">
            {deviceCardData.map((d, i) => (
              <motion.div whileHover={{ y: -4 }} className={`device-card ${d.status === 'ALARM' ? 'pulse' : ''}`} key={d.id}>
                <div className="row"><strong>{d.name}</strong><span className={`badge ${d.status.toLowerCase()}`}>{d.status}</span></div>
                <div className="big-number">{d.temp}°</div>
                <small>Updated: {String(d.updated).replace('T',' ').slice(0,19)}</small>
                <div className="mini-chart">
                  <ResponsiveContainer width="100%" height={60}>
                    <AreaChart data={selectedSeries.slice(-30)}>
                      <Area dataKey="avg_value" stroke="#22C55E" fillOpacity={0.2} fill="#22C55E" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
        <div className="card">
          <h3>Recent alarms</h3>
          {alarms.length === 0 && <div className="muted">No active alarms</div>}
          {alarms.map((a) => (
            <div className="alarm-item" key={a.id}><span className="sev critical">critical</span> Sensor {a.sensor_id}: {a.message}</div>
          ))}
        </div>
      </div>
    ),
    devices: (
      <div className="card">
        <h3>Device details</h3>
        <div className="row wrap">
          <label>Select device</label>
          <select value={selectedDevice || ''} onChange={(e) => setSelectedDevice(Number(e.target.value))}>
            {devices.map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}
          </select>
        </div>
        <div className="control-grid">
          <button onClick={() => fetch(`${API}/control`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device_id: selectedDevice, command: 'set_setpoint', value: -8 }) })}>Setpoint -8</button>
          <button onClick={() => fetch(`${API}/control`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device_id: selectedDevice, command: 'defrost', value: 1 }) })}>Start defrost</button>
          <button onClick={() => fetch(`${API}/control`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device_id: selectedDevice, command: 'fan_mode', value: 'auto' }) })}>Fan auto</button>
        </div>
      </div>
    ),
    alarms: (
      <div className="card">
        <h3>Alarms</h3>
        {alarms.map((a) => (
          <div className="alarm-item row" key={a.id}>
            <span><strong>Device Sensor {a.sensor_id}</strong> — {a.message}</span>
            <button onClick={() => fetch(`${API}/alarms/ack`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event_id: a.id }) }).then(loadAll)}>ACK</button>
          </div>
        ))}
      </div>
    ),
    reports: (
      <div className="grid-2">
        <div className="card">
          <h3>Exports</h3>
          <div className="row wrap">
            <button onClick={() => window.open(`${API}/reports/csv?hours=24`, '_blank')}>CSV</button>
            <button onClick={() => window.open(`${API}/reports/pdf?hours=24`, '_blank')}>PDF</button>
            <button onClick={() => window.open(`${API}/backup/export`, '_blank')}>Backup JSON</button>
          </div>
        </div>
        <div className="card">
          <h3>Audit stream</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={events.slice(0, 30).map((e, i) => ({ name: i + 1, v: 1 }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="v" fill="#3B82F6" />
            </BarChart>
          </ResponsiveContainer>
          <div className="events-list">{events.slice(0, 20).map((e) => <div key={e.id}>{e.type} — {e.description}</div>)}</div>
        </div>
      </div>
    ),
    map: (
      <div className="card">
        <h3>Floor plan map</h3>
        <input type="file" accept="image/*" onChange={uploadMap} />
        <div className="map-stage" style={{ backgroundImage: mapBg ? `url(${mapBg})` : 'none' }}>
          {devices.map((d, idx) => (
            <motion.button key={d.id} className={`map-marker ${alarms.length ? 'alarm' : ''}`} drag dragMomentum={false} style={{ left: 24 + idx * 60, top: 30 + idx * 30 }}>
              {d.name}
            </motion.button>
          ))}
        </div>
      </div>
    )
  }[page]

  return (
    <div className="app-shell">
      <Sidebar />
      <main>
        <Topbar wsState={wsState} />
        <AnimatePresence mode="wait">
          <motion.section key={page} {...pageTransition} className="page-wrap">
            {pageNode}
          </motion.section>
        </AnimatePresence>
      </main>
      <nav className="mobile-nav">
        {['dashboard', 'devices', 'alarms', 'reports', 'map'].map((p) => (
          <button key={p} className={page === p ? 'active' : ''} onClick={() => useAppStore.getState().setPage(p)}>{p}</button>
        ))}
      </nav>
    </div>
  )
}
