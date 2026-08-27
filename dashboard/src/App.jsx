import React, { useState } from 'react';
import LiveFeed from './components/LiveFeed';
import RiskPanel from './components/RiskPanel';
import AuditLog from './components/AuditLog';
import PolicyToggle from './components/PolicyToggle';
import MetricsPanel from './components/MetricsPanel';
import { ShieldCheck } from 'lucide-react';

function App() {
  const [selectedLog, setSelectedLog] = useState(null);
  const [activeTab, setActiveTab] = useState('live'); // 'live' or 'audit'

  return (
    <div className="min-h-screen bg-slate-950 text-slate-50 font-sans p-4 md:p-8">
      {/* Header */}
      <header className="flex items-center justify-between mb-8 pb-4 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="bg-primary/20 p-2 rounded-lg border border-primary/30">
            <ShieldCheck className="text-primary" size={28} />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">
              SentinelAI
            </h1>
            <p className="text-xs text-slate-400">Enterprise AI Governance Platform</p>
          </div>
        </div>
        <div className="flex gap-4">
          <button 
            onClick={() => setActiveTab('live')}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === 'live' ? 'bg-primary text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'}`}
          >
            Live Monitor
          </button>
          <button 
            onClick={() => setActiveTab('audit')}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === 'audit' ? 'bg-primary text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'}`}
          >
            Audit Log
          </button>
        </div>
      </header>

      {/* Top Metrics Panel */}
      <MetricsPanel />

      {/* Main Content Area */}
      {activeTab === 'live' ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-[600px]">
          <div className="lg:col-span-2 flex flex-col gap-6">
            <div className="h-2/3">
              <LiveFeed onSelectRow={setSelectedLog} />
            </div>
            <div className="h-1/3">
              <PolicyToggle />
            </div>
          </div>
          <div className="h-full">
            {selectedLog ? (
              <RiskPanel log={selectedLog} onClose={() => setSelectedLog(null)} />
            ) : (
              <div className="glass-card h-full flex items-center justify-center text-slate-500 border-dashed border-2 border-slate-700">
                <div className="text-center p-6">
                  <ShieldCheck size={48} className="mx-auto mb-4 text-slate-700" />
                  <p>Select a request from the live feed to view detailed risk analysis.</p>
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="h-[600px]">
          <AuditLog />
        </div>
      )}
    </div>
  );
}

export default App;
