import { Info, Cpu, Shield } from 'lucide-react';
import { RiskBadge, ActionBadge } from './shared.jsx';

function ScoreBar({ label, value }) {
  const pct = Math.round((value ?? 0) * 100);
  const color = pct > 65 ? '#F87171' : pct > 35 ? '#FBBF24' : '#4ADE80';
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: '#8A8AAA' }}>{label}</span>
        <span style={{ fontSize: 12, fontWeight: 600, color }}>{pct}%</span>
      </div>
      <div style={{ height: 5, background: '#2D2B45', borderRadius: 99, overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${pct}%`, background: color,
          borderRadius: 99, transition: 'width 0.5s ease',
        }} />
      </div>
    </div>
  );
}

export default function RiskPanel({ selectedRow }) {
  if (!selectedRow) {
    return (
      <div style={{
        background: 'rgba(26,24,40,0.85)',
        border: '1px solid rgba(83,74,183,0.2)',
        borderRadius: 12,
        padding: '24px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        minHeight: 320,
      }}>
        <Info size={32} style={{ color: '#3D3B55' }} />
        <p style={{ color: '#4B5563', fontSize: 13, textAlign: 'center' }}>
          Click a row in the Live Feed<br />to see detailed risk analysis
        </p>
      </div>
    );
  }

  const row = selectedRow;
  const breakdown = row.risk_breakdown ?? {};
  const tokensIn = 0;
  const tokensOut = row.tokens_used ?? 0;
  const llmCalled = row.model_used && row.model_used !== 'none';

  return (
    <div style={{
      background: 'rgba(26,24,40,0.85)',
      border: '1px solid rgba(83,74,183,0.2)',
      borderRadius: 12,
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '14px 20px',
        borderBottom: '1px solid rgba(83,74,183,0.15)',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}>
        <Shield size={14} style={{ color: '#A78BFA' }} />
        <h3 style={{ fontSize: 13, fontWeight: 600, color: '#8A8AAA', letterSpacing: '0.06em' }}>
          RISK ANALYSIS
        </h3>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <RiskBadge level={row.risk_level ?? 'LOW'} />
          <ActionBadge action={row.action_taken ?? 'ALLOW'} />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
        {/* LEFT */}
        <div style={{ padding: '18px 20px', borderRight: '1px solid rgba(83,74,183,0.1)' }}>
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, color: '#6B7280', fontWeight: 500, marginBottom: 6, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              Original Prompt
            </div>
            <div style={{
              background: '#0F0E1A',
              border: '1px solid rgba(83,74,183,0.1)',
              borderRadius: 8,
              padding: '10px 12px',
              fontSize: 12,
              color: '#C4C2D8',
              lineHeight: 1.6,
              maxHeight: 80,
              overflow: 'auto',
            }}>
              {row.prompt || '—'}
            </div>
          </div>

          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, color: '#6B7280', fontWeight: 500, marginBottom: 6, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              Governed Response
            </div>
            <div style={{
              background: '#0F0E1A',
              border: '1px solid rgba(83,74,183,0.1)',
              borderRadius: 8,
              padding: '10px 12px',
              fontSize: 12,
              color: '#C4C2D8',
              lineHeight: 1.6,
              maxHeight: 80,
              overflow: 'auto',
            }}>
              {row.final_response || '—'}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 3 }}>Model Used</div>
              <div style={{ fontSize: 12, color: '#A78BFA', fontFamily: 'monospace' }}>
                {llmCalled ? (row.model_used || '—') : 'none (LLM never called)'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 3 }}>Tokens</div>
              <div style={{ fontSize: 12, color: '#8A8AAA', fontFamily: 'monospace' }}>
                {tokensIn} in / {tokensOut} out
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 3 }}>Latency</div>
              <div style={{ fontSize: 12, color: '#8A8AAA', fontFamily: 'monospace' }}>
                {row.latency_ms ?? 0}ms
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 3 }}>Risk Score</div>
              <div style={{ fontSize: 12, color: '#8A8AAA', fontFamily: 'monospace' }}>
                {((row.risk_score ?? 0) * 100).toFixed(1)}%
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT */}
        <div style={{ padding: '18px 20px' }}>
          <div style={{ fontSize: 11, color: '#6B7280', fontWeight: 500, marginBottom: 14, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
            Signal Breakdown
          </div>
          <ScoreBar label="Injection Score"    value={breakdown.injection_score    ?? 0} />
          <ScoreBar label="Bias Score"         value={breakdown.bias_score          ?? 0} />
          <ScoreBar label="Groundedness Risk"  value={breakdown.groundedness_risk   ?? 0} />
          <ScoreBar label="PII (Response)"     value={breakdown.pii_response_score  ?? 0} />
          <ScoreBar label="PII (Prompt)"       value={breakdown.pii_prompt_score    ?? 0} />

          <div style={{ marginTop: 16, padding: '12px', background: '#0F0E1A', borderRadius: 8, border: '1px solid rgba(83,74,183,0.1)' }}>
            <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Evidence
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <ActionBadge action={row.action_taken ?? 'ALLOW'} />
            </div>
            <div style={{ marginTop: 8, fontSize: 11, color: '#6B7280', lineHeight: 1.6 }}>
              {llmCalled ? 'LLM called' : 'LLM never called'}
              {' · '}{tokensOut} tokens spent
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}