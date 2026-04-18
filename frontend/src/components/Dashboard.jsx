import { useState } from 'react'

// ── Decision logic mirror ─────────────────────────────────────────────────────
// Mirrors action_agent.py + risk_agent.py deterministically so the UI can
// preview EXACTLY what the agent will do before the batch even runs.

function deriveAgentPlan(client) {
  const score   = client.max_risk_score  || 0
  const days    = client.max_days_overdue || 0
  const amount  = client.total_amount     || 0
  const action  = (client.last_action || client.next_action || '').toLowerCase()
  const hasContact = client.has_contact !== false  // assume true unless told otherwise

  // Gate 1 – legal/disputed always blocked
  if (action.includes('legal') || action.includes('disputed')) {
    return { decision: 'blocked', reason: 'Legal/disputed — protected, agent cannot override', color: 'var(--text3)', icon: '🔒', priority: 0 }
  }

  // Gate 2 – missing contact
  if (!hasContact || action === 'resolve_contact_details') {
    return { decision: 'hitl', reason: 'Missing contact info — agent will pause for human input', color: 'var(--red)', icon: '⚠', priority: 1 }
  }

  // HITL triggers
  if (score >= 70 && days > 45 && amount > 500000) {
    return { decision: 'hitl', reason: `High-stakes overdue (₹${fmtAmt(amount)}, ${days}d, score ${score}) → human review`, color: 'var(--red)', icon: '⚠', priority: 1 }
  }

  // Escalation
  if (action.includes('escalate') || (score >= 85 && days > 75)) {
    return { decision: 'escalate', reason: `Score ${score} + ${days}d overdue → legal escalation flag`, color: 'var(--red)', icon: '⚖', priority: 2 }
  }

  // Call triggers
  if (action.includes('schedule_call') || action.includes('send_call') ||
      (score >= 70 && days > 60) || (score >= 60 && days > 75)) {
    const tone = score >= 80 ? 'urgent' : 'firm'
    return { decision: 'call', reason: `Score ${score}, ${days}d overdue → live call, ${tone} tone`, color: 'var(--violet)', icon: '📞', priority: 3 }
  }

  // Email triggers
  if (action.includes('email') || action.includes('notice') || action.includes('reminder') ||
      score >= 40 || days > 30) {
    const tone = days > 60 ? 'urgent' : days > 30 ? 'firm' : 'friendly'
    return { decision: 'email', reason: `Score ${score}, ${days}d overdue → email, ${tone} tone`, color: 'var(--teal)', icon: '✉', priority: 4 }
  }

  // Low risk — monitor
  return { decision: 'monitor', reason: `Score ${score}, ${days}d — within acceptable range, no action`, color: 'var(--text3)', icon: '·', priority: 5 }
}

function deriveTone(client) {
  const score = client.max_risk_score  || 0
  const days  = client.max_days_overdue || 0
  const count = client.contact_count   || 0

  if (client.dispute_flag) return { label: 'Dispute Acknowledgment', color: 'var(--amber)' }
  if (count === 0) {
    if (days > 60) return { label: 'Urgent',    color: 'var(--red)'    }
    if (days > 30) return { label: 'Firm',       color: 'var(--amber)'  }
    return                { label: 'Friendly',   color: 'var(--teal)'   }
  }
  if (count === 1) return { label: 'Urgent',     color: 'var(--amber)'  }
  return score >= 70
    ? { label: 'Final Notice', color: 'var(--red)' }
    : { label: 'Urgent',       color: 'var(--amber)' }
}

function deriveRiskFlags(client) {
  const flags = []
  const score = client.max_risk_score  || 0
  const days  = client.max_days_overdue || 0
  if (!client.has_contact && client.has_contact !== undefined)
    flags.push({ label: 'MISSING CONTACT', color: 'var(--red)' })
  if (client.dispute_flag)
    flags.push({ label: 'ACTIVE DISPUTE',  color: 'var(--red)' })
  if (days > 60 && score < 40)
    flags.push({ label: 'SCORE CONTRADICTION', color: 'var(--amber)' })
  if ((client.contact_count || 0) >= 3)
    flags.push({ label: 'REPEATED CONTACT', color: 'var(--amber)' })
  if (days > 75)
    flags.push({ label: 'CRITICAL OVERDUE', color: 'var(--red)' })
  return flags
}

