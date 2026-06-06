import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material'
import App from './App.tsx'

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#00D4FF' },
    secondary: { main: '#7C3AED' },
    background: { default: '#060818', paper: '#0D1117' },
    error: { main: '#FF4444' },
    warning: { main: '#FF9500' },
    success: { main: '#00C853' },
  },
  typography: {
    fontFamily: '"Inter", "Roboto", sans-serif',
  },
  shape: { borderRadius: 12 },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <App />
    </ThemeProvider>
  </StrictMode>
)