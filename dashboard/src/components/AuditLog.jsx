import React, { useState, useEffect } from 'react';
import { Search, Filter, Download } from 'lucide-react';
import clsx from 'clsx';

export default function AuditLog() {
  const [logs, setLogs] = useState([]);
  const [filterUC, setFilterUC] = useState('ALL');
  const [filterAction, setFilterAction] = useState('ALL');
  const [search, setSearch] = useState('');

  useEffect(() => {
    // We fetch a larger chunk of logs for the full table
    const fetchLogs = async () => {
      try {
        const res = await fetch('/audit/recent?limit=100');
        if (res.ok) {
          const data = await res.json();
          setLogs(data);
        }
      } catch (err) {
        console.error('Failed to fetch full audit log', err);
      }
    };
    fetchLogs();
  }, []);

  const filteredLogs = logs.filter(log => {
    const matchUC = filterUC === 'ALL' || log.use_case === filterUC;
    const matchAction = filterAction === 'ALL' || log.action?.action_taken === filterAction;
    const matchSearch = log.prompt?.toLowerCase().includes(search.toLowerCase()) || 
                        log.request_id?.toLowerCase().includes(search.toLowerCase());
    return matchUC && matchAction && matchSearch;
  });

  const exportCSV = () => {
    const headers = "Request ID,Time,Use Case,Risk Level,Action Taken,Latency\n";
    const csv = logs.map(l => 
      `${l.request_id},${l.timestamp},${l.use_case},${l.risk_score?.level},${l.action?.action_taken},${l.latency_ms}`
    ).join("\n");
    const blob = new Blob([headers + csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'sentinel_audit_log.csv';
    a.click();
  };

  return (
    <div className="glass-card animate-fade-in flex flex-col h-full" style={{ animationDelay: '0.3s' }}>
      <div className="p-5 border-b border-slate-700 flex flex-col md:flex-row gap-4 justify-between items-start md:items-center">
        <h2 className="text-lg font-semibold text-slate-100">Full Audit Log</h2>
        
        <div className="flex flex-wrap gap-3 w-full md:w-auto">
          <div className="relative flex-1 md:w-64">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
            <input 
              type="text" 
              placeholder="Search prompt or ID..." 
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-md py-1.5 pl-9 pr-3 text-sm text-slate-200 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary"
            />
          </div>
          
          <select 
            value={filterUC} 
            onChange={(e) => setFilterUC(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded-md py-1.5 px-3 text-sm text-slate-200 focus:outline-none focus:border-primary"
          >
            <option value="ALL">All Use Cases</option>
            <option value="customer_chatbot">Customer Chatbot</option>
            <option value="hr_copilot">HR Copilot</option>
            <option value="finance_tool">Finance Tool</option>
          </select>

          <select 
            value={filterAction} 
            onChange={(e) => setFilterAction(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded-md py-1.5 px-3 text-sm text-slate-200 focus:outline-none focus:border-primary"
          >
            <option value="ALL">All Actions</option>
            <option value="ALLOW">ALLOW</option>
            <option value="REDACT">REDACT</option>
            <option value="BLOCK">BLOCK</option>
            <option value="REPAIR">REPAIR</option>
            <option value="ESCALATE">ESCALATE</option>
          </select>

          <button 
            onClick={exportCSV}
            className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 border border-slate-600 rounded-md py-1.5 px-3 text-sm text-slate-200 transition-colors"
          >
            <Download size={16} />
            Export
          </button>
        </div>
      </div>

      <div className="overflow-auto flex-1">
        <table className="w-full text-left border-collapse text-sm">
          <thead className="bg-slate-800/50 sticky top-0 z-10 backdrop-blur-sm">
            <tr>
              <th className="p-4 text-slate-400 font-medium">Time</th>
              <th className="p-4 text-slate-400 font-medium">Use Case</th>
              <th className="p-4 text-slate-400 font-medium">Action</th>
              <th className="p-4 text-slate-400 font-medium w-1/2">Prompt Snippet</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {filteredLogs.map(log => (
              <tr key={log.request_id} className="hover:bg-slate-700/20 transition-colors">
                <td className="p-4 text-slate-300 font-mono text-xs whitespace-nowrap">
                  {new Date(log.timestamp).toLocaleString()}
                </td>
                <td className="p-4 text-slate-200">
                  {log.use_case}
                </td>
                <td className="p-4 font-semibold text-slate-300">
                  {log.action?.action_taken}
                </td>
                <td className="p-4 text-slate-400 truncate max-w-xs">
                  {log.prompt?.substring(0, 60)}...
                </td>
              </tr>
            ))}
            {filteredLogs.length === 0 && (
              <tr>
                <td colSpan="4" className="p-8 text-center text-slate-500">
                  No logs found matching criteria.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
