import { useState, useEffect, useRef } from 'react';
import { Activity, TrendingUp, Clock, ShieldOff, AlertTriangle, Zap } from 'lucide-react';
import { API_BASE, TENANT_HEADERS } from './shared.jsx';

const CARD_DEFS = [
  { key: 'requests',   icon: Activity,      label: 'Requests',      sub: 'Last 24h',        color: '#A78BFA' },
  { key: 'latency',    icon: Clock,         label: 'Avg Latency',   sub: 'p95: …ms',        color: '#60A5FA' },
  { key: 'blocked',    icon: ShieldOff,     label: 'Blocked',       sub: '% rate',          color: '#F87171' },
  { key: 'escalated',  icon: AlertTriangle, label: 'Escalations',   sub: 'Pending review',  color: '#FBBF24' },
  { key: 'tokensSaved',icon: Zap,           label: 'Tokens Saved',  sub: 'By early block',  color: '#34D399' },
];

function MetricCard({ icon: Icon, label, value, sub, color }) {
  return (
    <div style={{
      background: 'rgba(26,24,40,0.85)',
      border: '1px solid rgba(83,74,183,0.2)',
      borderRadius: 12,
      padding: '20px 22px',
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      flex: 1,
      minWidth: 160,
      transition: 'border-color 0.2s',
    }}
      onMouseEnter={e => e.currentTarget.style.borderColor = color + '60'}
      onMouseLeave={e => e.currentTarget.style.borderColor = 'rgba(83,74,183,0.2)'}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, color }}>
        <Icon size={16} />
        <span style={{ fontSize: 12, fontWeight: 500, color: '#8A8AAA', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</span>
      </div>
      <div style={{ fontSize: 32, fontWeight: 700, color: '#E2E0F0', lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 12, color: '#6B7280' }}>{sub}</div>
    </div>
  );
}

export default function MetricsPanel() {
  const [metrics, setMetrics] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const timerRef = useRef(null);

  const fetchMetrics = async () => {
    try {
      const res = await fetch(`${API_BASE}/metrics?period=24h`, { headers: TENANT_HEADERS });
      if (res.ok) {
        const data = await res.json();
        setMetrics(data);
        setLastUpdated(new Date());
      }
    } catch {}
  };

  useEffect(() => {
    fetchMetrics();
    timerRef.current = setInterval(fetchMetrics, 30000);
    return () => clearInterval(timerRef.current);
  }, []);

  const totalReq = metrics?.total_requests ?? 0;
  const actions = metrics?.actions ?? {};
  const avgLat = metrics ? Math.round(metrics.avg_latency_ms) : 0;
  const p95Lat = metrics ? Math.round(metrics.p95_latency_ms) : 0;
  const blocked = actions.BLOCK ?? 0;
  const blockRate = totalReq > 0 ? ((blocked / totalReq) * 100).toFixed(1) : '0.0';
  const escalated = actions.ESCALATE ?? 0;
  // Tokens saved = requests that were blocked × avg tokens (est 200 tokens each)
  const tokensSaved = (blocked * 200);
  const tokensSavedDisplay = tokensSaved >= 1000 ? (tokensSaved / 1000).toFixed(1) + 'K' : String(tokensSaved);

  const cards = [
    { ...CARD_DEFS[0], value: totalReq.toLocaleString(),     sub: 'Last 24h' },
    { ...CARD_DEFS[1], value: `${avgLat}ms`,                  sub: `p95: ${p95Lat}ms` },
    { ...CARD_DEFS[2], value: String(blocked),                sub: `${blockRate}% rate` },
    { ...CARD_DEFS[3], value: String(escalated),              sub: 'Pending review' },
    { ...CARD_DEFS[4], value: tokensSavedDisplay,             sub: 'By early block' },
  ];

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, color: '#C4C2D8', display: 'flex', alignItems: 'center', gap: 6 }}>
          <TrendingUp size={15} style={{ color: '#A78BFA' }} /> System Metrics
        </h2>
        {lastUpdated && (
          <span style={{ fontSize: 11, color: '#4B5563' }}>
            Updated {lastUpdated.toLocaleTimeString('en-US', { hour12: false })}
          </span>
        )}
      </div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {cards.map(c => <MetricCard key={c.key} {...c} />)}
      </div>
    </div>
  );
}
