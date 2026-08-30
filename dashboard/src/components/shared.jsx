// Risk and Action badge helpers — shared across components
export const RISK_COLORS = {
  LOW:    { bg: '#EAF3DE', text: '#27500A' },
  MEDIUM: { bg: '#FAEEDA', text: '#633806' },
  HIGH:   { bg: '#FCEBEB', text: '#791F1F' },
};

export const ACTION_COLORS = {
  ALLOW:    { bg: '#EAF3DE', text: '#27500A' },
  REDACT:   { bg: '#FAEEDA', text: '#633806' },
  BLOCK:    { bg: '#FCEBEB', text: '#791F1F' },
  REPAIR:   { bg: '#E6F1FB', text: '#0C447C' },
  ESCALATE: { bg: '#EEEDFE', text: '#3C3489' },
};

export function RiskBadge({ level }) {
  const c = RISK_COLORS[level] || { bg: '#2D2B45', text: '#A0A0B0' };
  return (
    <span style={{
      backgroundColor: c.bg,
      color: c.text,
      padding: '2px 8px',
      borderRadius: '9999px',
      fontSize: '11px',
      fontWeight: 600,
      letterSpacing: '0.04em',
      display: 'inline-block',
      lineHeight: '1.6',
    }}>
      {level}
    </span>
  );
}

export function ActionBadge({ action }) {
  const c = ACTION_COLORS[action] || { bg: '#2D2B45', text: '#A0A0B0' };
  return (
    <span style={{
      backgroundColor: c.bg,
      color: c.text,
      padding: '2px 8px',
      borderRadius: '9999px',
      fontSize: '11px',
      fontWeight: 600,
      letterSpacing: '0.04em',
      display: 'inline-block',
      lineHeight: '1.6',
    }}>
      {action}
    </span>
  );
}

export function formatTs(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch { return iso; }
}

export const API_BASE = import.meta.env.VITE_API_URL || '';
const tenantApiKey = import.meta.env.VITE_SENTINEL_API_KEY || '';
export const TENANT_HEADERS = tenantApiKey
  ? { 'X-Sentinel-API-Key': tenantApiKey }
  : {};
