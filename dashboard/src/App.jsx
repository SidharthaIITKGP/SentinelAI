import { useState } from 'react';
import { Shield } from 'lucide-react';
import MetricsPanel from './components/MetricsPanel.jsx';
import ChartsRow from './components/ChartsRow.jsx';
import LiveFeed from './components/LiveFeed.jsx';
import RiskPanel from './components/RiskPanel.jsx';
import AuditLog from './components/AuditLog.jsx';
import PolicyToggle from './components/PolicyToggle.jsx';

const NAV_TABS = ['Overview', 'Audit Log'];

// ─── Top Bar ──────────────────────────────────────────────────────────────────
function TopBar() {
  return (
    <header style={{
      height: 52,
      background: 'rgba(15,14,26,0.95)',
      borderBottom: '1px solid rgba(83,74,183,0.2)',
      display: 'flex',
      alignItems: 'center',
      padding: '0 24px',
      gap: 12,
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      zIndex: 100,
      backdropFilter: 'blur(12px)',
    }}>
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
        <div style={{
          width: 28,
          height: 28,
          background: 'linear-gradient(135deg, #534AB7, #A78BFA)',
          borderRadius: 7,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}>
          <Shield size={14} color="#fff" />
        </div>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#E2E0F0', lineHeight: 1.1 }}>
            SentinelAI
          </div>
          <div style={{ fontSize: 10, color: '#6B7280', lineHeight: 1 }}>
            Governance Control Plane
          </div>
        </div>
      </div>

      {/* Separator */}
      <div style={{ width: 1, height: 24, background: 'rgba(83,74,183,0.25)', margin: '0 8px' }} />

      <span style={{ fontSize: 12, color: '#8A8AAA', fontWeight: 400 }}>
        Real-time AI Governance
      </span>

      {/* Right side */}
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
        {/* Live indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div className="animate-pulse-dot" style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: '#4ADE80',
            boxShadow: '0 0 6px rgba(74,222,128,0.6)',
          }} />
          <span style={{ fontSize: 11, color: '#4ADE80', fontWeight: 600 }}>Live</span>
        </div>

        {/* Tenant badge */}
        <div style={{
          background: 'rgba(83,74,183,0.2)',
          border: '1px solid rgba(83,74,183,0.3)',
          borderRadius: 6,
          padding: '3px 10px',
          fontSize: 11,
          color: '#A78BFA',
          fontWeight: 500,
        }}>
          acme_corp
        </div>
      </div>
    </header>
  );
}

// ─── App ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [activeTab, setActiveTab] = useState(0);
  const [selectedRow, setSelectedRow] = useState(null);

  return (
    <div style={{ minHeight: '100vh', background: '#0F0E1A' }}>
      <TopBar />

      {/* Nav tabs */}
      <div style={{
        marginTop: 52,
        borderBottom: '1px solid rgba(83,74,183,0.12)',
        background: 'rgba(15,14,26,0.8)',
        position: 'sticky',
        top: 52,
        zIndex: 90,
        backdropFilter: 'blur(8px)',
      }}>
        <div style={{ maxWidth: 1440, margin: '0 auto', padding: '0 24px', display: 'flex', gap: 0 }}>
          {NAV_TABS.map((tab, idx) => (
            <button
              key={tab}
              id={`nav-tab-${tab.toLowerCase().replace(' ', '-')}`}
              onClick={() => setActiveTab(idx)}
              style={{
                background: 'none',
                border: 'none',
                borderBottom: activeTab === idx ? '2px solid #534AB7' : '2px solid transparent',
                color: activeTab === idx ? '#E2E0F0' : '#6B7280',
                padding: '12px 20px',
                fontSize: 13,
                fontWeight: activeTab === idx ? 600 : 400,
                cursor: 'pointer',
                transition: 'all 0.15s',
                fontFamily: 'Inter, sans-serif',
              }}
              onMouseEnter={e => { if (activeTab !== idx) e.currentTarget.style.color = '#A0A0B0'; }}
              onMouseLeave={e => { if (activeTab !== idx) e.currentTarget.style.color = '#6B7280'; }}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Main content */}
      <main style={{ maxWidth: 1440, margin: '0 auto', padding: '24px 24px 40px' }}>

        {activeTab === 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {/* Metrics cards */}
            <MetricsPanel />

            {/* Charts row */}
            <ChartsRow />

            {/* Live Feed + Policy side-by-side */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 380px', gap: 16 }}>
              <LiveFeed onRowClick={setSelectedRow} />
              <PolicyToggle />
            </div>

            {/* Risk Panel — shows when row is selected */}
            {selectedRow && (
              <div className="animate-fade-in">
                <RiskPanel selectedRow={selectedRow} />
              </div>
            )}
            {!selectedRow && (
              <RiskPanel selectedRow={null} />
            )}
          </div>
        )}

        {activeTab === 1 && (
          <AuditLog />
        )}
      </main>
    </div>
  );
}