import { create } from 'zustand'

const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
const initialTheme = localStorage.getItem('rms_theme') || (prefersDark ? 'dark' : 'light')

export const useAppStore = create((set) => ({
  theme: initialTheme,
  page: 'dashboard',
  setPage: (page) => set({ page }),
  toggleTheme: () => set((state) => {
    const next = state.theme === 'dark' ? 'light' : 'dark'
    localStorage.setItem('rms_theme', next)
    return { theme: next }
  }),
  setTheme: (theme) => set({ theme })
}))
