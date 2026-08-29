import { useState, useEffect, useRef } from 'react';
import { Search, Download, FileText } from 'lucide-react';
import { RiskBadge, ActionBadge, formatTs, API_BASE } from './shared.jsx';

const ALL_ACTIONS = ['ALL', 'ALLOW', 'REDACT', 'BLOCK', 'REPAIR', 'ESCALATE'];
const ALL_RISKS   = ['ALL', 'LOW', 'MEDIUM', 'HIGH'];
const ALL_CASES   = ['ALL', 'customer_chatbot', 'hr_copilot', 'finance_tool'];

function exportCSV(rows) {
  const header = 'Request ID,Use Case,Action,Risk Score,Risk Level,LLM Called,Latency (ms),Timestamp,Prompt\n';
  const lines = rows.map(r => [
    r.request_id,
    r.use_case,
    r.action_taken,
    (r.risk_score ?? 0).toFixed(3),
    r.risk_level,
    r.model_used && r.model_used !== 'none' ? 'Yes' : 'No',
    r.latency_ms,
    r.timestamp,
    `"${(r.prompt || '').replace(/"/g, '""')}"`,
  ].join(',')).join('\n');
  const blob = new Blob([header + lines], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `sentinelai_audit_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function AuditLog() {
  const [rows, setRows] = useState([]);
  const [search, setSearch] = useState('');
  const [actionFilter, setActionFilter] = useState('ALL');
  const [riskFilter, setRiskFilter] = useState('ALL');
  const [caseFilter, setCaseFilter] = useState('ALL');
  const timerRef = useRef(null);

  const fetchLogs = async () => {
    try {
      const res = await fetch(`${API_BASE}/audit/recent?limit=200`);
      if (res.ok) setRows(await res.json());
    } catch {}
  };

  useEffect(() => {
    fetchLogs();
    timerRef.current = setInterval(fetchLogs, 10000);
    return () => clearInterval(timerRef.current);
  }, []);

  const filtered = rows.filter(r => {
    if (actionFilter !== 'ALL' && r.action_taken !== actionFilter) return false;
    if (riskFilter !== 'ALL' && r.risk_level !== riskFilter) return false;
    if (caseFilter !== 'ALL' && r.use_case !== caseFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      if (!(r.prompt || '').toLowerCase().includes(q) &&
          !(r.request_id || '').toLowerCase().includes(q)) return false;
    }
    return true;
  });

  const selectStyle = {
    background: '#1A1828',
    border: '1px solid rgba(83,74,183,0.25)',
    borderRadius: 8,
    padding: '7px 10px',
    color: '#C4C2D8',
    fontSize: 12,
    cursor: 'pointer',
    outline: 'none',
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
        gap: 10,
        flexWrap: 'wrap',
      }}>
        <FileText size={14} style={{ color: '#A78BFA' }} />
        <h3 style={{ fontSize: 13, fontWeight: 600, color: '#8A8AAA', letterSpacing: '0.06em', marginRight: 4 }}>
          AUDIT LOG
        </h3>

        {/* Search */}
        <div style={{ position: 'relative', flex: 1, minWidth: 160, maxWidth: 260 }}>
          <Search size={12} style={{ position: 'absolute', left: 9, top: '50%', transform: 'translateY(-50%)', color: '#6B7280' }} />
          <input
            type="text"
            placeholder="Search prompts..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{
              ...selectStyle,
              width: '100%',
              paddingLeft: 28,
            }}
          />
        </div>

        {/* Filters */}
        <select value={actionFilter} onChange={e => setActionFilter(e.target.value)} style={selectStyle}>
          {ALL_ACTIONS.map(a => <option key={a} value={a}>{a === 'ALL' ? 'All actions' : a}</option>)}
        </select>
        <select value={riskFilter} onChange={e => setRiskFilter(e.target.value)} style={selectStyle}>
          {ALL_RISKS.map(r => <option key={r} value={r}>{r === 'ALL' ? 'All risks' : r}</option>)}
        </select>
        <select value={caseFilter} onChange={e => setCaseFilter(e.target.value)} style={selectStyle}>
          {ALL_CASES.map(c => <option key={c} value={c}>{c === 'ALL' ? 'All use cases' : c.replace(/_/g,' ')}</option>)}
        </select>

        <button
          onClick={() => exportCSV(filtered)}
          id="audit-export-btn"
          style={{
            marginLeft: 'auto',
            background: '#534AB7',
            border: 'none',
            borderRadius: 8,
            padding: '7px 14px',
            color: '#fff',
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            transition: 'background 0.15s',
          }}
          onMouseEnter={e => e.currentTarget.style.background = '#6B62C9'}
          onMouseLeave={e => e.currentTarget.style.background = '#534AB7'}
        >
          <Download size={12} />
          Export CSV
        </button>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'rgba(15,14,26,0.6)', borderBottom: '1px solid rgba(83,74,183,0.1)' }}>
              {['Request ID', 'Time', 'Use Case', 'Action', 'Risk', 'LLM Called?', 'Latency'].map(h => (
                <th key={h} style={{ padding: '10px 14px', textAlign: 'left', color: '#6B7280', fontWeight: 500, fontSize: 11, letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ padding: '40px 20px', textAlign: 'center', color: '#4B5563', fontSize: 13 }}>
                  {rows.length === 0 ? 'No audit records yet' : 'No results match your filters'}
                </td>
              </tr>
            ) : filtered.map((row, idx) => {
              const llmCalled = row.model_used && row.model_used !== 'none';
              return (
                <tr key={row.request_id} style={{
                  background: idx % 2 === 0 ? 'rgba(26,24,40,0.4)' : 'rgba(15,14,26,0.3)',
                  borderBottom: '1px solid rgba(83,74,183,0.06)',
                  transition: 'background 0.1s',
                }}
                  onMouseEnter={e => e.currentTarget.style.background = 'rgba(83,74,183,0.07)'}
                  onMouseLeave={e => e.currentTarget.style.background = idx % 2 === 0 ? 'rgba(26,24,40,0.4)' : 'rgba(15,14,26,0.3)'}
                >
                  <td style={{ padding: '10px 14px', color: '#6B7280', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                    {row.request_id?.slice(0,8)}…{row.request_id?.slice(-4)}
                  </td>
                  <td style={{ padding: '10px 14px', color: '#6B7280', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                    {formatTs(row.timestamp)}
                  </td>
                  <td style={{ padding: '10px 14px', color: '#C4C2D8', whiteSpace: 'nowrap' }}>
                    {(row.use_case || '—').replace(/_/g,' ')}
                  </td>
                  <td style={{ padding: '10px 14px' }}>
                    <ActionBadge action={row.action_taken ?? 'ALLOW'} />
                  </td>
                  <td style={{ padding: '10px 14px' }}>
                    <RiskBadge level={row.risk_level ?? 'LOW'} />
                    <span style={{ marginLeft: 6, color: '#6B7280', fontSize: 11 }}>
                      {((row.risk_score ?? 0)).toFixed(3)}
                    </span>
                  </td>
                  <td style={{ padding: '10px 14px', color: llmCalled ? '#4ADE80' : '#6B7280' }}>
                    {llmCalled ? 'Yes' : `No (${row.tokens_used ?? 0} tokens)`}
                  </td>
                  <td style={{ padding: '10px 14px', color: '#8A8AAA', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                    {row.latency_ms ?? 0}ms
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div style={{ padding: '10px 20px', borderTop: '1px solid rgba(83,74,183,0.1)', fontSize: 11, color: '#4B5563' }}>
        Showing {filtered.length} of {rows.length} records
      </div>
    </div>
  );
}