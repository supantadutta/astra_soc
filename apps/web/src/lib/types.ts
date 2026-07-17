export interface Me {
  id: string;
  email: string;
  full_name: string;
  tenant_id: string;
  roles: string[];
  permissions: string[];
  is_service_account: boolean;
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
