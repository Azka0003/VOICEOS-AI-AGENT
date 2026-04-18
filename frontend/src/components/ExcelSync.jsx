import { useState, useEffect, useRef } from 'react'

const riskColor = (label) => {
  if (!label) return 'var(--text3)'
  const l = label.toLowerCase()
  if (l === 'high') return 'var(--red)'
  if (l === 'medium' || l === 'med') return 'var(--amber)'
  return 'var(--teal)'
}

const actionColor = (action) => {
  if (!action || action === '—') return 'var(--text3)'
  const a = action.toLowerCase()
  if (a.includes('call')) return 'var(--violet)'
  if (a.includes('email')) return 'var(--teal)'
  if (a.includes('hitl') || a.includes('legal')) return 'var(--red)'
  return 'var(--text2)'
}

const fmt = (v) => {
  if (!v && v !== 0) return '—'
  if (v >= 100000) return `₹${(v / 100000).toFixed(1)}L`
  if (v >= 1000) return `₹${(v / 1000).toFixed(0)}K`
  return `₹${v}`
}

function ExcelCell({ children, style }) {
  return (
    <td style={{
      padding: '9px 14px',
      borderRight: '1px solid var(--border)',
      borderBottom: '1px solid var(--border)',
      fontSize: 12, color: 'var(--text2)',
      background: 'var(--bg1)',
      transition: 'background 0.6s, color 0.3s',
      whiteSpace: 'nowrap',
      ...style,
    }}>
      {children}
    </td>
  )
}

function FlashRow({ row, index }) {
  const [flash, setFlash] = useState(false)
  const prevRef = useRef(row)

  useEffect(() => {
    if (prevRef.current.last_action !== row.last_action || prevRef.current.risk_label !== row.risk_label) {
      setFlash(true)
      const t = setTimeout(() => setFlash(false), 1400)
      prevRef.current = row
      return () => clearTimeout(t)
    }
    prevRef.current = row
  }, [row])

  const rColor = riskColor(row.risk_label)
  const aColor = actionColor(row.last_action)

  return (
    <tr style={{
      transition: 'background 0.3s',
    }}>
      {/* Row number */}
      <td style={{
        padding: '9px 10px', textAlign: 'center',
        background: 'var(--bg2)', borderRight: '1px solid var(--border)',
        borderBottom: '1px solid var(--border)',
        color: 'var(--text3)', fontSize: 10,
        fontFamily: 'var(--font-mono)',
      }}>
        {index + 2}
      </td>

      {/* Client */}
      <ExcelCell style={{ background: flash ? 'rgba(0,229,180,0.07)' : 'var(--bg1)' }}>
        <span style={{ color: 'var(--text)', fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: 13 }}>
          {row.client}
        </span>
      </ExcelCell>

      {/* Amount */}
      <ExcelCell style={{ background: flash ? 'rgba(0,229,180,0.05)' : 'var(--bg1)' }}>
        <span style={{ color: 'var(--text)', fontWeight: 500 }}>{fmt(row.amount)}</span>
      </ExcelCell>

      {/* Risk Score */}
      <ExcelCell style={{ background: flash ? 'rgba(0,229,180,0.05)' : 'var(--bg1)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 40, height: 3, background: 'var(--bg3)', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{ width: `${row.risk || 0}%`, height: '100%', background: rColor, transition: 'width 0.6s ease' }} />
          </div>
          <span style={{ color: rColor, fontSize: 11, fontWeight: 600 }}>{row.risk ?? '—'}</span>
        </div>
      </ExcelCell>

      {/* Risk Label */}
      <ExcelCell style={{ background: flash ? 'rgba(0,229,180,0.05)' : 'var(--bg1)' }}>
        <span style={{
          padding: '2px 8px', borderRadius: 3, fontSize: 9, fontWeight: 700,
          letterSpacing: '0.1em', textTransform: 'uppercase',
          background: `${rColor}18`, color: rColor,
          border: `1px solid ${rColor}30`,
        }}>
          {row.risk_label || '—'}
        </span>
      </ExcelCell>

      {/* Last Action */}
      <ExcelCell style={{ background: flash ? 'rgba(0,229,180,0.08)' : 'var(--bg1)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {flash && (
            <span style={{
              width: 5, height: 5, borderRadius: '50%',
              background: 'var(--teal)', display: 'inline-block',
              animation: 'pulse-dot 0.5s ease 3',
            }} />
          )}
          <span style={{ color: aColor, fontWeight: flash ? 600 : 400 }}>
            {row.last_action || '—'}
          </span>
        </div>
      </ExcelCell>

      {/* Updated */}
      <ExcelCell style={{ background: flash ? 'rgba(0,229,180,0.04)' : 'var(--bg1)', color: 'var(--text3)', fontSize: 10 }}>
        {flash ? (
          <span style={{ color: 'var(--teal)', fontWeight: 600 }}>
            ↑ {row.updated}
          </span>
        ) : (
          row.updated || '—'
        )}
      </ExcelCell>
    </tr>
  )
}

function SyncStatus({ lastBatch }) {
  if (!lastBatch?.timestamp) return null
  const ts = new Date(lastBatch.timestamp)

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '10px 16px',
      background: 'var(--bg2)', borderBottom: '1px solid var(--border)',
      flexShrink: 0,
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%',
        background: 'var(--teal)', display: 'inline-block',
        flexShrink: 0,
      }} />
      <span style={{ color: 'var(--text3)', fontSize: 11 }}>
        Last sync: <span style={{ color: 'var(--teal)' }}>{ts.toLocaleTimeString()}</span>
        {' '}· {lastBatch.processed} rows written
      </span>
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 9, color: 'var(--text3)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
          invoices.xlsx
        </span>
        <span style={{
          padding: '2px 7px', borderRadius: 3, fontSize: 9, fontWeight: 700,
          background: 'var(--teal-dim)', color: 'var(--teal)',
          border: '1px solid var(--teal-mid)',
        }}>
          SYNCED
        </span>
      </div>
    </div>
  )
}

