import { LayoutDashboard, Refrigerator, LineChart, TriangleAlert, FileBarChart2, Map, Settings, Thermometer, Users, ScrollText } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'

const items = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'devices', label: 'Devices', icon: Refrigerator },
  { id: 'sensors', label: 'Sensors', icon: Thermometer },
  { id: 'analytics', label: 'Analytics', icon: LineChart },
  { id: 'alarms', label: 'Alarms', icon: TriangleAlert },
  { id: 'map', label: 'Maps', icon: Map },
  { id: 'reports', label: 'Reports', icon: FileBarChart2 },
  { id: 'users', label: 'Users', icon: Users },
  { id: 'logs', label: 'Logs', icon: ScrollText },
  { id: 'settings', label: 'Settings', icon: Settings }
]

export default function Sidebar() {
  const page = useAppStore((s) => s.page)
  const setPage = useAppStore((s) => s.setPage)

  return (
    <aside className="sidebar glass">
      <div className="brand">RMS XWEB+ UI</div>
      {items.map((item) => {
        const Icon = item.icon
        return (
          <button key={item.id} className={`nav-btn ${page === item.id ? 'active' : ''}`} onClick={() => setPage(item.id)}>
            <Icon size={18} /> {item.label}
          </button>
        )
      })}
    </aside>
  )
}
