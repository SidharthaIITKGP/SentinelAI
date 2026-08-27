import React from 'react';
import { X, ShieldAlert, CheckCircle, AlertTriangle } from 'lucide-react';
import clsx from 'clsx';

const ACTION_COLORS = {
  ALLOW: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  REDACT: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  BLOCK: 'text-red-400 bg-red-500/10 border-red-500/20',
  REPAIR: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
  ESCALATE: 'text-purple-400 bg-purple-500/10 border-purple-500/20'
};

export default function RiskPanel({ log, onClose }) {
  if (!log) return null;

  const action = log.action?.action_taken || 'ALLOW';
  const riskScore = log.risk_score?.score || 0;
  const breakdown = log.risk_score?.breakdown || {};

  return (
    <div className="glass-card flex flex-col h-full animate-fade-in relative border-l-4" 
         style={{ animationDelay: '0.2s', borderLeftColor: action === 'BLOCK' ? '#ef4444' : action === 'ALLOW' ? '#10b981' : '#f59e0b' }}>
      <button 
        onClick={onClose}
        className="absolute top-4 right-4 p-1 rounded-md text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
      >
        <X size={20} />
      </button>

      <div className="p-5 border-b border-slate-700">
        <h2 className="text-lg font-semibold text-slate-100 mb-1">Request Detail</h2>
        <div className="text-xs text-slate-400 font-mono">ID: {log.request_id}</div>
      </div>

      <div className="p-5 flex-1 overflow-auto space-y-6">
        
        {/* Action Taken Header */}
        <div className={clsx("p-4 rounded-lg border flex items-start gap-4", ACTION_COLORS[action])}>
          <div className="mt-1">
            {action === 'BLOCK' ? <ShieldAlert size={24} /> : (action === 'ALLOW' ? <CheckCircle size={24} /> : <AlertTriangle size={24} />)}
          </div>
          <div>
            <div className="font-bold text-lg">{action}</div>
            <div className="text-sm opacity-90 mt-1">
              {log.action?.evidence?.reason || "No explicit reason provided."}
            </div>
          </div>
        </div>

        {/* IO Content */}
        <div className="space-y-4">
          <div>
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Original Prompt</h3>
            <div className="p-3 bg-slate-900/50 rounded border border-slate-700/50 text-slate-200 text-sm whitespace-pre-wrap">
              {log.prompt}
            </div>
          </div>
          
          <div>
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Final Response</h3>
            <div className="p-3 bg-slate-900/50 rounded border border-slate-700/50 text-slate-200 text-sm whitespace-pre-wrap">
              {log.final_response}
            </div>
          </div>
        </div>

        {/* Risk Breakdown */}
        <div>
          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Risk Assessment (Score: {riskScore})</h3>
          <div className="space-y-3">
            {Object.entries(breakdown).map(([key, val]) => (
              <div key={key}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-slate-300 capitalize">{key.replace('_', ' ')}</span>
                  <span className="text-slate-400">{val}</span>
                </div>
                <div className="w-full bg-slate-800 rounded-full h-1.5">
                  <div 
                    className={clsx("h-1.5 rounded-full", val > 0.7 ? "bg-red-500" : val > 0.4 ? "bg-amber-500" : "bg-emerald-500")}
                    style={{ width: `${Math.min(100, Math.max(0, val * 100))}%` }}
                  ></div>
                </div>
              </div>
            ))}
            {Object.keys(breakdown).length === 0 && (
              <div className="text-sm text-slate-500 italic">No breakdown available.</div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
