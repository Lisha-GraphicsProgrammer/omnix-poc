import { useParams, useNavigate } from 'react-router-dom'
import { Box, Typography, Button } from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ThumbDownIcon from '@mui/icons-material/ThumbDown'
import CameraAltIcon from '@mui/icons-material/CameraAlt'
import AccessTimeIcon from '@mui/icons-material/AccessTime'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import PersonIcon from '@mui/icons-material/Person'
import { useState } from 'react'

const mockAlerts = [
  { id: 1, camera: 'Camera 1 — Entry Gate', rule: 'No Helmet', time: '14:32:11', severity: 'high', description: 'Worker detected entering the loading zone without a safety helmet.', personId: 27, duration: 59, confidence: 94, zone: 'Loading Zone A' },
  { id: 2, camera: 'Camera 2 — Crane Zone', rule: 'No Helmet', time: '14:28:45', severity: 'high', description: 'Worker detected near crane operation area without PPE helmet.', personId: 3, duration: 31, confidence: 91, zone: 'Crane Zone B' },
  { id: 3, camera: 'Camera 3 — Storage', rule: 'Forklift Near Worker', time: '14:15:02', severity: 'critical', description: 'Forklift detected within 5 meters of a worker in the material storage area.', personId: 9, duration: 8, confidence: 88, zone: 'Storage Zone' },
  { id: 4, camera: 'Camera 1 — Entry Gate', rule: 'Worker Count > 10', time: '13:55:30', severity: 'medium', description: 'Worker count exceeded threshold of 10 in the restricted entry gate area.', personId: null, duration: 45, confidence: 96, zone: 'Entry Gate' },
  { id: 5, camera: 'Camera 2 — Crane Zone', rule: 'No Helmet', time: '13:40:18', severity: 'high', description: 'Worker detected near crane without helmet. ByteTrack persistent tracking confirmed.', personId: 43, duration: 8, confidence: 87, zone: 'Crane Zone B' },
]

const severityConfig: Record<string, { color: string, bg: string, border: string, label: string }> = {
  critical: { color: '#fca5a5', bg: 'rgba(239,68,68,0.1)', border: 'rgba(239,68,68,0.25)', label: 'CRITICAL' },
  high: { color: '#fbbf24', bg: 'rgba(251,191,36,0.1)', border: 'rgba(251,191,36,0.25)', label: 'HIGH' },
  medium: { color: '#818cf8', bg: 'rgba(99,102,241,0.1)', border: 'rgba(99,102,241,0.25)', label: 'MEDIUM' },
}