export default function ExcelSync({ rows, lastBatch }) {
  const COLS = ['#', 'Client', 'Outstanding', 'Risk Score', 'Risk Label', 'Last Action', 'Updated']

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', width: '100%', height: '100%', overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '16px 20px 12px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg1)',
        display: 'flex', alignItems: 'baseline', gap: 12,
        flexShrink: 0,
      }}>
        <h2 style={{
          fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 700,
          letterSpacing: '-0.02em',
        }}>
          Excel Sync
        </h2>
        <span style={{ color: 'var(--text3)', fontSize: 11 }}>
          Real-time view of invoices.xlsx · cells flash on write
        </span>
      </div>

      <SyncStatus lastBatch={lastBatch} />

      {/* Spreadsheet area */}
      <div style={{ flex: 1, overflow: 'auto', background: 'var(--bg)' }}>
        {rows.length === 0 ? (
          <div style={{ color: 'var(--text3)', textAlign: 'center', padding: '80px 0', fontSize: 12 }}>
            No data — run a batch to populate Excel rows
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 700 }}>
            {/* Column header row — mimics Excel */}
            <thead>
              <tr>
                {COLS.map((col, i) => (
                  <th key={col} style={{
                    padding: '8px 14px',
                    background: 'var(--bg2)',
                    borderRight: '1px solid var(--border)',
                    borderBottom: '2px solid var(--border2)',
                    textAlign: i === 0 ? 'center' : 'left',
                    color: 'var(--text3)', fontSize: 9,
                    fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase',
                    position: 'sticky', top: 0, zIndex: 1,
                    whiteSpace: 'nowrap',
                  }}>
                    {i > 0 && (
                      <span style={{ marginRight: 5, color: 'var(--text3)', fontSize: 8 }}>
                        {String.fromCharCode(64 + i)}
                      </span>
                    )}
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {/* Row 1 header (like Excel) */}
              <tr>
                <td style={{
                  padding: '7px 10px', textAlign: 'center',
                  background: 'var(--bg2)', borderRight: '1px solid var(--border)',
                  borderBottom: '1px solid var(--border)',
                  color: 'var(--text3)', fontSize: 10,
                }}>
                  1
                </td>
                {['Client Name', 'Total Amount', 'Risk Score', 'Risk Level', 'Next Action', 'Timestamp'].map(h => (
                  <td key={h} style={{
                    padding: '7px 14px', background: 'var(--bg2)',
                    borderRight: '1px solid var(--border)',
                    borderBottom: '1px solid var(--border)',
                    color: 'var(--text3)', fontSize: 10,
                    fontStyle: 'italic',
                  }}>
                    {h}
                  </td>
                ))}
              </tr>

              {rows.map((row, i) => (
                <FlashRow key={row.client} row={row} index={i} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Bottom status bar */}
      <div style={{
        padding: '6px 16px', background: 'var(--bg2)', borderTop: '1px solid var(--border)',
        display: 'flex', gap: 20, flexShrink: 0,
      }}>
        <span style={{ color: 'var(--text3)', fontSize: 10 }}>
          {rows.length + 1} rows · {7} columns
        </span>
        <span style={{ color: 'var(--text3)', fontSize: 10 }}>
          Sheet1
        </span>
        <span style={{ marginLeft: 'auto', color: 'var(--text3)', fontSize: 10 }}>
          openpyxl · auto-save enabled
        </span>
      </div>
    </div>
  )
}
