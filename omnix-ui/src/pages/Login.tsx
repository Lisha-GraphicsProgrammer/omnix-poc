import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Box, TextField, Button, Typography, Alert, InputAdornment, IconButton } from '@mui/material'
import EmailIcon from '@mui/icons-material/Email'
import LockIcon from '@mui/icons-material/Lock'
import VisibilityIcon from '@mui/icons-material/Visibility'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff'

function VisionMetaphor() {
  const [step, setStep] = useState(0)
  const [typed, setTyped] = useState('')
  const [visible, setVisible] = useState(true)
  const fullText = 'Alert when worker without helmet enters loading zone'

  useEffect(() => {
    let i = 0
    const cycle = () => {
      setVisible(false)
      setTimeout(() => {
        const next = i % 4
        setStep(next)
        if (next === 0) setTyped('')
        setVisible(true)
        i++
      }, 400)
    }
    cycle()
    const t = setInterval(cycle, 3200)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (step !== 0) return
    let i = 0
    setTyped('')
    const t = setInterval(() => {
      setTyped(fullText.slice(0, i))
      i++
      if (i > fullText.length) clearInterval(t)
    }, 38)
    return () => clearInterval(t)
  }, [step])

  const steps = [
    { label: 'You type', color: '#818cf8' },
    { label: 'AI understands', color: '#a78bfa' },
    { label: 'Pipeline built', color: '#6ee7b7' },
    { label: 'Alert fired', color: '#f97316' },
  ]

  return (
    <Box sx={{
      borderRadius: '16px', overflow: 'hidden',
      border: '1px solid rgba(255,255,255,0.07)',
      background: 'rgba(0,0,0,0.4)',
      backdropFilter: 'blur(12px)',
      p: '20px 20px 18px', position: 'relative'
    }}>
      <Box sx={{
        position: 'absolute', inset: 0, pointerEvents: 'none', borderRadius: '16px',
        background: step === 0 ? 'radial-gradient(ellipse at 20% 50%, rgba(99,102,241,0.06) 0%, transparent 60%)'
          : step === 1 ? 'radial-gradient(ellipse at 80% 20%, rgba(167,139,250,0.06) 0%, transparent 60%)'
          : step === 2 ? 'radial-gradient(ellipse at 50% 80%, rgba(110,231,183,0.05) 0%, transparent 60%)'
          : 'radial-gradient(ellipse at 30% 30%, rgba(249,115,22,0.07) 0%, transparent 60%)',
        transition: 'background 1s ease'
      }} />

      <Box sx={{ display: 'flex', gap: 1, mb: 3, position: 'relative', zIndex: 1 }}>
        {steps.map((s, i) => (
          <Box key={i} sx={{ flex: 1 }}>
            <Box sx={{
              height: 2.5, borderRadius: 2, mb: .8,
              background: i <= step ? s.color : 'rgba(255,255,255,0.06)',
              transition: 'all .6s ease',
              boxShadow: i === step ? `0 0 12px ${s.color}90` : 'none',
              position: 'relative', overflow: 'hidden',
            }}>
              {i === step && (
                <Box sx={{ position: 'absolute', inset: 0, background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.5), transparent)', animation: 'shine 1.5s ease infinite', '@keyframes shine': { '0%': { transform: 'translateX(-100%)' }, '100%': { transform: 'translateX(200%)' } } }} />
              )}
            </Box>
            <Typography sx={{ color: i <= step ? s.color : 'rgba(255,255,255,0.18)', fontSize: '.6rem', fontWeight: i === step ? 700 : 400, transition: 'all .4s', letterSpacing: '.03em' }}>{s.label}</Typography>
          </Box>
        ))}
      </Box>

      <Box sx={{
        minHeight: 130, position: 'relative', zIndex: 1,
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(8px)',
        transition: 'opacity .35s ease, transform .35s ease'
      }}>
        {step === 0 && (
          <Box sx={{ p: '14px 16px', background: 'rgba(99,102,241,0.07)', border: '1px solid rgba(99,102,241,0.2)', borderRadius: '12px' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
              <Box sx={{ width: 5, height: 5, borderRadius: '50%', background: '#818cf8', boxShadow: '0 0 8px #818cf8' }} />
              <Typography sx={{ color: 'rgba(255,255,255,0.25)', fontSize: '.6rem', letterSpacing: '.07em', textTransform: 'uppercase' }}>Natural Language Input</Typography>
            </Box>
            <Typography sx={{ color: '#e2e8f0', fontSize: '.85rem', lineHeight: 1.65, minHeight: 56 }}>
              {typed}
              <Box component="span" sx={{ display: 'inline-block', width: '2px', height: '14px', background: '#818cf8', ml: '2px', animation: 'cur .7s infinite', '@keyframes cur': { '0%,100%': { opacity: 1 }, '50%': { opacity: 0 } }, verticalAlign: 'middle', boxShadow: '0 0 6px #818cf8' }} />
            </Typography>
            <Box sx={{ mt: 1.5, display: 'flex', alignItems: 'center', gap: 1 }}>
              <Box sx={{ flex: 1, height: 1, background: 'rgba(255,255,255,0.05)' }} />
              <Typography sx={{ color: 'rgba(255,255,255,0.15)', fontSize: '.6rem' }}>Sending to AI →</Typography>
            </Box>
          </Box>
        )}

        {step === 1 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: .9 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: .3 }}>
              <Box sx={{ width: 5, height: 5, borderRadius: '50%', background: '#a78bfa', boxShadow: '0 0 8px #a78bfa', animation: 'p .8s infinite', '@keyframes p': { '0%,100%': { transform: 'scale(1)' }, '50%': { transform: 'scale(1.5)' } } }} />
              <Typography sx={{ color: 'rgba(255,255,255,0.25)', fontSize: '.6rem', letterSpacing: '.07em', textTransform: 'uppercase' }}>Claude Haiku Processing</Typography>
              <Box sx={{ ml: 'auto', display: 'flex', gap: .4 }}>
                {[0, 1, 2].map(d => (
                  <Box key={d} sx={{ width: 4, height: 4, borderRadius: '50%', background: '#a78bfa', animation: `dot 1.2s ease ${d * .2}s infinite`, '@keyframes dot': { '0%,100%': { opacity: .2, transform: 'scale(.8)' }, '50%': { opacity: 1, transform: 'scale(1.2)' } } }} />
                ))}
              </Box>
            </Box>
            {[
              { k: 'Intent', v: 'Safety violation detection', c: '#818cf8' },
              { k: 'Objects', v: 'person · helmet', c: '#a78bfa' },
              { k: 'Logic', v: 'absence_in_association', c: '#c4b5fd' },
              { k: 'Zone', v: 'loading_zone (user_defined)', c: '#818cf8' },
            ].map((item, i) => (
              <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 2, px: '10px', py: '6px', background: 'rgba(99,102,241,0.05)', borderRadius: '8px', border: '1px solid rgba(99,102,241,0.1)', animation: `fi .35s ease ${i * .08}s both`, '@keyframes fi': { from: { opacity: 0, transform: 'translateX(-8px)' }, to: { opacity: 1, transform: 'none' } } }}>
                <Typography sx={{ color: 'rgba(255,255,255,0.22)', fontSize: '.62rem', minWidth: 44 }}>{item.k}</Typography>
                <Box sx={{ flex: 1, height: 1, background: 'rgba(255,255,255,0.04)' }} />
                <Typography sx={{ color: item.c, fontSize: '.73rem', fontWeight: 600, fontFamily: 'monospace' }}>{item.v}</Typography>
              </Box>
            ))}
          </Box>
        )}

        {step === 2 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: .8 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: .3 }}>
              <Box sx={{ width: 5, height: 5, borderRadius: '50%', background: '#6ee7b7', boxShadow: '0 0 8px #6ee7b7' }} />
              <Typography sx={{ color: 'rgba(255,255,255,0.25)', fontSize: '.6rem', letterSpacing: '.07em', textTransform: 'uppercase' }}>CV Pipeline Deployed</Typography>
            </Box>
            {[
              { icon: '📹', label: 'RTSP Stream Ingestion', status: 'active', c: '#6ee7b7', pct: 100 },
              { icon: '🔍', label: 'YOLOv8 Detection Engine', status: 'running', c: '#6ee7b7', pct: 100 },
              { icon: '🎯', label: 'ByteTrack ID Tracking', status: 'tracking', c: '#6ee7b7', pct: 85 },
              { icon: '📐', label: 'Zone Logic Check', status: 'checking', c: '#fbbf24', pct: 60 },
              { icon: '🔔', label: 'Alert Engine', status: 'ready', c: '#818cf8', pct: 35 },
            ].map((item, i) => (
              <Box key={i} sx={{ animation: `si .25s ease ${i * .07}s both`, '@keyframes si': { from: { opacity: 0, transform: 'translateX(8px)' }, to: { opacity: 1, transform: 'none' } } }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.2, mb: .35 }}>
                  <Box component="span" sx={{ fontSize: '.75rem' }}>{item.icon}</Box>
                  <Typography sx={{ color: 'rgba(255,255,255,0.5)', fontSize: '.72rem', flex: 1 }}>{item.label}</Typography>
                  <Typography sx={{ color: item.c, fontSize: '.6rem', fontWeight: 700 }}>{item.status}</Typography>
                </Box>
                <Box sx={{ height: 2, borderRadius: 1, background: 'rgba(255,255,255,0.05)', overflow: 'hidden', ml: 2.5, mb: .2 }}>
                  <Box sx={{ height: '100%', width: `${item.pct}%`, background: `linear-gradient(90deg, ${item.c}80, ${item.c})`, borderRadius: 1, transition: 'width 1.2s ease', boxShadow: `0 0 6px ${item.c}60` }} />
                </Box>
              </Box>
            ))}
          </Box>
        )}

        {step === 3 && (
          <Box sx={{ borderRadius: '12px', overflow: 'hidden', animation: 'ap .4s ease', '@keyframes ap': { from: { transform: 'scale(.95) translateY(8px)', opacity: 0 }, to: { transform: 'scale(1)', opacity: 1 } } }}>
            <Box sx={{ px: '14px', py: '10px', background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.25)', borderBottom: 'none', borderRadius: '12px 12px 0 0', display: 'flex', alignItems: 'center', gap: 1 }}>
              <Box sx={{ width: 7, height: 7, borderRadius: '50%', background: '#ef4444', boxShadow: '0 0 10px #ef4444', animation: 'bl .6s infinite', '@keyframes bl': { '0%,100%': { opacity: 1, boxShadow: '0 0 10px #ef4444' }, '50%': { opacity: .3, boxShadow: 'none' } } }} />
              <Typography sx={{ color: '#fca5a5', fontSize: '.75rem', fontWeight: 700, flex: 1 }}>VIOLATION DETECTED — HIGH SEVERITY</Typography>
              <Typography sx={{ color: 'rgba(255,255,255,0.3)', fontSize: '.6rem', fontFamily: 'monospace' }}>{new Date().toLocaleTimeString()}</Typography>
            </Box>
            <Box sx={{ p: '12px 14px', background: 'rgba(239,68,68,0.05)', border: '1px solid rgba(239,68,68,0.2)', borderTop: 'none', borderRadius: '0 0 12px 12px' }}>
              <Typography sx={{ color: 'rgba(255,255,255,0.5)', fontSize: '.75rem', lineHeight: 1.6, mb: 1.2 }}>
                <Box component="span" sx={{ color: '#fca5a5', fontWeight: 600 }}>Worker ID #27</Box> · No helmet · Loading zone entry · 59 frames
              </Typography>
              <Box sx={{ display: 'flex', gap: .8 }}>
                {[
                  { icon: '📸', text: 'Screenshot', c: 'rgba(255,255,255,0.04)' },
                  { icon: '📱', text: 'WhatsApp', c: 'rgba(99,102,241,0.08)' },
                  { icon: '📊', text: 'Logged', c: 'rgba(110,231,183,0.07)' },
                ].map((t, i) => (
                  <Box key={i} sx={{ px: 1, py: .4, background: t.c, border: '1px solid rgba(255,255,255,0.07)', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: .5, animation: `fb .3s ease ${i * .1}s both`, '@keyframes fb': { from: { opacity: 0, transform: 'translateY(4px)' }, to: { opacity: 1, transform: 'none' } } }}>
                    <Box component="span" sx={{ fontSize: '.7rem' }}>{t.icon}</Box>
                    <Typography sx={{ color: 'rgba(255,255,255,0.4)', fontSize: '.62rem' }}>{t.text}</Typography>
                  </Box>
                ))}
              </Box>
            </Box>
          </Box>
        )}
      </Box>
    </Box>
  )
}