function FakeScreenshot({ camera, rule, personId }: { camera: string, rule: string, personId: number | null }) {
  return (
    <Box sx={{ position: 'relative', width: '100%', aspectRatio: '16/9', borderRadius: '14px', overflow: 'hidden', background: 'linear-gradient(135deg, #0f1923 0%, #1a2a3a 50%, #0d1f2d 100%)', border: '1px solid rgba(255,255,255,0.08)' }}>
      <Box sx={{ position: 'absolute', inset: 0, backgroundImage: 'linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px)', backgroundSize: '40px 40px' }} />
      <Box sx={{ position: 'absolute', bottom: '10%', left: '5%', width: '90%', height: '20%', background: 'rgba(255,255,255,0.03)', borderRadius: '4px' }} />
      <Box sx={{ position: 'absolute', bottom: '30%', left: '15%', width: '10%', height: '50%', background: 'rgba(255,255,255,0.04)' }} />
      <Box sx={{ position: 'absolute', bottom: '30%', left: '55%', width: '8%', height: '40%', background: 'rgba(255,255,255,0.04)' }} />
      <Box sx={{ position: 'absolute', bottom: '30%', left: '75%', width: '12%', height: '35%', background: 'rgba(255,255,255,0.03)' }} />
      <Box sx={{ position: 'absolute', left: '8%', top: '12%', width: '84%', height: '70%', border: '1.5px dashed rgba(99,102,241,0.35)', borderRadius: '8px' }}>
        <Box sx={{ position: 'absolute', top: -10, left: 8, px: 1, py: .2, background: 'rgba(99,102,241,0.7)', borderRadius: '4px' }}>
          <Typography sx={{ color: '#fff', fontSize: '.52rem', fontWeight: 700 }}>DETECTION ZONE</Typography>
        </Box>
      </Box>
      <Box sx={{ position: 'absolute', left: '22%', top: '25%', width: '20%', height: '45%' }}>
        <Box sx={{ position: 'absolute', inset: 0, border: '2px solid #ef4444', borderRadius: '4px', boxShadow: '0 0 16px rgba(239,68,68,0.4)', animation: 'pulse .9s infinite', '@keyframes pulse': { '0%,100%': { opacity: 1 }, '50%': { opacity: .5 } } }} />
        <Box sx={{ position: 'absolute', top: -22, left: 0, background: '#ef4444', px: .8, py: .2, borderRadius: '3px', whiteSpace: 'nowrap' }}>
          <Typography sx={{ color: '#fff', fontSize: '.52rem', fontWeight: 700 }}>
            {personId ? `ID:${personId} · ` : ''}{rule.toUpperCase()} · 94%
          </Typography>
        </Box>
        <Box sx={{ position: 'absolute', inset: '10% 25%', background: 'rgba(239,68,68,0.15)', borderRadius: '4px 4px 0 0' }} />
      </Box>
      <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, px: 1.5, py: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'linear-gradient(to bottom, rgba(0,0,0,0.7), transparent)' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: .8 }}>
          <Box sx={{ width: 6, height: 6, borderRadius: '50%', background: '#ef4444', animation: 'blink 1s infinite', '@keyframes blink': { '0%,100%': { opacity: 1 }, '50%': { opacity: .2 } } }} />
          <Typography sx={{ color: 'rgba(255,255,255,0.7)', fontSize: '.6rem', fontWeight: 600 }}>REC</Typography>
          <Typography sx={{ color: 'rgba(255,255,255,0.3)', fontSize: '.55rem', ml: 1 }}>{camera}</Typography>
        </Box>
        <Typography sx={{ color: 'rgba(255,255,255,0.4)', fontSize: '.55rem', fontFamily: 'monospace' }}>
          {new Date().toLocaleTimeString()} · OMNIX CV Engine
        </Typography>
      </Box>
      <Box sx={{ position: 'absolute', bottom: 0, left: 0, right: 0, px: 1.5, py: 1, background: 'linear-gradient(to top, rgba(0,0,0,0.8), transparent)', display: 'flex', gap: 1 }}>
        <Box sx={{ px: 1, py: .3, background: 'rgba(239,68,68,0.2)', border: '1px solid rgba(239,68,68,0.4)', borderRadius: '4px' }}>
          <Typography sx={{ color: '#fca5a5', fontSize: '.55rem', fontWeight: 700 }}>⚠ VIOLATION DETECTED</Typography>
        </Box>
        <Box sx={{ px: 1, py: .3, background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.3)', borderRadius: '4px' }}>
          <Typography sx={{ color: '#a5b4fc', fontSize: '.55rem', fontWeight: 600 }}>ByteTrack Active</Typography>
        </Box>
      </Box>
    </Box>
  )
}

