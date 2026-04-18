import { useState } from 'react'

const SCENARIO_LABELS = {
  MISSING_CONTACT:          { label: 'Missing Contact',       color: 'var(--amber)' },
  HIGH_STAKES_OVERDUE:      { label: 'High Stakes Overdue',   color: 'var(--red)'   },
  ACTIVE_DISPUTE:           { label: 'Active Dispute',        color: 'var(--red)'   },
  CONTACT_HISTORY_CONFLICT: { label: 'Too Soon',              color: 'var(--amber)' },
  DATA_ERROR_PHONE:         { label: 'Bad Phone #',           color: 'var(--amber)' },
  LEGAL_ESCALATION_CONFLICT:{ label: 'Legal Conflict',        color: 'var(--red)'   },
  CONTRADICTORY_RISK_SCORE: { label: 'Data Inconsistency',    color: 'var(--amber)' },
  LOW_CONFIDENCE_FALLBACK:  { label: 'Low Confidence',        color: 'var(--text3)' },
  CHROMADB_MISS:            { label: 'ChromaDB Miss',         color: 'var(--violet)'},
}

function Pill({ children, color = 'var(--text3)', bg }) {
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 9px', borderRadius: 4,
      fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
      color,
      background: bg || `${color}18`,
      border: `1px solid ${color}30`,
    }}>
      {children}
    </span>
  )
}

function ContextGrid({ ctx }) {
  if (!ctx) return null
  const rows = [
    ctx.client       && ['Client',      ctx.client,      'var(--text)'],
    ctx.invoice_id   && ['Invoice',     ctx.invoice_id,  'var(--text2)'],
    ctx.amount       && ['Amount',      `₹${Number(ctx.amount).toLocaleString()}`, 'var(--teal)'],
    ctx.days_overdue != null && ['Days Overdue', `${ctx.days_overdue}d`, ctx.days_overdue > 60 ? 'var(--red)' : 'var(--amber)'],
    ctx.risk_score   != null && ['Risk Score',   ctx.risk_score,  ctx.risk_score >= 70 ? 'var(--red)' : ctx.risk_score >= 40 ? 'var(--amber)' : 'var(--teal)'],
    ctx.risk_label   && ['Risk Label',  ctx.risk_label,  'var(--text2)'],
    ctx.contact_name && ['Contact',     ctx.contact_name,'var(--text2)'],
    ctx.dispute_flag != null && ['Dispute',    ctx.dispute_flag ? 'YES' : 'No', ctx.dispute_flag ? 'var(--red)' : 'var(--text3)'],
  ].filter(Boolean)

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1fr 1fr',
      gap: 6, marginBottom: 14,
    }}>
      {rows.map(([label, value, color]) => (
        <div key={label} style={{
          background: 'var(--bg3)', borderRadius: 'var(--r)',
          padding: '7px 10px', border: '1px solid var(--border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6,
        }}>
          <span style={{ color: 'var(--text3)', fontSize: 9, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            {label}
          </span>
          <span style={{ color: color || 'var(--text2)', fontWeight: 600, fontSize: 11, textAlign: 'right' }}>
            {String(value)}
          </span>
        </div>
      ))}
    </div>
  )
}

function CommsHistory({ summary }) {
  if (!summary || summary.total_contacts === 0) return null
  return (
    <div style={{
      background: 'var(--bg3)', border: '1px solid var(--border)',
      borderRadius: 'var(--r)', padding: '8px 12px',
      marginBottom: 14, fontSize: 11,
    }}>
      <div style={{ color: 'var(--text3)', fontSize: 9, letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6 }}>
        Comms History
      </div>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <span><span style={{ color: 'var(--text3)' }}>Contacts </span><span style={{ color: 'var(--teal)', fontWeight: 600 }}>{summary.total_contacts}</span></span>
        {summary.last_contact_type && summary.last_contact_type !== 'none' && (
          <span><span style={{ color: 'var(--text3)' }}>Last </span><span style={{ color: 'var(--text2)' }}>{summary.last_contact_type}</span></span>
        )}
        {summary.last_contact_date && (
          <span style={{ color: 'var(--text3)', fontSize: 10 }}>
            {new Date(summary.last_contact_date).toLocaleDateString()}
          </span>
        )}
        {summary.last_tone && summary.last_tone !== 'none' && (
          <span><span style={{ color: 'var(--text3)' }}>Tone </span><span style={{ color: 'var(--text2)' }}>{summary.last_tone}</span></span>
        )}
      </div>
    </div>
  )
}

