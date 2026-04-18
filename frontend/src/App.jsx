import { useState, useEffect, useRef, useCallback } from 'react'
import Dashboard from './components/Dashboard.jsx'
import HITLPanel from './components/HITLPanel.jsx'
import AgentFeed from './components/AgentFeed.jsx'
import CallMonitor from './components/CallMonitor.jsx'
import ExcelSync from './components/ExcelSync.jsx'

const BASE = window.location.origin.includes('localhost')
  ? 'http://localhost:8000'
  : window.location.origin

export default function App() {
  const [dashData, setDashData]   = useState(null)
  const [feedItems, setFeedItems] = useState([])
  const [activeCall, setActiveCall] = useState(null)       // {client, sid}
  const [transcript, setTranscript] = useState([])
  const [batchRunning, setBatchRunning] = useState(false)
  const [excelRows, setExcelRows]  = useState([])
  const [activeTab, setActiveTab]  = useState('dashboard')
  const sseRef = useRef(null)

  const addFeed = useCallback((type, msg, raw = {}) => {
    setFeedItems(prev => [{
      id: Date.now() + Math.random(),
      type,
      msg,
      time: new Date().toLocaleTimeString('en', { hour12: false }),
      ...raw
    }, ...prev].slice(0, 200))
  }, [])

  const loadDashboard = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/dashboard/data`)
      const d = await r.json()
      setDashData(d)
      setBatchRunning(d.batch_running || false)
      if (d.clients) {
        setExcelRows(d.clients.map(c => ({
          client: c.client,
          amount: c.total_amount,
          risk: c.max_risk_score,
          risk_label: c.risk_label || (c.max_risk_score >= 70 ? 'High' : c.max_risk_score >= 40 ? 'Medium' : 'Low'),
          last_action: c.last_action || '—',
          updated: new Date().toLocaleTimeString()
        })))
      }
    } catch (e) {
      addFeed('error', `Backend unreachable: ${e.message}`)
    }
  }, [addFeed])

  const connectSSE = useCallback(() => {
    if (sseRef.current) sseRef.current.close()
    const es = new EventSource(`${BASE}/events`)
    sseRef.current = es

    es.onmessage = (e) => {
      const ev = JSON.parse(e.data)
      if (ev.type === 'ping' || ev.type === 'connected') return

      if (ev.type === 'batch_start') {
        setBatchRunning(true)
        addFeed('system', '▶ Autonomous batch initiated', ev)
      }
      else if (ev.type === 'batch_progress') {
        addFeed('info', ev.message || 'Processing…', ev)
      }
      else if (ev.type === 'batch_complete') {
        setBatchRunning(false)
        addFeed('success', `✓ Batch complete — ${ev.processed} processed, ${ev.errors} errors`, ev)
        setTimeout(loadDashboard, 800)
      }
      else if (ev.type === 'client_processed') {
        addFeed('action', `${ev.client} → ${ev.decision || '?'} [${ev.risk_label || ''}]`, ev)
        setExcelRows(prev => prev.map(r =>
          r.client === ev.client
            ? { ...r, last_action: ev.decision, risk_label: ev.risk_label, updated: new Date().toLocaleTimeString(), flash: true }
            : r
        ))
        setTimeout(() => setExcelRows(prev => prev.map(r => ({ ...r, flash: false }))), 1500)
      }
      else if (ev.type === 'client_error') {
        addFeed('error', `${ev.client}: ${ev.error}`, ev)
      }
      else if (ev.type === 'call_started') {
        setActiveCall({ client: ev.client, sid: ev.call_sid })
        setTranscript([])
        addFeed('call', `📞 Call started → ${ev.client}`, ev)
        setActiveTab('call')
      }
      else if (ev.type === 'transcript') {
        setTranscript(prev => [...prev, { role: ev.role, content: ev.content, time: new Date().toLocaleTimeString() }])
      }
      else if (ev.type === 'call_ended') {
        setActiveCall(null)
        addFeed('info', `📵 Call ended — ${ev.client}`, ev)
        setTimeout(loadDashboard, 1000)
      }
      else if (ev.type === 'call_outcome') {
        const msg = ev.payment_commitment
          ? `✓ ${ev.client} committed → ${ev.payment_commitment}`
          : `${ev.client} — outcome: ${ev.outcome}`
        addFeed('success', msg, ev)
      }
      else if (ev.type === 'hitl_resolved') {
        addFeed('hitl', `HITL resolved: ${ev.checkpoint_id}`, ev)
        setTimeout(loadDashboard, 500)
      }
      else if (ev.type === 'agent_action') {
        addFeed('agent', ev.message, ev)
      }
    }

    es.onerror = () => {
      addFeed('error', 'SSE disconnected — reconnecting…')
      setTimeout(connectSSE, 3000)
    }
  }, [addFeed, loadDashboard])

  useEffect(() => {
    loadDashboard()
    connectSSE()
    const interval = setInterval(loadDashboard, 30000)
    return () => {
      clearInterval(interval)
      if (sseRef.current) sseRef.current.close()
    }
  }, [loadDashboard, connectSSE])

  const triggerBatch = async () => {
    if (batchRunning) return
    try {
      await fetch(`${BASE}/batch/run`, { method: 'POST' })
    } catch (e) {
      addFeed('error', `Batch trigger failed: ${e.message}`)
    }
  }

  const approveHITL = async (id, action) => {
    try {
      await fetch(`${BASE}/hitl/approve/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ option_id: action, approved_by: 'dashboard' })
      })
      loadDashboard()
    } catch (e) {
      addFeed('error', `HITL action failed: ${e.message}`)
    }
  }

  const TABS = [
    { id: 'dashboard', label: 'Portfolio', icon: '◈' },
    { id: 'hitl',      label: 'HITL',      icon: '⚠', badge: Array.isArray(dashData?.hitl_pending) ? dashData.hitl_pending.length : (dashData?.hitl_pending ? Object.keys(dashData.hitl_pending).length : 0) },
    { id: 'feed',      label: 'Agent Feed', icon: '⟳' },
    { id: 'call',      label: 'Call',       icon: '◉', live: !!activeCall },
    { id: 'excel',     label: 'Excel Sync', icon: '⊞' },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden', background: 'var(--bg)' }}>
      {/* TOP BAR */}
      <header style={{
        display: 'flex', alignItems: 'center', gap: 24,
        padding: '0 24px', height: 52,
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg1)',
        flexShrink: 0,
        position: 'relative',
      }}>
        {/* scan line effect */}
        <div style={{
          position: 'absolute', inset: 0, pointerEvents: 'none',
          background: 'linear-gradient(to bottom, transparent 40%, rgba(0,229,180,0.015) 50%, transparent 60%)',
          animation: 'scan-line 8s linear infinite',
          zIndex: 0,
        }} />

        <div style={{
          fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 800,
          letterSpacing: '-0.03em', color: 'var(--teal)', zIndex: 1
        }}>
          Debt<span style={{ color: 'var(--text3)' }}>Pilot</span>
        </div>

        <div style={{ color: 'var(--text3)', fontSize: 11, borderLeft: '1px solid var(--border)', paddingLeft: 16, zIndex: 1 }}>
          AUTONOMOUS AR COLLECTIONS
        </div>

        {/* NAV TABS */}
        <nav style={{ display: 'flex', gap: 4, marginLeft: 16, zIndex: 1 }}>
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '4px 12px', borderRadius: 'var(--r)',
                background: activeTab === tab.id ? 'var(--bg3)' : 'transparent',
                border: activeTab === tab.id ? '1px solid var(--border2)' : '1px solid transparent',
                color: activeTab === tab.id ? 'var(--text)' : 'var(--text3)',
                fontSize: 12, fontFamily: 'var(--font-mono)',
                transition: 'all 0.15s',
                position: 'relative',
              }}
            >
              <span style={{
                color: tab.live ? 'var(--violet)' : activeTab === tab.id ? 'var(--teal)' : 'var(--text3)',
                animation: tab.live ? 'pulse-dot 1s infinite' : 'none',
              }}>{tab.icon}</span>
              {tab.label}
              {tab.badge > 0 && (
                <span style={{
                  background: 'var(--red)', color: '#fff',
                  borderRadius: 10, fontSize: 9, fontWeight: 700,
                  padding: '1px 5px', minWidth: 16, textAlign: 'center',
                }}>
                  {tab.badge}
                </span>
              )}
            </button>
          ))}
        </nav>

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12, zIndex: 1 }}>
          {activeCall && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--violet)', fontSize: 11 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--violet)', display: 'inline-block', animation: 'pulse-dot 1s infinite' }} />
              LIVE: {activeCall.client}
            </div>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{
              width: 7, height: 7, borderRadius: '50%',
              background: batchRunning ? 'var(--amber)' : 'var(--text3)',
              display: 'inline-block',
              animation: batchRunning ? 'pulse-dot 1s infinite' : 'none',
            }} />
            <span style={{ color: 'var(--text3)', fontSize: 11 }}>
              {batchRunning ? 'RUNNING' : 'IDLE'}
            </span>
          </div>
        </div>
      </header>

      {/* MAIN CONTENT */}
      <main style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>
        {activeTab === 'dashboard' && (
          <Dashboard data={dashData} batchRunning={batchRunning} onTriggerBatch={triggerBatch} />
        )}
        {activeTab === 'hitl' && (
          <HITLPanel pending={dashData?.hitl_pending || []} onApprove={approveHITL} decisionLog={dashData?.lineage_log || []} />
        )}
        {activeTab === 'feed' && (
          <AgentFeed items={feedItems} batchRunning={batchRunning} />
        )}
        {activeTab === 'call' && (
          <CallMonitor activeCall={activeCall} transcript={transcript} feedItems={feedItems} />
        )}
        {activeTab === 'excel' && (
          <ExcelSync rows={excelRows} lastBatch={dashData?.last_batch} />
        )}
      </main>
    </div>
  )
}