export default function AlertDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [markedFP, setMarkedFP] = useState(false)
  const alert = mockAlerts.find(a => a.id === Number(id))

  if (!alert) return (
    <Box sx={{ minHeight: '100vh', background: '#08080a', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Typography sx={{ color: 'rgba(255,255,255,0.4)' }}>Alert not found</Typography>
    </Box>
  )

  const sev = severityConfig[alert.severity]

  return (
    <Box sx={{ minHeight: '100vh', background: '#08080a', fontFamily: '"Inter", system-ui, sans-serif' }}>

      {/* TOP BAR */}
      <Box sx={{ px: 4, py: 0, height: 64, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: 2, background: 'rgba(13,13,16,0.95)', backdropFilter: 'blur(20px)', position: 'sticky', top: 0, zIndex: 50 }}>
        <Box onClick={() => navigate('/dashboard')} sx={{ display: 'flex', alignItems: 'center', gap: 1, cursor: 'pointer', px: 1.5, py: .7, borderRadius: '8px', border: '1px solid rgba(255,255,255,0.07)', background: 'rgba(255,255,255,0.03)', transition: 'all .2s', '&:hover': { background: 'rgba(255,255,255,0.06)' } }}>
          <ArrowBackIcon sx={{ fontSize: 14, color: 'rgba(255,255,255,0.4)' }} />
          <Typography sx={{ color: 'rgba(255,255,255,0.4)', fontSize: '.78rem' }}>Dashboard</Typography>
        </Box>

        <Box sx={{ width: '1px', height: 16, background: 'rgba(255,255,255,0.08)', flexShrink: 0 }} />

        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Box sx={{ width: 28, height: 28, borderRadius: '7px', background: 'linear-gradient(135deg, #6366f1, #8b5cf6)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 14px rgba(99,102,241,0.4)', flexShrink: 0 }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
              <ellipse cx="12" cy="12" rx="10" ry="6.5" stroke="white" strokeWidth="1.5"/>
              <circle cx="12" cy="12" r="3.5" fill="white"/>
              <circle cx="13.5" cy="10.5" r="1.4" fill="#6366f1"/>
            </svg>
          </Box>
          <Typography sx={{ color: '#fff', fontWeight: 700, fontSize: '.92rem', letterSpacing: '-.2px' }}>OMNIX</Typography>
          <Box sx={{ width: '1px', height: 16, background: 'rgba(255,255,255,0.08)', flexShrink: 0 }} />
          <Typography sx={{ color: 'rgba(255,255,255,0.35)', fontSize: '.82rem' }}>Alert Detail</Typography>
        </Box>

        <Box sx={{ ml: 'auto', display: 'flex', gap: 1 }}>
          {alert.id > 1 && (
            <Box onClick={() => navigate(`/alert/${alert.id - 1}`)} sx={{ px: 1.5, py: .6, borderRadius: '7px', border: '1px solid rgba(255,255,255,0.07)', background: 'rgba(255,255,255,0.03)', cursor: 'pointer', '&:hover': { background: 'rgba(255,255,255,0.06)' } }}>
              <Typography sx={{ color: 'rgba(255,255,255,0.35)', fontSize: '.75rem' }}>← Prev</Typography>
            </Box>
          )}
          {alert.id < mockAlerts.length && (
            <Box onClick={() => navigate(`/alert/${alert.id + 1}`)} sx={{ px: 1.5, py: .6, borderRadius: '7px', border: '1px solid rgba(255,255,255,0.07)', background: 'rgba(255,255,255,0.03)', cursor: 'pointer', '&:hover': { background: 'rgba(255,255,255,0.06)' } }}>
              <Typography sx={{ color: 'rgba(255,255,255,0.35)', fontSize: '.75rem' }}>Next →</Typography>
            </Box>
          )}
        </Box>
      </Box>

      {/* MAIN */}
      <Box sx={{ maxWidth: 1100, mx: 'auto', p: '40px 32px', display: 'flex', gap: 4 }}>

        {/* LEFT */}
        <Box sx={{ flex: 1.4 }}>
          <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 3 }}>
            <Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1.5 }}>
                <Box sx={{ px: 2, py: .5, borderRadius: '6px', background: sev.bg, border: `1px solid ${sev.border}` }}>
                  <Typography sx={{ color: sev.color, fontSize: '.72rem', fontWeight: 800, letterSpacing: '.05em' }}>{sev.label}</Typography>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: .7, px: 1.5, py: .5, borderRadius: '6px', background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.18)' }}>
                  <Box sx={{ width: 6, height: 6, borderRadius: '50%', background: '#ef4444', boxShadow: '0 0 6px #ef4444', animation: 'bl 1s infinite', '@keyframes bl': { '0%,100%': { opacity: 1 }, '50%': { opacity: .2 } } }} />
                  <Typography sx={{ color: '#fca5a5', fontSize: '.68rem', fontWeight: 600 }}>Active Violation</Typography>
                </Box>
              </Box>
              <Typography sx={{ color: '#fff', fontSize: '1.8rem', fontWeight: 800, letterSpacing: '-1px', lineHeight: 1.1, mb: .8 }}>
                {alert.rule}
              </Typography>
              <Typography sx={{ color: 'rgba(255,255,255,0.3)', fontSize: '.88rem' }}>
                Alert #{alert.id} · {alert.camera}
              </Typography>
            </Box>
          </Box>

          <Box sx={{ mb: 3 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
              <Box sx={{ width: 6, height: 6, borderRadius: '50%', background: '#ef4444', animation: 'bl 1s infinite' }} />
              <Typography sx={{ color: 'rgba(255,255,255,0.25)', fontSize: '.7rem', letterSpacing: '.04em' }}>Live frame at time of detection</Typography>
            </Box>
            <FakeScreenshot camera={alert.camera} rule={alert.rule} personId={alert.personId} />
          </Box>

          <Box sx={{ display: 'flex', gap: 2 }}>
            {!markedFP ? (
              <Button variant="outlined" startIcon={<ThumbDownIcon sx={{ fontSize: 15 }} />}
                onClick={() => setMarkedFP(true)}
                sx={{ py: 1.3, px: 2.5, borderRadius: '10px', fontWeight: 600, fontSize: '.85rem', textTransform: 'none', color: '#fca5a5', border: '1px solid rgba(239,68,68,0.25)', background: 'rgba(239,68,68,0.07)', transition: 'all .2s', '&:hover': { background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.4)' } }}>
                Mark as False Positive
              </Button>
            ) : (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 2.5, py: 1.3, borderRadius: '10px', background: 'rgba(110,231,183,0.08)', border: '1px solid rgba(110,231,183,0.2)' }}>
                <Typography sx={{ color: '#6ee7b7', fontSize: '.85rem', fontWeight: 600 }}>✓ Marked as False Positive</Typography>
              </Box>
            )}
            <Button variant="outlined" onClick={() => navigate('/dashboard')}
              sx={{ py: 1.3, px: 2.5, borderRadius: '10px', fontWeight: 600, fontSize: '.85rem', textTransform: 'none', color: 'rgba(255,255,255,0.5)', border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.03)', transition: 'all .2s', '&:hover': { background: 'rgba(255,255,255,0.06)', borderColor: 'rgba(255,255,255,0.18)', color: '#fff' } }}>
              Back to Dashboard
            </Button>
            <Button variant="contained"
              sx={{ py: 1.3, px: 2.5, borderRadius: '10px', fontWeight: 600, fontSize: '.85rem', textTransform: 'none', background: 'linear-gradient(135deg, #6366f1, #7c3aed)', boxShadow: '0 4px 14px rgba(99,102,241,0.3)', border: '1px solid rgba(99,102,241,0.3)', '&:hover': { background: 'linear-gradient(135deg, #5558e8, #6d28d9)' } }}>
              Export Report
            </Button>
          </Box>
        </Box>

        {/* RIGHT */}
        <Box sx={{ width: 320, flexShrink: 0 }}>
          <Box sx={{ borderRadius: '16px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', overflow: 'hidden', mb: 2 }}>
            <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)', background: 'rgba(255,255,255,0.02)' }}>
              <Typography sx={{ color: '#fff', fontSize: '.85rem', fontWeight: 700 }}>Alert Details</Typography>
            </Box>
            {[
              { icon: <CameraAltIcon sx={{ fontSize: 15 }} />, label: 'Camera', value: alert.camera },
              { icon: <WarningAmberIcon sx={{ fontSize: 15 }} />, label: 'Rule Violated', value: alert.rule },
              { icon: <AccessTimeIcon sx={{ fontSize: 15 }} />, label: 'Time', value: alert.time },
              { icon: <PersonIcon sx={{ fontSize: 15 }} />, label: 'Person ID', value: alert.personId ? `ByteTrack #${alert.personId}` : 'Multiple persons' },
            ].map((item, i, arr) => (
              <Box key={i} sx={{ px: 3, py: 2, borderBottom: i < arr.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none', display: 'flex', alignItems: 'flex-start', gap: 2 }}>
                <Box sx={{ color: 'rgba(255,255,255,0.2)', mt: .1, flexShrink: 0 }}>{item.icon}</Box>
                <Box>
                  <Typography sx={{ color: 'rgba(255,255,255,0.2)', fontSize: '.65rem', textTransform: 'uppercase', letterSpacing: '.07em', mb: .3 }}>{item.label}</Typography>
                  <Typography sx={{ color: '#fff', fontSize: '.83rem', fontWeight: 500 }}>{item.value}</Typography>
                </Box>
              </Box>
            ))}
          </Box>

          <Box sx={{ borderRadius: '16px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', overflow: 'hidden', mb: 2 }}>
            <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)', background: 'rgba(255,255,255,0.02)' }}>
              <Typography sx={{ color: '#fff', fontSize: '.85rem', fontWeight: 700 }}>Detection Metrics</Typography>
            </Box>
            <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
              {[
                { label: 'Duration', value: `${alert.duration} frames`, c: '#fbbf24', pct: Math.min(100, (alert.duration / 60) * 100) },
                { label: 'Confidence', value: `${alert.confidence}%`, c: '#6ee7b7', pct: alert.confidence },
                { label: 'Zone', value: alert.zone, c: '#818cf8', pct: null },
              ].map((m, i) => (
                <Box key={i}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: .6 }}>
                    <Typography sx={{ color: 'rgba(255,255,255,0.3)', fontSize: '.72rem' }}>{m.label}</Typography>
                    <Typography sx={{ color: m.c, fontSize: '.72rem', fontWeight: 600 }}>{m.value}</Typography>
                  </Box>
                  {m.pct !== null && (
                    <Box sx={{ height: 4, borderRadius: 2, background: 'rgba(255,255,255,0.05)', overflow: 'hidden' }}>
                      <Box sx={{ height: '100%', width: `${m.pct}%`, background: `linear-gradient(90deg, ${m.c}80, ${m.c})`, borderRadius: 2, boxShadow: `0 0 8px ${m.c}60` }} />
                    </Box>
                  )}
                </Box>
              ))}
            </Box>
          </Box>

          <Box sx={{ borderRadius: '16px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', p: 3, mb: 2 }}>
            <Typography sx={{ color: 'rgba(255,255,255,0.2)', fontSize: '.65rem', textTransform: 'uppercase', letterSpacing: '.07em', mb: 1 }}>Description</Typography>
            <Typography sx={{ color: 'rgba(255,255,255,0.55)', fontSize: '.82rem', lineHeight: 1.65 }}>
              {alert.description} ByteTrack ID: {alert.personId}. Duration: {alert.duration} frames.
            </Typography>
          </Box>

          <Box sx={{ borderRadius: '16px', background: 'rgba(110,231,183,0.04)', border: '1px solid rgba(110,231,183,0.12)', p: 3 }}>
            <Typography sx={{ color: '#6ee7b7', fontSize: '.72rem', fontWeight: 700, mb: 1.5, letterSpacing: '.04em' }}>AUTOMATED ACTIONS</Typography>
            {['📸 Screenshot captured and stored', '📱 WhatsApp alert dispatched', '📊 Event logged to database', '🔔 Dashboard notification sent'].map((t, i) => (
              <Box key={i} sx={{ mb: i < 3 ? 1 : 0 }}>
                <Typography sx={{ color: 'rgba(255,255,255,0.45)', fontSize: '.77rem' }}>{t}</Typography>
              </Box>
            ))}
          </Box>
        </Box>
      </Box>
    </Box>
  )
}