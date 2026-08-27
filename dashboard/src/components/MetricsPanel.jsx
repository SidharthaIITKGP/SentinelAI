import React, { useState, useEffect } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import { Activity, Clock, AlertTriangle, ShieldCheck, Zap } from 'lucide-react';

const COLORS = {
  ALLOW: '#10b981', // green
  REDACT: '#f59e0b', // yellow
  BLOCK: '#ef4444', // red
  REPAIR: '#3b82f6', // blue
  ESCALATE: '#8b5cf6' // purple
};

const MetricCard = ({ title, value, icon: Icon, subtext }) => (
  <div className="glass-card p-6 flex flex-col h-full justify-between">
    <div className="flex justify-between items-start mb-4">
      <h3 className="text-slate-400 font-medium text-sm">{title}</h3>
      <div className="p-2 bg-slate-800 rounded-lg text-primary">
        <Icon size={20} />
      </div>
    </div>
    <div>
      <div className="text-3xl font-bold text-slate-100">{value}</div>
      {subtext && <div className="text-xs text-slate-500 mt-2">{subtext}</div>}
    </div>
  </div>
);

export default function MetricsPanel() {
  const [metrics, setMetrics] = useState(null);

  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        const res = await fetch('/metrics');
        if (res.ok) {
          const data = await res.json();
          setMetrics(data);
        }
      } catch (err) {
        console.error('Failed to fetch metrics', err);
      }
    };

    fetchMetrics();
    const interval = setInterval(fetchMetrics, 30000);
    return () => clearInterval(interval);
  }, []);

  if (!metrics) return <div className="animate-pulse flex space-x-4"><div className="h-24 bg-slate-800 rounded w-full"></div></div>;

  const actionData = Object.entries(metrics.actions || {}).map(([key, value]) => ({
    name: key.toUpperCase(),
    value: value
  })).filter(d => d.value > 0);

  return (
    <div className="grid grid-cols-1 md:grid-cols-5 gap-6 mb-8 animate-fade-in">
      <MetricCard 
        title="Total Requests" 
        value={metrics.total_requests.toLocaleString()} 
        icon={Activity} 
        subtext="Past 24 hours"
      />
      
      <div className="glass-card p-4 flex flex-col items-center justify-center md:col-span-1">
        <h3 className="text-slate-400 font-medium text-sm self-start mb-2">Actions Breakdown</h3>
        <div className="h-32 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={actionData}
                innerRadius={30}
                outerRadius={50}
                paddingAngle={5}
                dataKey="value"
              >
                {actionData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[entry.name] || '#94a3b8'} />
                ))}
              </Pie>
              <Tooltip 
                contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '8px', color: '#f8fafc' }}
                itemStyle={{ color: '#e2e8f0' }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      <MetricCard 
        title="Avg Latency" 
        value={`${Math.round(metrics.avg_latency_ms)} ms`} 
        icon={Clock} 
      />

      <div className="glass-card p-6 flex flex-col justify-between">
         <div className="flex justify-between items-start mb-4">
          <h3 className="text-slate-400 font-medium text-sm">Risk Distribution</h3>
          <div className="p-2 bg-slate-800 rounded-lg text-primary">
            <AlertTriangle size={20} />
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <div className="flex justify-between items-center text-sm">
            <span className="text-emerald-400 font-medium">LOW</span>
            <span className="text-slate-300 font-bold">{metrics.risk_distribution.low || 0}</span>
          </div>
          <div className="flex justify-between items-center text-sm">
            <span className="text-amber-400 font-medium">MEDIUM</span>
            <span className="text-slate-300 font-bold">{metrics.risk_distribution.medium || 0}</span>
          </div>
          <div className="flex justify-between items-center text-sm">
            <span className="text-red-400 font-medium">HIGH</span>
            <span className="text-slate-300 font-bold">{metrics.risk_distribution.high || 0}</span>
          </div>
        </div>
      </div>

      <MetricCard 
        title="False Positives" 
        value={`${(metrics.false_positive_rate * 100).toFixed(1)}%`} 
        icon={ShieldCheck} 
        subtext="From human feedback"
      />
    </div>
  );
}
