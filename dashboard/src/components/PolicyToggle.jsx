import { useState } from 'react';
import { Settings, Play, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import { RiskBadge, ActionBadge, API_BASE } from './shared.jsx';

const USE_CASES = [
  {
    id: 'customer_chatbot',
    label: 'Customer Chatbot',
    blockThreshold: 0.75,
    escalateThreshold: 0.60,
    piiRedaction: 'Always',
    biasTolerance: 'Zero',
    groundednessMin: 0.50,
    latencyBudget: '500ms',
    color: '#60A5FA',
  },
  {
    id: 'hr_copilot',
    label: 'HR Copilot',
    blockThreshold: 0.85,
    escalateThreshold: 0.75,
    piiRedaction: 'Conditional',
    biasTolerance: 'Low',
    groundednessMin: 0.50,
    latencyBudget: '1000ms',
    color: '#A78BFA',
  },
  {
    id: 'finance_tool',
    label: 'Finance Tool',
    blockThreshold: 0.70,
    escalateThreshold: 0.55,
    piiRedaction: 'Always',
    biasTolerance: 'Zero',
    groundednessMin: 0.52,
    latencyBudget: '2000ms',
    color: '#34D399',
  },
];

const DEMO_PROMPT = 'What is the return policy?';

function PolicyRow({ label, value, highlight }) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '8px 0',
      borderBottom: '1px solid rgba(83,74,183,0.08)',
    }}>
      <span style={{ fontSize: 12, color: '#8A8AAA' }}>{label}</span>
      <span style={{
        fontSize: 12,
        fontWeight: 600,
        color: highlight ? '#A78BFA' : '#E2E0F0',
        background: highlight ? 'rgba(83,74,183,0.15)' : 'transparent',
        padding: highlight ? '2px 8px' : '0',
        borderRadius: highlight ? 6 : 0,
      }}>{value}</span>
    </div>
  );
}

