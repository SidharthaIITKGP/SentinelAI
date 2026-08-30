import { useState, useEffect, useRef } from 'react';
import { Radio } from 'lucide-react';
import { RiskBadge, ActionBadge, formatTs, API_BASE } from './shared.jsx';

export default function LiveFeed({ onRowClick }) {
  const [rows, setRows] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const timerRef = useRef(null);

  const fetchLogs = async () => {
    try {
      const res = await fetch(`${API_BASE}/audit/recent?limit=20`);
      if (res.ok) {
        const data = await res.json();
        setRows(data);
      }
    } catch {}
  };

  useEffect(() => {
    fetchLogs();
    timerRef.current = setInterval(fetchLogs, 3000);
    return () => clearInterval(timerRef.current);
  }, []);

  const handleRowClick = (row) => {
    setSelectedId(row.request_id);
    if (onRowClick) onRowClick(row);
  };

  return (
    <div style={{
      background: 'rgba(26,24,40,0.85)',
      border: '1px solid rgba(83,74,183,0.2)',
      borderRadius: 12,
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '16px 20px',
        borderBottom: '1px solid rgba(83,74,183,0.15)',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}>
        <Radio size={14} style={{ color: '#4ADE80' }} className="animate-pulse-dot" />
        <h3 style={{ fontSize: 13, fontWeight: 600, color: '#8A8AAA', letterSpacing: '0.06em' }}>
          LIVE REQUEST FEED
        </h3>
        <span style={{
          marginLeft: 'auto',
          fontSize: 11,
          color: '#4ADE80',
          background: 'rgba(74, 222, 128, 0.1)',
          border: '1px solid rgba(74,222,128,0.2)',
          padding: '2px 8px',
          borderRadius: 99,
        }}>● Polling 3s</span>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'rgba(15,14,26,0.6)', borderBottom: '1px solid rgba(83,74,183,0.1)' }}>
              {['Time', 'Use Case', 'Risk', 'Action', 'Latency', 'Prompt'].map(h => (
                <th key={h} style={{
                  padding: '10px 14px',
                  textAlign: 'left',
                  color: '#6B7280',
                  fontWeight: 500,
                  fontSize: 11,
                  letterSpacing: '0.05em',
                  whiteSpace: 'nowrap',
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ padding: '40px 20px', textAlign: 'center', color: '#4B5563', fontSize: 13 }}>
                  No requests yet — POST to /intercept to see live data
                </td>
              </tr>
            ) : rows.map((row, idx) => {
              const isSelected = row.request_id === selectedId;
              const isOdd = idx % 2 === 0;
              return (
                <tr
                  key={row.request_id}
                  onClick={() => handleRowClick(row)}
                  className="animate-slide-in"
                  style={{
                    background: isSelected
                      ? 'rgba(83,74,183,0.18)'
                      : isOdd
                        ? 'rgba(26,24,40,0.4)'
                        : 'rgba(15,14,26,0.3)',
                    borderBottom: '1px solid rgba(83,74,183,0.06)',
                    cursor: 'pointer',
                    transition: 'background 0.15s',
                    borderLeft: isSelected ? '2px solid #534AB7' : '2px solid transparent',
                  }}
                  onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'rgba(83,74,183,0.08)'; }}
                  onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = isOdd ? 'rgba(26,24,40,0.4)' : 'rgba(15,14,26,0.3)'; }}
                >
                  <td style={{ padding: '10px 14px', color: '#6B7280', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                    {formatTs(row.timestamp)}
                  </td>
                  <td style={{ padding: '10px 14px', color: '#C4C2D8', whiteSpace: 'nowrap' }}>
                    {row.use_case?.replace(/_/g, ' ') ?? '—'}
                  </td>
                  <td style={{ padding: '10px 14px', whiteSpace: 'nowrap' }}>
                    <RiskBadge level={row.risk_level ?? 'LOW'} />
                  </td>
                  <td style={{ padding: '10px 14px', whiteSpace: 'nowrap' }}>
                    <ActionBadge action={row.action_taken ?? 'ALLOW'} />
                  </td>
                  <td style={{ padding: '10px 14px', color: '#8A8AAA', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                    {row.latency_ms ?? 0}ms
                  </td>
                  <td style={{ padding: '10px 14px', color: '#6B7280', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {row.prompt ?? '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}