// ── Formatters ────────────────────────────────────────────────────────────────
function fmtAmt(v) {
  if (!v && v !== 0) return '—'
  if (v >= 100000) return `${(v / 100000).toFixed(1)}L`
  if (v >= 1000)   return `${(v / 1000).toFixed(0)}K`
  return String(v)
}

const riskColor = (score) => score >= 70 ? 'var(--red)' : score >= 40 ? 'var(--amber)' : 'var(--teal)'

// ── Sub-components ────────────────────────────────────────────────────────────
function StatBox({ value, label, color = 'var(--teal)', sub }) {
  return (
    <div style={{
      background: 'var(--bg2)', border: '1px solid var(--border)',
      borderRadius: 'var(--r)', padding: '14px 16px',
    }}>
      <div style={{ fontFamily: 'var(--font-display)', fontSize: 26, fontWeight: 700, color, letterSpacing: '-0.02em', lineHeight: 1 }}>
        {value}
      </div>
      <div style={{ color: 'var(--text3)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em', marginTop: 4 }}>
        {label}
      </div>
      {sub && <div style={{ color: 'var(--text3)', fontSize: 9, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function DecisionBadge({ plan }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 9px', borderRadius: 4,
      fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
      background: `${plan.color}18`, color: plan.color,
      border: `1px solid ${plan.color}35`,
    }}>
      <span>{plan.icon}</span> {plan.decision}
    </span>
  )
}

function ScoreBar({ score, width = 64 }) {
  const color = riskColor(score)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width, height: 3, background: 'var(--bg3)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${score}%`, height: '100%', background: color, borderRadius: 2 }} />
      </div>
      <span style={{ color, fontSize: 10, fontWeight: 600, minWidth: 18 }}>{score}</span>
    </div>
  )
}

// ── CLIENT DETAIL DRAWER ──────────────────────────────────────────────────────
function ClientDrawer({ client, onClose }) {
  const plan  = deriveAgentPlan(client)
  const tone  = deriveTone(client)
  const flags = deriveRiskFlags(client)
  const score = client.max_risk_score   || 0
  const days  = client.max_days_overdue || 0

  const SCORING_BREAKDOWN = [
    { label: 'Days Overdue Component',  max: 40, value: days > 75 ? 40 : days > 60 ? 32 : days > 45 ? 24 : days > 30 ? 16 : days > 15 ? 8 : 3, desc: `${days} days → ${days > 75 ? '40' : days > 60 ? '32' : days > 45 ? '24' : days > 30 ? '16' : days > 15 ? '8' : '3'} pts` },
    { label: 'Dispute Flag',            max: 35, value: client.dispute_flag ? 35 : 0, desc: client.dispute_flag ? '+35 pts (active dispute)' : '0 pts (no dispute)' },
    { label: 'Missing Contact Penalty', max: 15, value: client.has_contact === false ? 15 : 0, desc: client.has_contact === false ? '+15 pts (no contact)' : '0 pts (contact known)' },
    { label: 'Repeated Contact',        max: 5,  value: (client.contact_count || 0) >= 3 ? 5 : 0, desc: (client.contact_count || 0) >= 3 ? '+5 pts (3+ contacts)' : '0 pts' },
  ]

  const DECISION_TREE = [
    { step: 1, condition: 'Is next_action = legal/disputed?',   result: 'BLOCK → no action',  met: plan.decision === 'blocked' },
    { step: 2, condition: 'Missing contact name?',              result: 'HITL pause',          met: plan.decision === 'hitl' && !client.has_contact },
    { step: 3, condition: 'High-stakes overdue?',               result: 'HITL pause',          met: plan.decision === 'hitl' },
    { step: 4, condition: 'score≥85 AND days>75?',              result: 'Escalate to legal',   met: plan.decision === 'escalate' },
    { step: 5, condition: 'score≥70 AND days>60? / schedule_call?', result: 'Place call',     met: plan.decision === 'call' },
    { step: 6, condition: 'score≥40 OR days>30?',               result: 'Send email',          met: plan.decision === 'email' },
    { step: 7, condition: 'None of the above',                  result: 'Monitor only',        met: plan.decision === 'monitor' },
  ]

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 100,
      display: 'flex', alignItems: 'flex-start', justifyContent: 'flex-end',
    }}>
      {/* Backdrop */}
      <div onClick={onClose} style={{
        position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)',
        backdropFilter: 'blur(2px)',
      }} />

      {/* Drawer */}
      <div style={{
        position: 'relative', zIndex: 1,
        width: 520, height: '100%', overflowY: 'auto',
        background: 'var(--bg1)', borderLeft: '1px solid var(--border)',
        animation: 'slide-in-right 0.2s ease both',
      }}>
        <style>{`
          @keyframes slide-in-right {
            from { transform: translateX(40px); opacity: 0; }
            to   { transform: translateX(0);    opacity: 1; }
          }
        `}</style>

        {/* Header */}
        <div style={{
          padding: '20px 24px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg2)',
          position: 'sticky', top: 0, zIndex: 2,
        }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
            <div>
              <div style={{
                fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 800,
                letterSpacing: '-0.02em', color: 'var(--text)',
              }}>
                {client.client}
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                <DecisionBadge plan={plan} />
                <span style={{ color: tone.color, fontSize: 10, fontWeight: 600 }}>
                  TONE: {tone.label.toUpperCase()}
                </span>
                {flags.map(f => (
                  <span key={f.label} style={{
                    padding: '2px 7px', borderRadius: 3, fontSize: 8, fontWeight: 700,
                    letterSpacing: '0.1em', background: `${f.color}18`, color: f.color,
                    border: `1px solid ${f.color}30`,
                  }}>{f.label}</span>
                ))}
              </div>
            </div>
            <button onClick={onClose} style={{
              background: 'transparent', border: '1px solid var(--border)',
              color: 'var(--text3)', borderRadius: 'var(--r)', padding: '6px 10px',
              fontFamily: 'var(--font-mono)', fontSize: 11, cursor: 'pointer',
            }}>✕</button>
          </div>
        </div>

        <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 24 }}>

          {/* AGENT DECISION */}
          <section>
            <SectionLabel>Agent Decision Preview</SectionLabel>
            <div style={{
              background: `${plan.color}0c`, border: `1px solid ${plan.color}35`,
              borderRadius: 'var(--r2)', padding: '14px 16px',
              borderLeft: `3px solid ${plan.color}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 20 }}>{plan.icon}</span>
                <span style={{
                  fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 700,
                  color: plan.color, textTransform: 'capitalize',
                }}>
                  {plan.decision === 'hitl' ? 'Pause for Human Review' :
                   plan.decision === 'call' ? 'Place Live Call' :
                   plan.decision === 'email' ? 'Send Email' :
                   plan.decision === 'escalate' ? 'Escalate to Legal' :
                   plan.decision === 'blocked' ? 'Blocked' : 'Monitor Only'}
                </span>
              </div>
              <div style={{ color: 'var(--text2)', fontSize: 12, lineHeight: 1.65 }}>
                {plan.reason}
              </div>
            </div>
          </section>

          {/* KEY METRICS */}
          <section>
            <SectionLabel>Risk Inputs</SectionLabel>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
              <MetricBox label="Outstanding" value={`₹${fmtAmt(client.total_amount)}`} color="var(--teal)" />
              <MetricBox label="Days Overdue" value={`${days}d`} color={days > 60 ? 'var(--red)' : days > 30 ? 'var(--amber)' : 'var(--teal)'} />
              <MetricBox label="Priority Score" value={(client.priority_score || 0).toFixed(0)} color="var(--violet)" />
            </div>
          </section>

          {/* RISK SCORE BREAKDOWN */}
          <section>
            <SectionLabel>Risk Score Breakdown — {score}/100</SectionLabel>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {SCORING_BREAKDOWN.map(row => (
                <div key={row.label} style={{
                  display: 'grid', gridTemplateColumns: '1fr 160px 36px',
                  gap: 10, alignItems: 'center',
                  padding: '8px 12px',
                  background: 'var(--bg2)', borderRadius: 'var(--r)',
                  border: '1px solid var(--border)',
                }}>
                  <div>
                    <div style={{ color: 'var(--text2)', fontSize: 11 }}>{row.label}</div>
                    <div style={{ color: 'var(--text3)', fontSize: 10 }}>{row.desc}</div>
                  </div>
                  <div style={{ height: 3, background: 'var(--bg3)', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{
                      width: `${(row.value / row.max) * 100}%`, height: '100%',
                      background: row.value > 0 ? riskColor(score) : 'var(--bg3)',
                      transition: 'width 0.5s ease',
                    }} />
                  </div>
                  <div style={{
                    textAlign: 'right', fontSize: 11, fontWeight: 700,
                    color: row.value > 0 ? riskColor(score) : 'var(--text3)',
                  }}>
                    {row.value > 0 ? `+${row.value}` : '0'}
                  </div>
                </div>
              ))}
              <div style={{
                display: 'flex', justifyContent: 'space-between',
                padding: '10px 12px', background: 'var(--bg3)',
                borderRadius: 'var(--r)', border: '1px solid var(--border2)',
              }}>
                <span style={{ color: 'var(--text2)', fontSize: 11 }}>Base + LLM history assessment</span>
                <span style={{ color: riskColor(score), fontWeight: 700, fontSize: 13 }}>= {score}/100</span>
              </div>
            </div>
          </section>

          {/* DECISION TREE */}
          <section>
            <SectionLabel>Decision Tree — How the Agent Routes This Client</SectionLabel>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {DECISION_TREE.map((step, i) => {
                const isFinal = step.met
                const isPast  = DECISION_TREE.slice(0, i).some(s => s.met)
                return (
                  <div key={step.step} style={{
                    display: 'flex', gap: 12, alignItems: 'flex-start',
                    paddingBottom: i < DECISION_TREE.length - 1 ? 0 : 0,
                  }}>
                    {/* connector */}
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
                      <div style={{
                        width: 22, height: 22, borderRadius: '50%', border: '1px solid',
                        borderColor: isFinal ? plan.color : isPast ? 'var(--bg3)' : 'var(--border)',
                        background: isFinal ? `${plan.color}20` : 'transparent',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 9, fontWeight: 700,
                        color: isFinal ? plan.color : isPast ? 'var(--text3)' : 'var(--text3)',
                        transition: 'all 0.2s',
                      }}>
                        {isPast ? '✓' : step.step}
                      </div>
                      {i < DECISION_TREE.length - 1 && (
                        <div style={{
                          width: 1, height: 20,
                          background: isPast || isFinal ? 'var(--border)' : 'var(--border)',
                        }} />
                      )}
                    </div>
                    <div style={{
                      flex: 1, paddingBottom: 16,
                      opacity: isPast ? 0.35 : 1,
                    }}>
                      <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 2 }}>
                        {step.condition}
                      </div>
                      <div style={{
                        fontSize: 10, fontWeight: isFinal ? 700 : 400,
                        color: isFinal ? plan.color : 'var(--text3)',
                      }}>
                        → {step.result}
                        {isFinal && <span style={{ marginLeft: 6 }}>← THIS CLIENT</span>}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>

          {/* TONE EXPLANATION */}
          <section>
            <SectionLabel>Communication Tone Logic</SectionLabel>
            <div style={{
              background: 'var(--bg2)', border: '1px solid var(--border)',
              borderRadius: 'var(--r)', padding: '12px 14px', fontSize: 11, lineHeight: 1.8,
            }}>
              {client.dispute_flag ? (
                <span style={{ color: 'var(--amber)' }}>Active dispute detected → tone forced to <b>Dispute Acknowledgment</b>. Agent will never send demanding language during an open dispute.</span>
              ) : (client.contact_count || 0) === 0 ? (
                <span>First contact → tone based on days overdue: <b style={{ color: tone.color }}>{tone.label}</b> ({days}d overdue)</span>
              ) : (client.contact_count || 0) === 1 ? (
                <span>Second contact → escalates to <b style={{ color: tone.color }}>Urgent</b> regardless of score</span>
              ) : score >= 70 ? (
                <span>3+ contacts, high risk → <b style={{ color: tone.color }}>Final Notice</b> tone</span>
              ) : (
                <span>3+ contacts → <b style={{ color: tone.color }}>Urgent</b> tone</span>
              )}
            </div>
          </section>

        </div>
      </div>
    </div>
  )
}

function SectionLabel({ children }) {
  return (
    <div style={{
      color: 'var(--text3)', fontSize: 9, fontWeight: 600,
      letterSpacing: '0.14em', textTransform: 'uppercase',
      marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8,
    }}>
      {children}
      <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
    </div>
  )
}

function MetricBox({ label, value, color }) {
  return (
    <div style={{
      background: 'var(--bg2)', border: '1px solid var(--border)',
      borderRadius: 'var(--r)', padding: '10px 12px', textAlign: 'center',
    }}>
      <div style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 700, color, letterSpacing: '-0.01em' }}>
        {value}
      </div>
      <div style={{ color: 'var(--text3)', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.1em', marginTop: 3 }}>
        {label}
      </div>
    </div>
  )
}

// ── DECISION QUEUE PREVIEW ────────────────────────────────────────────────────
function DecisionQueue({ clients }) {
  const planned = clients.map(c => ({ ...c, plan: deriveAgentPlan(c) }))
  const counts = { call: 0, email: 0, hitl: 0, escalate: 0, blocked: 0, monitor: 0 }
  planned.forEach(c => counts[c.plan.decision] = (counts[c.plan.decision] || 0) + 1)

  const order = ['call', 'escalate', 'hitl', 'email', 'monitor', 'blocked']
  const labels = { call: '📞 Call', escalate: '⚖ Escalate', hitl: '⚠ HITL', email: '✉ Email', monitor: '· Monitor', blocked: '🔒 Blocked' }
  const colors = { call: 'var(--violet)', escalate: 'var(--red)', hitl: 'var(--red)', email: 'var(--teal)', monitor: 'var(--text3)', blocked: 'var(--text3)' }

  return (
    <div style={{
      background: 'var(--bg2)', border: '1px solid var(--border)',
      borderRadius: 'var(--r)', padding: '12px 14px',
    }}>
      <div style={{ color: 'var(--text3)', fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 10 }}>
        Next Batch Preview
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {order.filter(k => counts[k] > 0).map(k => (
          <div key={k} style={{
            display: 'flex', alignItems: 'center', gap: 5,
            padding: '4px 10px', borderRadius: 4,
            background: `${colors[k]}12`, border: `1px solid ${colors[k]}30`,
          }}>
            <span style={{ fontSize: 11 }}>{labels[k].split(' ')[0]}</span>
            <span style={{ color: colors[k], fontWeight: 700, fontSize: 12 }}>{counts[k]}</span>
            <span style={{ color: 'var(--text3)', fontSize: 9 }}>{labels[k].split(' ').slice(1).join(' ')}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── MAIN DASHBOARD ────────────────────────────────────────────────────────────
export default function Dashboard({ data, batchRunning, onTriggerBatch }) {
  const [selected, setSelected] = useState(null)
  const portfolio = data?.portfolio || {}
  const clients   = data?.clients   || []
  const lastBatch = data?.last_batch || {}

  const totalClients = Object.values(portfolio.count_by_risk || {}).reduce((a, b) => a + b, 0) || clients.length

  return (
    <div style={{ display: 'flex', width: '100%', height: '100%', overflow: 'hidden' }}>

      {/* SIDEBAR */}
      <aside style={{
        width: 260, flexShrink: 0,
        borderRight: '1px solid var(--border)',
        background: 'var(--bg1)',
        display: 'flex', flexDirection: 'column',
        padding: 16, gap: 14, overflowY: 'auto',
      }}>
        {/* RUN BUTTON */}
        <button onClick={onTriggerBatch} disabled={batchRunning} style={{
          width: '100%', padding: '14px 0',
          background: batchRunning ? 'var(--bg3)' : 'var(--teal)',
          color: batchRunning ? 'var(--amber)' : '#000',
          border: batchRunning ? '1px solid var(--amber-dim)' : 'none',
          borderRadius: 'var(--r)',
          fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700,
          letterSpacing: '0.1em', cursor: batchRunning ? 'not-allowed' : 'pointer',
          transition: 'all 0.2s',
        }}>
          {batchRunning ? '⟳  BATCH RUNNING…' : '▶  RUN FULL BATCH'}
        </button>

        {batchRunning && (
          <div>
            <div style={{ background: 'var(--bg3)', borderRadius: 3, height: 3, overflow: 'hidden' }}>
              <div style={{ height: '100%', background: 'var(--amber)', width: '60%', animation: 'ppulse 1.5s ease-in-out infinite' }} />
            </div>
            <style>{`@keyframes ppulse { 0%,100%{opacity:0.5} 50%{opacity:1} }`}</style>
          </div>
        )}

        {/* STATS */}
        <div style={{ color: 'var(--text3)', fontSize: 9, letterSpacing: '0.14em', textTransform: 'uppercase' }}>Portfolio Overview</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <StatBox value={`₹${fmtAmt(portfolio.total_outstanding)}`} label="Outstanding" />
          <StatBox value={totalClients || '—'} label="Clients" color="var(--violet)" />
          <StatBox value={portfolio.count_by_risk?.High ?? '—'} label="High Risk" color="var(--red)"
            sub={`of ${totalClients}`} />
          <StatBox value={portfolio.overdue_gt_60 ?? '—'} label="60+ Days" color="var(--amber)" />
        </div>

        {/* NEXT BATCH PREVIEW */}
        {clients.length > 0 && !batchRunning && (
          <DecisionQueue clients={clients} />
        )}

        {/* HOW IT WORKS */}
        <div style={{
          background: 'var(--bg2)', border: '1px solid var(--border)',
          borderRadius: 'var(--r)', padding: '12px 14px',
          fontSize: 11, color: 'var(--text3)', lineHeight: 1.8,
        }}>
          <div style={{ color: 'var(--text2)', fontWeight: 600, marginBottom: 6, fontSize: 11 }}>How the agent decides</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {[
              ['🔒', 'Legal/disputed → blocked'],
              ['⚠', 'No contact / high stakes → HITL'],
              ['⚖', 'score≥85 + 75d → escalate'],
              ['📞', 'score≥70 + 60d → call'],
              ['✉', 'score≥40 or 30d → email'],
              ['·', 'otherwise → monitor'],
            ].map(([icon, text]) => (
              <div key={text} style={{ display: 'flex', gap: 6, alignItems: 'baseline', fontSize: 10 }}>
                <span style={{ flexShrink: 0, width: 14 }}>{icon}</span>
                <span>{text}</span>
              </div>
            ))}
          </div>
        </div>

        {/* LAST BATCH */}
        {lastBatch.timestamp && (
          <div style={{
            background: 'var(--bg2)', border: '1px solid var(--border)',
            borderRadius: 'var(--r)', padding: '10px 12px',
          }}>
            <div style={{ color: 'var(--text3)', fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 6 }}>Last Batch</div>
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>{new Date(lastBatch.timestamp).toLocaleTimeString()}</div>
            <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
              <span><span style={{ color: 'var(--teal)', fontWeight: 600 }}>{lastBatch.processed}</span><span style={{ color: 'var(--text3)', fontSize: 10 }}> done</span></span>
              {lastBatch.errors > 0 && <span><span style={{ color: 'var(--red)', fontWeight: 600 }}>{lastBatch.errors}</span><span style={{ color: 'var(--text3)', fontSize: 10 }}> err</span></span>}
            </div>
          </div>
        )}
      </aside>

      {/* MAIN TABLE */}
      <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 6 }}>
          <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 700, letterSpacing: '-0.02em' }}>
            Invoice Portfolio
          </h2>
          <span style={{ color: 'var(--text3)', fontSize: 11 }}>
            {clients.length} clients · sorted by priority · click any row to see agent reasoning
          </span>
        </div>

        {/* Column key */}
        <div style={{ display: 'flex', gap: 16, marginBottom: 14, padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
          {[
            { color: 'var(--violet)', label: 'Will call' },
            { color: 'var(--teal)',   label: 'Will email' },
            { color: 'var(--red)',    label: 'HITL / Escalate' },
            { color: 'var(--text3)', label: 'Monitor / Blocked' },
          ].map(({ color, label }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
              <span style={{ color: 'var(--text3)', fontSize: 10 }}>{label}</span>
            </div>
          ))}
        </div>

        {clients.length === 0 ? (
          <div style={{ color: 'var(--text3)', textAlign: 'center', padding: '60px 0', fontSize: 12 }}>
            No client data — start backend and refresh
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: '0 4px' }}>
            <thead>
              <tr>
                {['#', 'Client', 'Outstanding', 'Days', 'Risk', 'Agent Will…', 'Why', 'Tone'].map(h => (
                  <th key={h} style={{
                    textAlign: 'left', padding: '0 12px 8px',
                    color: 'var(--text3)', fontSize: 9, fontWeight: 500,
                    letterSpacing: '0.12em', textTransform: 'uppercase',
                    borderBottom: '1px solid var(--border)',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {clients.map((c, i) => {
                const plan  = deriveAgentPlan(c)
                const tone  = deriveTone(c)
                const score = c.max_risk_score || 0
                const days  = c.max_days_overdue || 0

                return (
                  <tr
                    key={c.client}
                    className="animate-in"
                    onClick={() => setSelected(c)}
                    style={{
                      animationDelay: `${i * 0.04}s`,
                      cursor: 'pointer',
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.querySelectorAll('td').forEach(td => td.style.background = 'var(--bg3)')
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.querySelectorAll('td').forEach(td => td.style.background = 'var(--bg2)')
                    }}
                  >
                    <td style={tdStyle({ borderLeft: `2px solid ${plan.color}`, borderRadius: 'var(--r) 0 0 var(--r)', color: 'var(--text3)', fontSize: 10, textAlign: 'center', width: 32 })}>
                      {i + 1}
                    </td>
                    <td style={tdStyle({ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 13, color: 'var(--text)' })}>
                      {c.client}
                    </td>
                    <td style={tdStyle({ color: 'var(--text)', fontWeight: 500 })}>
                      ₹{fmtAmt(c.total_amount)}
                    </td>
                    <td style={tdStyle({ color: days > 60 ? 'var(--red)' : days > 30 ? 'var(--amber)' : 'var(--text2)' })}>
                      {days}d
                    </td>
                    <td style={tdStyle({})}>
                      <ScoreBar score={score} />
                    </td>
                    <td style={tdStyle({})}>
                      <DecisionBadge plan={plan} />
                    </td>
                    <td style={tdStyle({ color: 'var(--text3)', fontSize: 11, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' })}>
                      {plan.reason.split(' → ')[0]}
                    </td>
                    <td style={tdStyle({ borderRadius: '0 var(--r) var(--r) 0' })}>
                      <span style={{
                        color: tone.color, fontSize: 9, fontWeight: 700,
                        letterSpacing: '0.08em', textTransform: 'uppercase',
                      }}>
                        {tone.label}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* DRAWER */}
      {selected && (
        <ClientDrawer client={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}

const tdStyle = (extra = {}) => ({
  padding: '10px 12px',
  background: 'var(--bg2)',
  transition: 'background 0.15s',
  ...extra,
})