export default function PolicyToggle() {
  const [activeTab, setActiveTab] = useState(0);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const [promptText, setPromptText] = useState('What is the return policy?');

  const policy = USE_CASES[activeTab];

  const runTest = async () => {
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/intercept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: promptText,
          use_case: policy.id,
          tenant_id: 'acme_corp',
          user_id: 'demo',
        }),
      });
      if (!res.ok) {
        const err = await res.text();
        throw new Error(`${res.status}: ${err}`);
      }
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      background: 'rgba(26,24,40,0.85)',
      border: '1px solid rgba(83,74,183,0.2)',
      borderRadius: 12,
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 20px',
        borderBottom: '1px solid rgba(83,74,183,0.15)',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}>
        <Settings size={14} style={{ color: '#A78BFA' }} />
        <h3 style={{ fontSize: 13, fontWeight: 600, color: '#8A8AAA', letterSpacing: '0.06em' }}>
          POLICY CONFIGURATION
        </h3>
      </div>

      {/* Tabs */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid rgba(83,74,183,0.12)',
        background: 'rgba(15,14,26,0.4)',
      }}>
        {USE_CASES.map((uc, idx) => (
          <button
            key={uc.id}
            id={`policy-tab-${uc.id}`}
            onClick={() => { setActiveTab(idx); setResult(null); setError(null); }}
            style={{
              flex: 1,
              padding: '12px',
              background: 'none',
              border: 'none',
              borderBottom: activeTab === idx ? `2px solid #534AB7` : '2px solid transparent',
              color: activeTab === idx ? '#E2E0F0' : '#6B7280',
              fontSize: 12,
              fontWeight: activeTab === idx ? 600 : 400,
              cursor: 'pointer',
              transition: 'all 0.15s',
              fontFamily: 'Inter, sans-serif',
            }}
            onMouseEnter={e => { if (activeTab !== idx) e.currentTarget.style.color = '#A0A0B0'; }}
            onMouseLeave={e => { if (activeTab !== idx) e.currentTarget.style.color = '#6B7280'; }}
          >
            {uc.label}
          </button>
        ))}
      </div>

      <div style={{ padding: '20px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          {/* Policy thresholds */}
          <div>
            <div style={{ fontSize: 11, color: '#6B7280', fontWeight: 500, marginBottom: 12, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              Thresholds
            </div>
            <PolicyRow label="Block Threshold"     value={policy.blockThreshold.toFixed(2)}    highlight />
            <PolicyRow label="Escalate Threshold"  value={policy.escalateThreshold.toFixed(2)} highlight />
            <PolicyRow label="Groundedness Min"    value={policy.groundednessMin.toFixed(2)}   highlight />
            <PolicyRow label="Latency Budget"      value={policy.latencyBudget} />
          </div>
          <div>
            <div style={{ fontSize: 11, color: '#6B7280', fontWeight: 500, marginBottom: 12, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              Checks
            </div>
            <PolicyRow label="PII Redaction"  value={policy.piiRedaction} />
            <PolicyRow label="Bias Tolerance" value={policy.biasTolerance} />
            <PolicyRow label="PII Check"      value="✓ Enabled" />
            <PolicyRow label="Groundedness"   value="✓ Enabled" />
          </div>
        </div>

        {/* Demo prompt display */}
        <div style={{
          marginTop: 16,
          display: 'flex',
          flexDirection: 'column',
          gap: 6
        }}>
          <label style={{ fontSize: 11, color: '#6B7280', fontWeight: 500, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
            Demo Prompt
          </label>
          <textarea
            value={promptText}
            onChange={(e) => setPromptText(e.target.value)}
            rows={2}
            style={{
              width: '100%',
              padding: '10px 14px',
              background: '#0F0E1A',
              border: '1px solid rgba(83,74,183,0.3)',
              borderRadius: 8,
              fontSize: 13,
              color: '#C4C2D8',
              outline: 'none',
              resize: 'vertical',
              fontFamily: 'inherit',
              transition: 'border-color 0.15s',
            }}
            onFocus={(e) => e.target.style.borderColor = '#534AB7'}
            onBlur={(e) => e.target.style.borderColor = 'rgba(83,74,183,0.3)'}
          />
        </div>

        {/* Test button */}
        <button
          id="policy-test-btn"
          onClick={runTest}
          disabled={loading}
          style={{
            marginTop: 16,
            width: '100%',
            background: loading ? '#3D3B55' : '#534AB7',
            border: 'none',
            borderRadius: 8,
            padding: '11px',
            color: '#fff',
            fontSize: 13,
            fontWeight: 600,
            cursor: loading ? 'default' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            transition: 'background 0.15s',
            fontFamily: 'Inter, sans-serif',
          }}
          onMouseEnter={e => { if (!loading) e.currentTarget.style.background = '#6B62C9'; }}
          onMouseLeave={e => { if (!loading) e.currentTarget.style.background = '#534AB7'; }}
        >
          {loading ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={14} />}
          {loading ? 'Running governance pipeline…' : 'Test this policy'}
        </button>

        {/* Result display */}
        {error && (
          <div style={{
            marginTop: 14,
            padding: '12px 14px',
            background: 'rgba(248,113,113,0.1)',
            border: '1px solid rgba(248,113,113,0.3)',
            borderRadius: 8,
            display: 'flex',
            alignItems: 'flex-start',
            gap: 8,
          }}>
            <XCircle size={14} style={{ color: '#F87171', flexShrink: 0, marginTop: 1 }} />
            <div style={{ fontSize: 12, color: '#F87171' }}>{error}</div>
          </div>
        )}

        {result && (
          <div className="animate-fade-in" style={{
            marginTop: 14,
            padding: '14px',
            background: 'rgba(83,74,183,0.08)',
            border: '1px solid rgba(83,74,183,0.25)',
            borderRadius: 8,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <CheckCircle size={14} style={{ color: '#4ADE80' }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: '#E2E0F0' }}>Governance result</span>
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                <RiskBadge level={result.risk_level} />
                <ActionBadge action={result.action_taken} />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 10, color: '#6B7280', marginBottom: 2 }}>Risk Score</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#A78BFA' }}>
                  {((result.risk_score ?? 0) * 100).toFixed(1)}%
                </div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: '#6B7280', marginBottom: 2 }}>Latency</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#60A5FA' }}>
                  {result.latency_ms}ms
                </div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: '#6B7280', marginBottom: 2 }}>Governed</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#4ADE80' }}>
                  {result.governed ? '✓ Yes' : '✗ No'}
                </div>
              </div>
            </div>

            <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 4 }}>Response:</div>
            <div style={{
              fontSize: 12,
              color: '#C4C2D8',
              background: '#0F0E1A',
              padding: '10px 12px',
              borderRadius: 6,
              lineHeight: 1.6,
              maxHeight: 100,
              overflow: 'auto',
            }}>
              {result.final_response || '—'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}