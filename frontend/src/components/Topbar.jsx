import { Moon, Sun } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'

export default function Topbar({ wsState }) {
  const theme = useAppStore((s) => s.theme)
  const toggleTheme = useAppStore((s) => s.toggleTheme)

  return (
    <header className="topbar glass">
      <div className="pill">WebSocket: <strong>{wsState}</strong></div>
      <button className="theme-btn" onClick={toggleTheme}>
        {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />} {theme === 'dark' ? 'Light' : 'Dark'}
      </button>
    </header>
  )
}
