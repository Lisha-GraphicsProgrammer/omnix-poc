import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Rules from './pages/Rules'
import AlertDetail from './pages/AlertDetail'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/login" />} />
        <Route path="/login" element={<Login />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/rules" element={<Rules />} />
        <Route path="/alert/:id" element={<AlertDetail />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App