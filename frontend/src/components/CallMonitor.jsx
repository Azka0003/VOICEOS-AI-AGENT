import { useEffect, useRef } from 'react'

function TranscriptLine({ line, index }) {
  const isAgent = line.role === 'assistant' || line.role === 'agent'
  return (
    <div
      className="animate-in"
      style={{
        display: 'flex',
        flexDirection: isAgent ? 'row' : 'row-reverse',
        gap: 10, alignItems: 'flex-end',
        animationDelay: `${Math.min(index * 0.04, 0.4)}s`,
        marginBottom: 10,
      }}
    >
      {/* Avatar */}
      <div style={{
        width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
        background: isAgent ? 'var(--teal-dim)' : 'var(--violet-dim)',
        border: `1px solid ${isAgent ? 'var(--teal-mid)' : 'var(--violet)40'}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 10, color: isAgent ? 'var(--teal)' : 'var(--violet)',
        fontWeight: 700, fontFamily: 'var(--font-display)',
      }}>
        {isAgent ? 'AI' : 'C'}
      </div>

      <div style={{ maxWidth: '72%' }}>
        <div style={{
          fontSize: 9, color: 'var(--text3)', marginBottom: 3,
          textAlign: isAgent ? 'left' : 'right',
          letterSpacing: '0.08em', textTransform: 'uppercase',
        }}>
          {isAgent ? 'DebtPilot AI' : 'Client'} · {line.time}
        </div>
        <div style={{
          padding: '10px 14px', borderRadius: isAgent ? '4px 10px 10px 10px' : '10px 4px 10px 10px',
          background: isAgent ? 'var(--bg3)' : 'var(--violet-dim)',
          border: `1px solid ${isAgent ? 'var(--border)' : 'var(--violet)30'}`,
          fontSize: 13, lineHeight: 1.6, color: 'var(--text)',
          borderLeft: isAgent ? `2px solid var(--teal)` : 'none',
          borderRight: !isAgent ? `2px solid var(--violet)` : 'none',
        }}>
          {line.content}
        </div>
      </div>
    </div>
  )
}

function WaveViz({ active }) {
  if (!active) return null
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 2, height: 20 }}>
      {[...Array(12)].map((_, i) => (
        <div
          key={i}
          style={{
            width: 2, borderRadius: 1,
            background: 'var(--violet)',
            animation: `wave-bar 0.8s ease-in-out infinite`,
            animationDelay: `${i * 0.07}s`,
          }}
        />
      ))}
      <style>{`
        @keyframes wave-bar {
          0%, 100% { height: 3px; opacity: 0.3; }
          50% { height: 18px; opacity: 1; }
        }
      `}</style>
    </div>
  )
}

export default function CallMonitor({ activeCall, transcript, feedItems }) {
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [transcript])

  const callFeedItems = feedItems.filter(i => i.type === 'call' || i.type === 'success')
    .slice(0, 8)

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', width: '100%', height: '100%',
      overflow: 'hidden',
    }}>

      {/* CALL HEADER */}
      <div style={{
        padding: '16px 24px',
        borderBottom: '1px solid var(--border)',
        background: activeCall ? 'rgba(139,120,255,0.06)' : 'var(--bg1)',
        flexShrink: 0,
        display: 'flex', alignItems: 'center', gap: 16,
        transition: 'background 0.5s',
      }}>
        <div style={{
          width: 44, height: 44, borderRadius: '50%',
          background: activeCall ? 'var(--violet-dim)' : 'var(--bg3)',
          border: `1px solid ${activeCall ? 'var(--violet)40' : 'var(--border)'}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 20,
          animation: activeCall ? 'pulse-dot 2s infinite' : 'none',
        }}>
          📞
        </div>

        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {activeCall ? (
              <>
                <span style={{
                  width: 7, height: 7, borderRadius: '50%',
                  background: 'var(--red)', display: 'inline-block',
                  animation: 'pulse-dot 1s infinite',
                }} />
                <span style={{
                  fontFamily: 'var(--font-display)', fontSize: 14, fontWeight: 700,
                  color: 'var(--red)', letterSpacing: '0.04em',
                }}>
                  LIVE CALL
                </span>
              </>
            ) : (
              <span style={{ color: 'var(--text3)', fontSize: 12 }}>No active call</span>
            )}
          </div>
          {activeCall && (
            <div style={{
              fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 700,
              color: 'var(--text)', letterSpacing: '-0.01em', marginTop: 2,
            }}>
              {activeCall.client}
            </div>
          )}
        </div>

        {activeCall && (
          <div style={{ marginLeft: 'auto' }}>
            <WaveViz active={!!activeCall} />
          </div>
        )}
      </div>

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* TRANSCRIPT */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{
            padding: '10px 24px 6px',
            color: 'var(--text3)', fontSize: 9, letterSpacing: '0.14em',
            textTransform: 'uppercase', flexShrink: 0,
            borderBottom: '1px solid var(--border)',
          }}>
            Live Transcript · {transcript.length} lines
          </div>

          <div
            ref={scrollRef}
            style={{
              flex: 1, overflowY: 'auto',
              padding: '20px 24px',
            }}
          >
            {transcript.length === 0 ? (
              <div style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center',
                justifyContent: 'center', height: '100%', gap: 12,
                color: 'var(--text3)', fontSize: 12,
              }}>
                <div style={{ fontSize: 40, opacity: 0.15 }}>◉</div>
                {activeCall
                  ? 'Call in progress — transcript will appear here'
                  : 'No active call — transcript will appear when a call starts'
                }
              </div>
            ) : (
              transcript.map((line, i) => (
                <TranscriptLine key={i} line={line} index={i} />
              ))
            )}
          </div>
        </div>

        {/* SIDE PANEL — call context */}
        <aside style={{
          width: 260, flexShrink: 0,
          borderLeft: '1px solid var(--border)',
          background: 'var(--bg1)',
          padding: 16, overflowY: 'auto',
          display: 'flex', flexDirection: 'column', gap: 16,
        }}>
          <div>
            <div style={{
              color: 'var(--text3)', fontSize: 9, letterSpacing: '0.14em',
              textTransform: 'uppercase', marginBottom: 10,
            }}>
              Call Events
            </div>
            {callFeedItems.length === 0 ? (
              <div style={{ color: 'var(--text3)', fontSize: 11, textAlign: 'center', padding: '20px 0' }}>
                No call events yet
              </div>
            ) : (
              callFeedItems.map((item, i) => (
                <div key={i} style={{
                  padding: '7px 0', borderBottom: '1px solid var(--border)',
                  fontSize: 11, display: 'flex', gap: 8,
                  animation: 'fade-in 0.2s ease both',
                }}>
                  <span style={{ color: 'var(--text3)', fontSize: 9, flexShrink: 0 }}>{item.time}</span>
                  <span style={{ color: 'var(--text2)' }}>{item.msg}</span>
                </div>
              ))
            )}
          </div>

          {/* LEGEND */}
          <div style={{
            background: 'var(--bg2)', border: '1px solid var(--border)',
            borderRadius: 'var(--r)', padding: 12,
          }}>
            <div style={{ color: 'var(--text3)', fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 8 }}>
              Participants
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 20, height: 20, borderRadius: '50%', background: 'var(--teal-dim)', border: '1px solid var(--teal-mid)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 8, color: 'var(--teal)', fontWeight: 700 }}>AI</div>
                <span style={{ color: 'var(--text2)', fontSize: 11 }}>DebtPilot Agent</span>
                <span style={{ marginLeft: 'auto', width: 4, height: 4, borderRadius: '50%', background: activeCall ? 'var(--teal)' : 'var(--text3)', display: 'inline-block', animation: activeCall ? 'pulse-dot 1.5s infinite' : 'none' }} />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 20, height: 20, borderRadius: '50%', background: 'var(--violet-dim)', border: '1px solid var(--violet)40', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 8, color: 'var(--violet)', fontWeight: 700 }}>C</div>
                <span style={{ color: 'var(--text2)', fontSize: 11 }}>{activeCall?.client || 'Client'}</span>
                <span style={{ marginLeft: 'auto', width: 4, height: 4, borderRadius: '50%', background: activeCall ? 'var(--violet)' : 'var(--text3)', display: 'inline-block', animation: activeCall ? 'pulse-dot 1.5s infinite 0.5s' : 'none' }} />
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}
