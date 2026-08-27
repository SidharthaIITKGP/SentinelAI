import React, { useState, useEffect } from 'react';
import { Shield, ShieldAlert, ShieldCheck, AlertCircle } from 'lucide-react';
import clsx from 'clsx';

const RISK_BADGE = {
  LOW: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  MEDIUM: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  HIGH: 'bg-red-500/20 text-red-400 border-red-500/30'
};

const ACTION_TAG = {
  ALLOW: 'bg-emerald-500/20 text-emerald-400',
  REDACT: 'bg-amber-500/20 text-amber-400',
  BLOCK: 'bg-red-500/20 text-red-400',
  REPAIR: 'bg-blue-500/20 text-blue-400',
  ESCALATE: 'bg-purple-500/20 text-purple-400'
};

export default function LiveFeed({ onSelectRow }) {
  const [logs, setLogs] = useState([]);

  useEffect(() => {
    const fetchLogs = async () => {
      try {
        const res = await fetch('/audit/recent?limit=20');
        if (res.ok) {
          const data = await res.json();
          setLogs(data);
        }
      } catch (err) {
        console.error('Failed to fetch live feed', err);
      }
    };

    fetchLogs();
    const interval = setInterval(fetchLogs, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="glass-card flex flex-col h-full animate-fade-in" style={{ animationDelay: '0.1s' }}>
      <div className="p-5 border-b border-slate-700 flex justify-between items-center">
        <h2 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
          Live Intercept Feed
        </h2>
      </div>
      <div className="overflow-auto flex-1 p-0">
        <table className="w-full text-left border-collapse text-sm">
          <thead className="bg-slate-800/50 sticky top-0 z-10 backdrop-blur-sm">
            <tr>
              <th className="p-4 text-slate-400 font-medium">Time</th>
              <th className="p-4 text-slate-400 font-medium">Use Case</th>
              <th className="p-4 text-slate-400 font-medium">Risk Level</th>
              <th className="p-4 text-slate-400 font-medium">Action Taken</th>
              <th className="p-4 text-slate-400 font-medium">Latency</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {logs.map((log) => (
              <tr 
                key={log.request_id} 
                onClick={() => onSelectRow(log)}
                className="hover:bg-slate-700/30 cursor-pointer transition-colors"
              >
                <td className="p-4 text-slate-300 font-mono text-xs whitespace-nowrap">
                  {new Date(log.timestamp).toLocaleTimeString()}
                </td>
                <td className="p-4 text-slate-200">
                  {log.use_case.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())}
                </td>
                <td className="p-4">
                  <span className={clsx("px-2.5 py-1 rounded-full text-xs font-semibold border flex items-center gap-1.5 w-max", RISK_BADGE[log.risk_score?.level || 'LOW'])}>
                    {log.risk_score?.level === 'HIGH' ? <ShieldAlert size={14}/> : (log.risk_score?.level === 'MEDIUM' ? <AlertCircle size={14}/> : <ShieldCheck size={14}/>)}
                    {log.risk_score?.level}
                  </span>
                </td>
                <td className="p-4">
                  <span className={clsx("px-2.5 py-1 rounded-full text-xs font-semibold uppercase tracking-wider", ACTION_TAG[log.action?.action_taken || 'ALLOW'])}>
                    {log.action?.action_taken}
                  </span>
                </td>
                <td className="p-4 text-slate-400 font-mono text-xs">
                  {log.latency_ms}ms
                </td>
              </tr>
            ))}
            {logs.length === 0 && (
              <tr>
                <td colSpan="5" className="p-8 text-center text-slate-500">
                  Waiting for requests...
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