function OptionButtons({ options, onAction, resolving }) {
  if (!options?.length) {
    // Fallback to simple approve/skip
    return (
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={() => onAction('approve')} disabled={resolving}
          style={primaryBtnStyle(resolving)}>
          {resolving ? 'RESOLVING…' : '✓  APPROVE'}
        </button>
        <button onClick={() => onAction('skip')} disabled={resolving}
          style={ghostBtnStyle}>SKIP</button>
      </div>
    )
  }

  const primary = options.find(o => o.option_id === 'proceed_anyway') || options[0]
  const secondary = options.filter(o => o.option_id !== primary.option_id)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <button onClick={() => onAction(primary.option_id)} disabled={resolving}
        style={primaryBtnStyle(resolving)}>
        {resolving ? 'RESOLVING…' : primary.label}
      </button>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {secondary.map(opt => (
          <button key={opt.option_id} onClick={() => onAction(opt.option_id)} disabled={resolving}
            style={{
              ...ghostBtnStyle,
              flex: 1, minWidth: 80,
              fontSize: 10,
            }}
            onMouseEnter={e => { e.currentTarget.style.color = 'var(--red)'; e.currentTarget.style.borderColor = 'var(--red-mid)' }}
            onMouseLeave={e => { e.currentTarget.style.color = 'var(--text3)'; e.currentTarget.style.borderColor = 'var(--border)' }}
          >
            {opt.label.length > 28 ? opt.label.slice(0, 28) + '…' : opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}

const primaryBtnStyle = (disabled) => ({
  width: '100%', padding: '10px 0',
  background: disabled ? 'var(--bg3)' : 'var(--teal)',
  color: disabled ? 'var(--text3)' : '#000',
  border: 'none', borderRadius: 'var(--r)',
  fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700,
  letterSpacing: '0.08em', cursor: disabled ? 'not-allowed' : 'pointer',
  transition: 'all 0.2s',
})

const ghostBtnStyle = {
  padding: '8px 14px',
  background: 'transparent', color: 'var(--text3)',
  border: '1px solid var(--border)', borderRadius: 'var(--r)',
  fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer',
  transition: 'all 0.15s',
}

function HITLCard({ item, onApprove }) {
  const [resolving, setResolving] = useState(false)

  // Support both old flat shape and new rich checkpoint shape
  const id = item.checkpoint_id || item.id || '?'
  const client = item.invoice_context?.client || item.client || id
  const scenario = item.trigger?.scenario_code || item.scenario || ''
  const reason = item.trigger?.human_readable_reason || item.reason || 'Human review required.'
  const wouldHaveDone = item.trigger?.would_have_done
  const confidence = item.trigger?.confidence_before_pause
  const invoiceCtx = item.invoice_context || null
  const commsSummary = item.comms_history_summary || null
  const options = item.options_for_human || null
  const createdAt = item.created_at ? new Date(item.created_at).toLocaleTimeString('en', { hour12: false }) : null

  const scenarioCfg = SCENARIO_LABELS[scenario] || { label: scenario || 'Review', color: 'var(--red)' }

  const handle = async (optionId) => {
    setResolving(true)
    await onApprove(id, optionId)
  }

  return (
    <div className="animate-in" style={{
      border: `1px solid ${scenarioCfg.color}40`,
      borderRadius: 'var(--r2)',
      background: `${scenarioCfg.color}08`,
      padding: 18,
      position: 'relative', overflow: 'hidden',
    }}>
      {/* top-right glow */}
      <div style={{
        position: 'absolute', top: 0, right: 0, width: 80, height: 80,
        background: `radial-gradient(circle at top right, ${scenarioCfg.color}18 0%, transparent 70%)`,
        pointerEvents: 'none',
      }} />

      {/* HEADER */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 14 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{
              fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 700,
              color: 'var(--text)', letterSpacing: '-0.01em',
            }}>
              {client}
            </span>
            <Pill color={scenarioCfg.color}>{scenarioCfg.label}</Pill>
            {confidence != null && (
              <Pill color="var(--text3)">conf {Math.round(confidence * 100)}%</Pill>
            )}
          </div>
          <div style={{ color: 'var(--text3)', fontSize: 9, marginTop: 3, display: 'flex', gap: 10 }}>
            <span>ID: {id}</span>
            {createdAt && <span>{createdAt}</span>}
          </div>
        </div>
        <span style={{
          padding: '3px 9px', borderRadius: 4, fontSize: 9, fontWeight: 700,
          background: 'var(--red-mid)', color: 'var(--red)',
          letterSpacing: '0.1em', animation: 'pulse-dot 2.5s infinite',
          flexShrink: 0,
        }}>
          ⚠ PENDING
        </span>
      </div>

      {/* REASON BOX */}
      <div style={{
        background: 'var(--bg3)', borderRadius: 'var(--r)',
        padding: '10px 14px', marginBottom: 14,
        border: '1px solid var(--border)',
        fontSize: 12, color: 'var(--text2)', lineHeight: 1.7,
        borderLeft: `2px solid ${scenarioCfg.color}60`,
      }}>
        {reason}
      </div>

      {/* WOULD HAVE DONE */}
      {wouldHaveDone && wouldHaveDone !== 'unknown' && (
        <div style={{
          marginBottom: 12, fontSize: 11, display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ color: 'var(--text3)' }}>Would have done:</span>
          <Pill color="var(--violet)">{wouldHaveDone}</Pill>
        </div>
      )}

      {/* CONTEXT GRID */}
      <ContextGrid ctx={invoiceCtx} />

      {/* COMMS HISTORY */}
      <CommsHistory summary={commsSummary} />

      {/* ACTION BUTTONS */}
      <OptionButtons options={options} onAction={handle} resolving={resolving} />
    </div>
  )
}

function DecisionRow({ entry }) {
  const ts = entry.timestamp
    ? new Date(entry.timestamp).toLocaleTimeString('en', { hour12: false, hour: '2-digit', minute: '2-digit' })
    : '??:??'

  // Determine event type color
  const isHITL    = entry.hitl_triggered || entry.action?.includes?.('HITL') || entry.agent === 'hitl_manager'
  const isSuccess = entry.decision?.includes?.('email') || entry.decision?.includes?.('call')
  const isBlocked = entry.decision === 'blocked' || entry.action === 'blocked'
  const color = isHITL ? 'var(--red)' : isBlocked ? 'var(--amber)' : isSuccess ? 'var(--teal)' : 'var(--text3)'

  const label = entry.decision || entry.action || entry.event || entry.hitl_scenario || '—'
  const subject = entry.client || entry.agent || '—'

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '42px 8px 1fr auto', gap: '0 8px',
      padding: '8px 0', borderBottom: '1px solid var(--border)',
      alignItems: 'start',
    }}>
      <span style={{ color: 'var(--text3)', fontSize: 10, paddingTop: 1 }}>{ts}</span>
      <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, marginTop: 3, flexShrink: 0 }} />
      <span style={{ color: 'var(--text2)', fontSize: 11, lineHeight: 1.4 }}>
        <span style={{ color: 'var(--teal)', fontWeight: 600 }}>{subject}</span>
        {' → '}{label}
        {entry.hitl_scenario && <span style={{ color: 'var(--red)', marginLeft: 4 }}>[{entry.hitl_scenario}]</span>}
      </span>
      {entry.risk_score != null && (
        <span style={{
          fontSize: 9, padding: '2px 6px', borderRadius: 3,
          background: 'var(--bg3)', color: 'var(--text3)', border: '1px solid var(--border)',
          flexShrink: 0,
        }}>
          {entry.risk_score}
        </span>
      )}
    </div>
  )
}

