const TYPE_CONFIG = {
  success: { color: 'var(--teal)',   icon: '✓', label: 'SUCCESS' },
  error:   { color: 'var(--red)',    icon: '✗', label: 'ERROR'   },
  call:    { color: 'var(--violet)', icon: '◉', label: 'CALL'    },
  action:  { color: 'var(--amber)',  icon: '→', label: 'ACTION'  },
  hitl:    { color: 'var(--red)',    icon: '⚠', label: 'HITL'    },
  agent:   { color: 'var(--violet)', icon: '⟳', label: 'AGENT'  },
  system:  { color: 'var(--text3)',  icon: '·', label: 'SYSTEM'  },
  info:    { color: 'var(--text2)',  icon: '·', label: 'INFO'    },
}

function FeedEntry({ item, index }) {
  const cfg = TYPE_CONFIG[item.type] || TYPE_CONFIG.info

  return (
    <div
      className="animate-in"
      style={{
        display: 'grid',
        gridTemplateColumns: '44px 52px 1fr',
        gap: 0,
        borderBottom: '1px solid var(--border)',
        alignItems: 'start',
        animationDelay: `${Math.min(index * 0.03, 0.3)}s`,
      }}
    >
      <div style={{
        padding: '10px 0 10px 4px',
        color: 'var(--text3)', fontSize: 9,
        fontFamily: 'var(--font-mono)',
        lineHeight: '16px',
        borderRight: '1px solid var(--border)',
      }}>
        {item.time}
      </div>

      <div style={{
        padding: '10px 8px',
        display: 'flex', alignItems: 'center', gap: 5,
        borderRight: '1px solid var(--border)',
      }}>
        <span style={{ color: cfg.color, fontSize: 12 }}>{cfg.icon}</span>
        <span style={{
          color: cfg.color, fontSize: 8, fontWeight: 700,
          letterSpacing: '0.1em', textTransform: 'uppercase',
        }}>
          {cfg.label}
        </span>
      </div>

      <div style={{
        padding: '10px 14px',
        fontSize: 12, color: 'var(--text2)',
        lineHeight: 1.55,
        wordBreak: 'break-word',
      }}>
        {item.msg}
        {item.current && item.total && (
          <span style={{
            marginLeft: 8, fontSize: 10, color: 'var(--text3)',
            background: 'var(--bg3)', padding: '1px 6px', borderRadius: 3,
          }}>
            {item.current}/{item.total}
          </span>
        )}
      </div>
    </div>
  )
}

function BatchProgress({ items }) {
  const batchItems = items.filter(i => i.type === 'action')
  if (!batchItems.length) return null

  const counts = { call: 0, email: 0, hitl: 0, other: 0 }
  batchItems.forEach(i => {
    const m = i.msg.toLowerCase()
    if (m.includes('call')) counts.call++
    else if (m.includes('email')) counts.email++
    else if (m.includes('hitl') || m.includes('legal')) counts.hitl++
    else counts.other++
  })

  const bars = [
    { label: 'Call',  value: counts.call,  color: 'var(--violet)' },
    { label: 'Email', value: counts.email, color: 'var(--teal)'   },
    { label: 'HITL',  value: counts.hitl,  color: 'var(--red)'    },
    { label: 'Other', value: counts.other, color: 'var(--text3)'  },
  ].filter(b => b.value > 0)

  const total = Object.values(counts).reduce((a, b) => a + b, 0)

  return (
    <div style={{
      background: 'var(--bg2)', border: '1px solid var(--border)',
      borderRadius: 'var(--r2)', padding: '14px 18px',
      flexShrink: 0,
    }}>
      <div style={{
        color: 'var(--text3)', fontSize: 9, letterSpacing: '0.14em',
        textTransform: 'uppercase', marginBottom: 10,
      }}>
        Session Actions · {total} total
      </div>

      <div style={{ display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden', gap: 1, marginBottom: 10 }}>
        {bars.map(b => (
          <div key={b.label} style={{
            flex: b.value, background: b.color, minWidth: 2,
            transition: 'flex 0.4s ease',
          }} />
        ))}
      </div>

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {bars.map(b => (
          <div key={b.label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: b.color, display: 'inline-block' }} />
            <span style={{ color: 'var(--text3)', fontSize: 10 }}>{b.label}</span>
            <span style={{ color: b.color, fontWeight: 600, fontSize: 11 }}>{b.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function AgentFeed({ items, batchRunning }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', width: '100%', height: '100%',
      padding: 20, gap: 16, overflow: 'hidden',
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexShrink: 0 }}>
        <h2 style={{
          fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 700, letterSpacing: '-0.02em',
        }}>
          Agent Feed
        </h2>
        {batchRunning && (
          <span style={{ color: 'var(--amber)', fontSize: 11, display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--amber)', display: 'inline-block', animation: 'pulse-dot 1s infinite' }} />
            live
          </span>
        )}
        <span style={{ color: 'var(--text3)', fontSize: 11, marginLeft: 'auto' }}>
          {items.length} events
        </span>
      </div>

      <BatchProgress items={items} />

      {/* FEED TABLE */}
      <div style={{
        flex: 1, overflow: 'auto',
        background: 'var(--bg1)', border: '1px solid var(--border)',
        borderRadius: 'var(--r2)',
      }}>
        {/* HEADER */}
        <div style={{
          display: 'grid', gridTemplateColumns: '44px 52px 1fr',
          background: 'var(--bg2)', position: 'sticky', top: 0, zIndex: 1,
          borderBottom: '1px solid var(--border)',
        }}>
          {['Time', 'Type', 'Message'].map((h, i) => (
            <div key={h} style={{
              padding: '8px 0 8px',
              paddingLeft: i === 0 ? 4 : i === 2 ? 14 : 8,
              color: 'var(--text3)', fontSize: 9,
              fontWeight: 500, letterSpacing: '0.12em', textTransform: 'uppercase',
              borderRight: i < 2 ? '1px solid var(--border)' : 'none',
            }}>
              {h}
            </div>
          ))}
        </div>

        {items.length === 0 ? (
          <div style={{ color: 'var(--text3)', textAlign: 'center', padding: '60px 0', fontSize: 12 }}>
            Waiting for agent activity…
          </div>
        ) : (
          items.map((item, i) => <FeedEntry key={item.id} item={item} index={i} />)
        )}
      </div>
    </div>
  )
}
