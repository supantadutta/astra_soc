import * as Icons from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: keyof typeof Icons;
  permission?: string;
  group: string;
}

export const NAV: NavItem[] = [
  { href: "/dashboard", label: "SOC Overview", icon: "LayoutDashboard", group: "Operate", permission: "incident:read" },
  { href: "/alerts", label: "Alerts", icon: "Siren", group: "Operate", permission: "alert:read" },
  { href: "/incidents", label: "Incidents", icon: "AlertTriangle", group: "Operate", permission: "incident:read" },
  { href: "/entities", label: "Entity Graph", icon: "Network", group: "Investigate", permission: "entity:read" },
  { href: "/attack-paths", label: "Attack-Path Explorer", icon: "GitBranch", group: "Investigate", permission: "entity:read" },
  { href: "/timeline", label: "Evidence Timeline", icon: "ListTree", group: "Investigate", permission: "incident:read" },
  { href: "/agents", label: "Agent Command Center", icon: "Bot", group: "Investigate", permission: "agent:read" },
  { href: "/query", label: "Query Workbench", icon: "Search", group: "Investigate", permission: "query:run" },
  { href: "/threat-intel", label: "Threat Intelligence", icon: "Globe", group: "Investigate", permission: "threatintel:read" },
  { href: "/detections", label: "Detection Engineering", icon: "Radar", group: "Engineer", permission: "detection:read" },
  { href: "/playbooks", label: "Automation Playbooks", icon: "Workflow", group: "Engineer", permission: "playbook:read" },
  { href: "/knowledge", label: "Knowledge & Memory", icon: "BrainCircuit", group: "Engineer", permission: "knowledge:read" },
  { href: "/response", label: "Response Actions", icon: "Zap", group: "Respond", permission: "approval:read" },
  { href: "/approvals", label: "Approval Center", icon: "ClipboardCheck", group: "Respond", permission: "approval:read" },
  { href: "/reports", label: "Reports", icon: "FileText", group: "Respond", permission: "report:read" },
  { href: "/models", label: "AI Model Operations", icon: "Cpu", group: "Platform", permission: "model:read" },
  { href: "/connectors", label: "Integrations", icon: "Boxes", group: "Platform", permission: "connector:read" },
  { href: "/learning", label: "Controlled Learning", icon: "FlaskConical", group: "Platform", permission: "feedback:write" },
  { href: "/performance", label: "Analyst Performance", icon: "Activity", group: "Platform", permission: "report:read" },
  { href: "/platform-health", label: "Platform Health", icon: "Database", group: "Platform", permission: "health:read" },
  { href: "/audit", label: "Audit Logs", icon: "ScrollText", group: "Govern", permission: "audit:read" },
  { href: "/rbac", label: "RBAC", icon: "Lock", group: "Govern", permission: "rbac:manage" },
  { href: "/tenants", label: "Tenant Management", icon: "Layers", group: "Govern", permission: "tenant:manage" },
  { href: "/settings", label: "System Settings", icon: "Settings", group: "Govern", permission: "settings:manage" },
  { href: "/demo", label: "Demo Control Center", icon: "FlaskConical", group: "Govern", permission: "demo:manage" },
];

export const NAV_GROUPS = ["Operate", "Investigate", "Engineer", "Respond", "Platform", "Govern"];