export default function HITLPanel({ pending, onApprove, decisionLog }) {
  // pending is either an object or array depending on backend version
  const items = Array.isArray(pending)
    ? pending
    : Object.values(pending || {})
  const pendingItems = items.filter(i => i.status === 'pending' || !i.status)

  const recentLog = [...(decisionLog || [])].reverse().slice(0, 60)

  return (
    <div style={{ display: 'flex', width: '100%', height: '100%', overflow: 'hidden' }}>

      {/* LEFT — PENDING QUEUE */}
      <div style={{
        flex: '0 0 460px', borderRight: '1px solid var(--border)',
        background: 'var(--bg1)', display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{
          padding: '16px 20px 12px', borderBottom: '1px solid var(--border)',
          display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
        }}>
          <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 700, letterSpacing: '-0.02em' }}>
            HITL Queue
          </h2>
          {pendingItems.length > 0 && (
            <span style={{
              background: 'var(--red)', color: '#fff', borderRadius: 10,
              fontSize: 10, fontWeight: 700, padding: '2px 8px',
              animation: 'pulse-dot 2s infinite',
            }}>
              {pendingItems.length}
            </span>
          )}
          <span style={{ marginLeft: 'auto', color: 'var(--text3)', fontSize: 10 }}>
            Human review required before agent can proceed
          </span>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {pendingItems.length === 0 ? (
            <div style={{
              textAlign: 'center', padding: '70px 20px',
              color: 'var(--text3)', fontSize: 12, lineHeight: 2,
            }}>
              <div style={{ fontSize: 36, marginBottom: 12, opacity: 0.2 }}>✓</div>
              All clear — no approvals pending
              <br />
              <span style={{ fontSize: 10 }}>HITL checkpoints will appear here when the agent pauses</span>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {pendingItems.map((item) => (
                <HITLCard
                  key={item.checkpoint_id || item.id}
                  item={item}
                  onApprove={onApprove}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* RIGHT — DECISION LOG */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Header */}
        <div style={{
          padding: '16px 20px 12px', borderBottom: '1px solid var(--border)',
          display: 'flex', alignItems: 'baseline', gap: 10, flexShrink: 0,
          background: 'var(--bg1)',
        }}>
          <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 700, letterSpacing: '-0.02em' }}>
            Decision Log
          </h2>
          <span style={{ color: 'var(--text3)', fontSize: 10 }}>
            {recentLog.length} entries · last 60 events
          </span>
        </div>

        {/* Colour key */}
        <div style={{
          padding: '8px 20px', borderBottom: '1px solid var(--border)',
          display: 'flex', gap: 16, flexShrink: 0, background: 'var(--bg2)',
        }}>
          {[
            { color: 'var(--teal)',   label: 'Action taken' },
            { color: 'var(--red)',    label: 'HITL triggered' },
            { color: 'var(--amber)',  label: 'Blocked / warned' },
            { color: 'var(--text3)', label: 'Other' },
          ].map(({ color, label }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: color }} />
              <span style={{ color: 'var(--text3)', fontSize: 9 }}>{label}</span>
            </div>
          ))}
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '4px 20px 20px' }}>
          {recentLog.length === 0 ? (
            <div style={{ color: 'var(--text3)', fontSize: 12, textAlign: 'center', paddingTop: 50 }}>
              No decisions recorded yet
            </div>
          ) : (
            recentLog.map((entry, i) => <DecisionRow key={i} entry={entry} />)
          )}
        </div>
      </div>
    </div>
  )
}
