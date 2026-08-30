import { useState, useEffect, useRef } from 'react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { BarChart2 } from 'lucide-react';
import { API_BASE, TENANT_HEADERS } from './shared.jsx';

const ACTION_PIE_COLORS = {
  ALLOW:    '#4ADE80',
  REDACT:   '#FB923C',
  BLOCK:    '#F87171',
  REPAIR:   '#60A5FA',
  ESCALATE: '#C084FC',
};

const RISK_COLORS = {
  LOW:    { bar: '#4ADE80', label: '#27500A', bg: '#EAF3DE' },
  MEDIUM: { bar: '#FBBF24', label: '#633806', bg: '#FAEEDA' },
  HIGH:   { bar: '#F87171', label: '#791F1F', bg: '#FCEBEB' },
};

function RiskBar({ label, count, total, colors }) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
        <span style={{
          fontSize: 12, fontWeight: 600, color: colors.label,
          background: colors.bg, padding: '2px 8px', borderRadius: 999,
        }}>{label}</span>
        <span style={{ fontSize: 12, color: '#8A8AAA' }}>{pct}% &nbsp;<span style={{ color: '#4B5563' }}>({count})</span></span>
      </div>
      <div style={{ height: 7, background: '#2D2B45', borderRadius: 99, overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${pct}%`, background: colors.bar,
          borderRadius: 99, transition: 'width 0.6s ease',
        }} />
      </div>
    </div>
  );
}

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div style={{ background: '#1A1828', border: '1px solid #3D3B55', borderRadius: 8, padding: '8px 12px' }}>
      <div style={{ fontWeight: 600, color: '#E2E0F0', fontSize: 13 }}>{d.name}</div>
      <div style={{ color: '#A0A0B0', fontSize: 12 }}>{d.value} requests ({d.pct}%)</div>
    </div>
  );
};

export default function ChartsRow() {
  const [metrics, setMetrics] = useState(null);
  const timerRef = useRef(null);

  const fetchMetrics = async () => {
    try {
      const res = await fetch(`${API_BASE}/metrics?period=24h`, { headers: TENANT_HEADERS });
      if (res.ok) setMetrics(await res.json());
    } catch {}
  };

  useEffect(() => {
    fetchMetrics();
    timerRef.current = setInterval(fetchMetrics, 30000);
    return () => clearInterval(timerRef.current);
  }, []);

  const actions = metrics?.actions ?? {};
  const risk = metrics?.risk_distribution ?? {};
  const total = metrics?.total_requests ?? 0;
  const riskTotal = (risk.LOW ?? 0) + (risk.MEDIUM ?? 0) + (risk.HIGH ?? 0) || 1;

  const pieData = Object.entries(actions)
    .filter(([k]) => k !== 'total' && actions[k] > 0)
    .map(([name, value]) => ({
      name,
      value,
      pct: total > 0 ? Math.round((value / total) * 100) : 0,
    }));

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      {/* Actions Pie Chart */}
      <div style={{
        background: 'rgba(26,24,40,0.85)',
        border: '1px solid rgba(83,74,183,0.2)',
        borderRadius: 12,
        padding: '20px 22px',
      }}>
        <h3 style={{ fontSize: 13, fontWeight: 600, color: '#8A8AAA', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 6 }}>
          <BarChart2 size={13} style={{ color: '#A78BFA' }} />
          ACTIONS BREAKDOWN
        </h3>
        {pieData.length === 0 ? (
          <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#4B5563', fontSize: 13 }}>
            No data yet — run some requests
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={80}
                paddingAngle={3}
                dataKey="value"
              >
                {pieData.map((entry) => (
                  <Cell key={entry.name} fill={ACTION_PIE_COLORS[entry.name] || '#8B8BA0'} />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
              <Legend
                formatter={(value) => <span style={{ color: '#A0A0B0', fontSize: 11 }}>{value}</span>}
                iconSize={8}
              />
            </PieChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Risk Distribution */}
      <div style={{
        background: 'rgba(26,24,40,0.85)',
        border: '1px solid rgba(83,74,183,0.2)',
        borderRadius: 12,
        padding: '20px 22px',
      }}>
        <h3 style={{ fontSize: 13, fontWeight: 600, color: '#8A8AAA', marginBottom: 20, display: 'flex', alignItems: 'center', gap: 6 }}>
          <BarChart2 size={13} style={{ color: '#A78BFA' }} />
          RISK DISTRIBUTION
        </h3>
        <RiskBar label="LOW"    count={risk.LOW ?? 0}    total={riskTotal} colors={RISK_COLORS.LOW} />
        <RiskBar label="MEDIUM" count={risk.MEDIUM ?? 0} total={riskTotal} colors={RISK_COLORS.MEDIUM} />
        <RiskBar label="HIGH"   count={risk.HIGH ?? 0}   total={riskTotal} colors={RISK_COLORS.HIGH} />
        {total === 0 && (
          <div style={{ marginTop: 16, color: '#4B5563', fontSize: 13, textAlign: 'center' }}>
            No data yet — run some requests
          </div>
        )}
      </div>
    </div>
  );
}