const inp = {
  '& .MuiOutlinedInput-root': {
    borderRadius: '12px', background: 'rgba(255,255,255,0.06)',
    '& fieldset': { borderColor: 'rgba(255,255,255,0.18)', borderWidth: 1.5 },
    '&:hover fieldset': { borderColor: 'rgba(99,102,241,0.6)', borderWidth: 1.5 },
    '&.Mui-focused fieldset': { borderColor: '#6366f1', borderWidth: 2 },
    '&.Mui-focused': { background: 'rgba(99,102,241,0.06)', boxShadow: '0 0 0 4px rgba(99,102,241,0.1)' },
    transition: 'all .2s'
  },
  '& .MuiInputLabel-root': { color: 'rgba(255,255,255,0.4)', fontSize: '.88rem' },
  '& .MuiInputLabel-root.Mui-focused': { color: '#818cf8' },
  '& input': { color: '#fff', fontSize: '.95rem' },
  '& input:-webkit-autofill': {
    WebkitBoxShadow: '0 0 0 1000px #111116 inset !important',
    WebkitTextFillColor: '#fff !important',
    borderRadius: '12px',
    transition: 'background-color 5000s ease-in-out 0s',
  },
  '& input:-webkit-autofill:hover': { WebkitBoxShadow: '0 0 0 1000px #111116 inset !important' },
  '& input:-webkit-autofill:focus': { WebkitBoxShadow: '0 0 0 1000px #111116 inset !important' },
}
export default function Login() {
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')
  const [show, setShow] = useState(false)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const [mounted, setMounted] = useState(false)
  const nav = useNavigate()
  useEffect(() => { setTimeout(() => setMounted(true), 80) }, [])

  const login = () => {
    if (!email || !pw) { setErr('Please enter your credentials'); return }
    setLoading(true); setTimeout(() => nav('/dashboard'), 900)
  }

  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', background: '#08080a' }}>

      {/* LEFT */}
      <Box sx={{
        flex: 1, display: { xs: 'none', md: 'flex' },
        flexDirection: 'column', p: '36px 52px 48px',
        borderRight: '1px solid rgba(255,255,255,0.05)',
        position: 'relative', overflow: 'hidden',
        opacity: mounted ? 1 : 0, transform: mounted ? 'none' : 'translateX(-20px)',
        transition: 'all .7s ease'
      }}>
        <Box sx={{ position: 'absolute', width: 500, height: 500, borderRadius: '50%', top: -150, right: -100, background: 'radial-gradient(circle, rgba(99,102,241,0.07) 0%, transparent 65%)', pointerEvents: 'none' }} />
        <Box sx={{ position: 'absolute', width: 400, height: 400, borderRadius: '50%', bottom: -100, left: -50, background: 'radial-gradient(circle, rgba(139,92,246,0.05) 0%, transparent 65%)', pointerEvents: 'none' }} />

        {/* NAV */}
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 7 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <Box sx={{ width: 34, height: 34, borderRadius: '9px', background: 'linear-gradient(135deg, #6366f1, #8b5cf6)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 20px rgba(99,102,241,0.4), 0 0 0 1px rgba(255,255,255,0.1)' }}>
              <svg width="19" height="19" viewBox="0 0 24 24" fill="none">
                <ellipse cx="12" cy="12" rx="10" ry="6.5" stroke="white" strokeWidth="1.5"/>
                <circle cx="12" cy="12" r="3.5" fill="white"/>
                <circle cx="13.5" cy="10.5" r="1.4" fill="#6366f1"/>
              </svg>
            </Box>
            <Typography sx={{ color: '#fff', fontWeight: 700, fontSize: '1.05rem', letterSpacing: '-.2px' }}>OMNIX</Typography>
            <Box sx={{ px: 1.2, py: .3, borderRadius: '5px', background: 'rgba(99,102,241,0.12)', border: '1px solid rgba(99,102,241,0.25)' }}>
              <Typography sx={{ color: '#a5b4fc', fontSize: '.58rem', fontWeight: 700, letterSpacing: '.08em' }}>ENTERPRISE</Typography>
            </Box>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            {['SOC 2', 'ISO 27001', 'GDPR'].map(b => (
              <Box key={b} sx={{ px: 1.3, py: .35, borderRadius: '5px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}>
                <Typography sx={{ color: 'rgba(255,255,255,0.28)', fontSize: '.6rem' }}>✓ {b}</Typography>
              </Box>
            ))}
          </Box>
        </Box>

        {/* HEADLINE */}
        <Box sx={{ mb: 4 }}>
          <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 1, px: 1.5, py: .5, borderRadius: '20px', background: 'rgba(99,102,241,0.1)', border: '1px solid rgba(99,102,241,0.2)', mb: 2.5, width: 'fit-content' }}>
            <Box sx={{ width: 5, height: 5, borderRadius: '50%', background: '#818cf8', boxShadow: '0 0 6px rgba(129,140,248,0.8)' }} />
            <Typography sx={{ color: '#a5b4fc', fontSize: '.7rem', fontWeight: 600, letterSpacing: '.04em' }}>AI-Powered Construction Safety Platform</Typography>
          </Box>
          <Typography sx={{ fontSize: '3.2rem', fontWeight: 900, lineHeight: 1.1, letterSpacing: '-2px', color: '#fff', mb: 2 }}>
            Vision AI that<br />
            <Box component="span" sx={{ background: 'linear-gradient(135deg, #818cf8 0%, #c4b5fd 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text' }}>
              speaks English
            </Box>
          </Typography>
          <Typography sx={{ color: 'rgba(255,255,255,0.35)', fontSize: '.9rem', lineHeight: 1.8, maxWidth: 400 }}>
            Type what you want to detect. OMNIX converts your instruction into a production-grade CV pipeline instantly.
          </Typography>
        </Box>

        {/* METAPHOR */}
        <Box sx={{ mb: 4 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
            <Box sx={{ width: 6, height: 6, borderRadius: '50%', background: '#818cf8', boxShadow: '0 0 6px rgba(129,140,248,0.6)' }} />
            <Typography sx={{ color: 'rgba(255,255,255,0.25)', fontSize: '.7rem', letterSpacing: '.04em' }}>See how OMNIX works — live demo</Typography>
          </Box>
          <VisionMetaphor />
        </Box>

        {/* STATS */}
        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 1.2 }}>
          {[
            { val: '99.9%', label: 'Uptime', c: '#818cf8' },
            { val: '<3s', label: 'Latency', c: '#a78bfa' },
            { val: '100+', label: 'Cameras', c: '#c4b5fd' },
            { val: '7', label: 'Violations*', c: '#6ee7b7' },
          ].map((s, i) => (
            <Box key={i} sx={{ p: '14px 12px', borderRadius: '10px', background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.05)', transition: 'all .2s', '&:hover': { background: 'rgba(99,102,241,0.06)', borderColor: 'rgba(99,102,241,0.15)' } }}>
              <Typography sx={{ color: s.c, fontSize: '1.4rem', fontWeight: 800, letterSpacing: '-1px', lineHeight: 1, mb: .4 }}>{s.val}</Typography>
              <Typography sx={{ color: 'rgba(255,255,255,0.2)', fontSize: '.6rem', textTransform: 'uppercase', letterSpacing: '.07em' }}>{s.label}</Typography>
            </Box>
          ))}
        </Box>
      </Box>

      {/* RIGHT */}
      <Box sx={{
        width: { xs: '100%', md: '500px' }, flexShrink: 0,
        display: 'flex', flexDirection: 'column',
        background: '#0d0d10', borderLeft: '1px solid rgba(255,255,255,0.05)',
        opacity: mounted ? 1 : 0, transform: mounted ? 'none' : 'translateY(14px)',
        transition: 'all .7s ease .1s'
      }}>
        <Box sx={{ px: 5, py: 2.5, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Box sx={{ width: 7, height: 7, borderRadius: '50%', background: '#22c55e', boxShadow: '0 0 8px rgba(34,197,94,0.6)', animation: 'pg 2s infinite', '@keyframes pg': { '0%,100%': { opacity: 1 }, '50%': { opacity: .3 } } }} />
            <Typography sx={{ color: 'rgba(255,255,255,0.2)', fontSize: '.72rem' }}>All systems operational</Typography>
          </Box>
          <Box sx={{ px: 1.5, py: .35, borderRadius: '5px', background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.15)' }}>
            <Typography sx={{ color: 'rgba(34,197,94,0.65)', fontSize: '.58rem', fontWeight: 700, letterSpacing: '.07em' }}>LIVE</Typography>
          </Box>
        </Box>

        <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', p: '48px 52px' }}>
          <Box sx={{ width: '100%', maxWidth: 360 }}>
            <Box sx={{ mb: 6 }}>
              <Typography sx={{ color: '#fff', fontSize: '2.1rem', fontWeight: 800, letterSpacing: '-1px', lineHeight: 1.1, mb: 1.5 }}>Welcome back</Typography>
              <Typography sx={{ color: 'rgba(255,255,255,0.28)', fontSize: '.88rem', lineHeight: 1.6 }}>Sign in to access your OMNIX monitoring dashboard</Typography>
            </Box>

            {err && (
              <Alert severity="error" sx={{ mb: 3, borderRadius: '10px', fontSize: '.84rem', background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)', color: '#fca5a5', '& .MuiAlert-icon': { color: '#f87171' } }}>
                {err}
              </Alert>
            )}

            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
              <TextField fullWidth label="Work email" variant="outlined"
                value={email} onChange={e => setEmail(e.target.value)}
                slotProps={{ input: { startAdornment: <InputAdornment position="start"><EmailIcon sx={{ color: 'rgba(255,255,255,0.3)', fontSize: 17 }} /></InputAdornment> } }}
                sx={inp} />

              <TextField fullWidth label="Password" variant="outlined"
                type={show ? 'text' : 'password'}
                value={pw} onChange={e => setPw(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && login()}
                slotProps={{
                  input: {
                    startAdornment: <InputAdornment position="start"><LockIcon sx={{ color: 'rgba(255,255,255,0.3)', fontSize: 17 }} /></InputAdornment>,
                    endAdornment: <InputAdornment position="end">
                      <IconButton onClick={() => setShow(!show)} edge="end" size="small">
                        {show ? <VisibilityOffIcon sx={{ color: 'rgba(255,255,255,0.3)', fontSize: 17 }} /> : <VisibilityIcon sx={{ color: 'rgba(255,255,255,0.3)', fontSize: 17 }} />}
                      </IconButton>
                    </InputAdornment>
                  }
                }}
                sx={inp} />

              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mt: -.5 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, cursor: 'pointer' }}>
                  <Box sx={{ width: 15, height: 15, borderRadius: '4px', border: '1.5px solid rgba(255,255,255,0.2)' }} />
                  <Typography sx={{ color: 'rgba(255,255,255,0.25)', fontSize: '.78rem' }}>Remember me</Typography>
                </Box>
                <Typography sx={{ color: 'rgba(99,102,241,0.6)', fontSize: '.8rem', cursor: 'pointer', '&:hover': { color: '#818cf8' }, transition: 'color .15s' }}>
                  Forgot password?
                </Typography>
              </Box>

              <Button fullWidth variant="contained" onClick={login} disabled={loading}
                sx={{
                  mt: .5, py: 1.9, borderRadius: '12px',
                  fontWeight: 600, fontSize: '.95rem', textTransform: 'none', color: '#fff',
                  background: loading ? 'rgba(99,102,241,0.2)' : 'linear-gradient(135deg, #6366f1 0%, #7c3aed 100%)',
                  boxShadow: loading ? 'none' : '0 4px 20px rgba(99,102,241,0.28), inset 0 1px 0 rgba(255,255,255,0.12)',
                  border: '1px solid rgba(99,102,241,0.3)', transition: 'all .2s ease',
                  '&:hover': { background: 'linear-gradient(135deg, #5558e8 0%, #6d28d9 100%)', boxShadow: '0 8px 28px rgba(99,102,241,0.4)', transform: 'translateY(-1px)' },
                  '&:active': { transform: 'none' },
                  '&.Mui-disabled': { background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.15)', border: '1px solid rgba(255,255,255,0.04)', boxShadow: 'none' }
                }}>
                {loading ? (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                    <Box sx={{ width: 16, height: 16, borderRadius: '50%', border: '2px solid rgba(255,255,255,0.2)', borderTopColor: '#fff', animation: 'sp 1s linear infinite', '@keyframes sp': { '100%': { transform: 'rotate(360deg)' } } }} />
                    Signing in...
                  </Box>
                ) : 'Continue →'}
              </Button>
            </Box>

            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, my: 3.5 }}>
              <Box sx={{ flex: 1, height: '1px', background: 'rgba(255,255,255,0.07)' }} />
              <Typography sx={{ color: 'rgba(255,255,255,0.18)', fontSize: '.72rem' }}>or</Typography>
              <Box sx={{ flex: 1, height: '1px', background: 'rgba(255,255,255,0.07)' }} />
            </Box>

            <Button fullWidth variant="outlined"
              sx={{ py: 1.6, borderRadius: '12px', fontWeight: 500, fontSize: '.88rem', textTransform: 'none', color: 'rgba(255,255,255,0.5)', border: '1.5px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.03)', transition: 'all .2s', '&:hover': { background: 'rgba(255,255,255,0.06)', borderColor: 'rgba(255,255,255,0.2)', color: 'rgba(255,255,255,0.8)' } }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <svg width="16" height="16" viewBox="0 0 24 24">
                  <rect x="3" y="3" width="8" height="8" rx="1" fill="#4285F4"/>
                  <rect x="13" y="3" width="8" height="8" rx="1" fill="#EA4335"/>
                  <rect x="3" y="13" width="8" height="8" rx="1" fill="#34A853"/>
                  <rect x="13" y="13" width="8" height="8" rx="1" fill="#FBBC05"/>
                </svg>
                Continue with SSO
              </Box>
            </Button>

            <Box sx={{ mt: 5, pt: 4, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              <Box sx={{ display: 'flex', justifyContent: 'center', gap: 3, mb: 2 }}>
                {[{ icon: '🔐', text: 'End-to-end encrypted' }, { icon: '🛡️', text: 'Zero-trust security' }].map((item, i) => (
                  <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: .7 }}>
                    <Box component="span" sx={{ fontSize: '.78rem' }}>{item.icon}</Box>
                    <Typography sx={{ color: 'rgba(255,255,255,0.25)', fontSize: '.72rem' }}>{item.text}</Typography>
                  </Box>
                ))}
              </Box>
              <Typography sx={{ color: 'rgba(255,255,255,0.15)', fontSize: '.68rem', textAlign: 'center' }}>
                © 2026 NGXP OMNIX · Enterprise Vision Intelligence Platform
              </Typography>
            </Box>
          </Box>
        </Box>
      </Box>
    </Box>
  )
}