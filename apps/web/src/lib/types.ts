export interface Me {
  id: string;
  email: string;
  full_name: string;
  tenant_id: string;
  roles: string[];
  permissions: string[];
  is_service_account: boolean;
  tenant_slug: string;
  tenant_name: string;
  tenant_kind: "provider" | "reseller" | "customer" | string;
  home_tenant_id: string;
  home_tenant_slug: string;
  home_permissions: string[];
  delegated_via: "platform" | "break_glass" | "provider" | "grant" | null;
  mfa_enabled: boolean;
  mfa_verified: boolean;
  tenant_requires_mfa: boolean;
}

/** A tenant the user may act in (drives the tenant switcher). */
export interface AccessibleTenant {
  id: string;
  name: string;
  slug: string;
  kind: string;
  status: string;
  service_tier: string;
  region: string;
  role: string;
  via: "home" | "platform" | "break_glass" | "provider" | "grant";
  branding: Record<string, any>;
  requires_mfa: boolean;
}

export interface SlaTarget {
  due: string | null;
  state: "breached" | "at_risk" | "on_track" | "met" | "n/a";
  minutes_remaining: number | null;
  completed_at?: string;
}

export interface SlaState {
  ack: SlaTarget;
  resolve: SlaTarget;
  overall: SlaTarget["state"];
  escalation_level: number;
}

export interface Notification {
  id: string;
  title: string;
  body?: string;
  level: string;
  category: string;
  link?: string;
  channel?: string;
  delivery_status?: string;
  read_at?: string | null;
  created_at: string;
}

export interface ModeState {
  mode: "DEMO" | "LIVE";
  is_live: boolean;
  changed_at?: string;
  changed_by?: string;
  ai_enabled: boolean;
  llm_strategy: string;
  degraded: boolean;
  degraded_reasons: string[];
  allow_live_mode: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface Incident {
  id: string;
  key: string;
  title: string;
  summary: string;
  severity: string;
  status: string;
  confidence: number;
  business_risk: number;
  risk_score: number;
  scenario_key?: string;
  attack_tactics: string[];
  attack_techniques: string[];
  affected_users: string[];
  affected_hosts: string[];
  related_ips: string[];
  related_domains: string[];
  created_at: string;
  updated_at: string;
  owner_id?: string;
  acknowledged_at?: string | null;
  sla?: SlaState;
}

export interface Alert {
  id: string;
  title: string;
  description: string;
  source: string;
  severity: string;
  status: string;
  risk_score: number;
  confidence: number;
  attack_techniques: string[];
  incident_id?: string;
  created_at: string;
}

export interface Evidence {
  id: string;
  kind: string;
  title: string;
  content: string;
  source: string;
  produced_by: string;
  confidence: number;
  attack_techniques: string[];
  created_at: string;
}

export interface AgentRun {
  id: string;
  agent_key: string;
  status: string;
  provider_used: string;
  simulated: boolean;
  tokens_used: number;
  model_used: string;
  output: Record<string, any>;
  created_at: string;
}
