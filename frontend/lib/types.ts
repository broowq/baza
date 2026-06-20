export type Plan = "starter" | "pro" | "team";

export type Organization = {
  id: string;
  name: string;
  plan: Plan;
  leads_used_current_month: number;
  leads_limit_per_month: number;
  projects_limit: number;
  users_limit: number;
  can_invite_members: boolean;
  lead_webhook_url?: string;
  // Per-org monthly AI/LLM spend cap. Both values are in kopecks (₽ × 100)
  // so the API stays integer end-to-end; UI divides by 100 for display.
  ai_cost_used_kopecks_current_month?: number;
  ai_cost_limit_kopecks_per_month?: number;
};

export type OkvedCode = {
  code: string;
  label: string;
  confidence: number;
};

export type Project = {
  id: string;
  name: string;
  prompt?: string;
  niche: string;
  geography: string;
  segments: string[];
  okved_codes?: OkvedCode[];
  cron_schedule: string;
  auto_collection_enabled: boolean;
};

export type PromptEnhanceResponse = {
  enhanced_prompt: string;
  project_name: string;
  niche: string;
  geography: string;
  segments: string[];
  okved_codes?: OkvedCode[];
  target_customer_types: string[];
  search_queries_niche: string;
  explanation: string;
};

export type Lead = {
  id: string;
  company: string;
  city: string;
  website: string;
  email: string;
  email_status?: "" | "valid" | "no_mx" | "syntax" | "skipped";
  phone: string;
  address: string;
  contacts: Record<string, unknown>;
  contacts_json: Record<string, unknown>;
  domain?: string;
  score: number;
  notes: string;
  tags?: string[];
  last_contacted_at?: string | null;
  reminder_at?: string | null;
  status: LeadStatus;
  // CRM fields
  assigned_to_user_id?: string | null;
  deal_value?: number;
  expected_close_at?: string | null;
  source_url: string;
  source?: "yandex_maps" | "2gis" | "rusprofile" | "searxng" | "bing" | "maps_searxng" | "";
  external_id?: string;
  enriched: boolean;
  demo?: boolean;
};

/* ── CRM ──────────────────────────────────────────────────────────── */

export type LeadStatus = "new" | "contacted" | "qualified" | "proposal" | "won" | "rejected";

export type PipelineStage = {
  key: LeadStatus;
  label: string;
  terminal: boolean;
  won: boolean;
};

export type OrgMember = {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
};

export type LeadTask = {
  id: string;
  lead_id: string;
  title: string;
  due_at?: string | null;
  done: boolean;
  done_at?: string | null;
  assigned_to_user_id?: string | null;
  created_by_user_id?: string | null;
  created_at: string;
};

export type LeadTaskWithLead = LeadTask & {
  lead_company?: string;
  project_id?: string | null;
};

export type LeadActivity = {
  id: string;
  kind: string;   // created | stage_changed | assigned | unassigned | value_changed | note | contacted | call | task_created | task_done
  text: string;
  user_name: string;
  meta: Record<string, unknown>;
  created_at: string;
};

export type FunnelStage = {
  key: LeadStatus;
  label: string;
  count: number;
  value: number;
  terminal: boolean;
  won: boolean;
};

export type Funnel = {
  stages: FunnelStage[];
  total_leads: number;
  open_leads: number;
  won_count: number;
  won_value: number;
  open_value: number;
  conversion_rate: number;
};

export type LeadWarehouse = {
  found: boolean;
  company_id?: string | null;
  times_seen?: number | null;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  other_niches?: string[];
  sources?: string[];
  categories?: string[];
  best_score?: number | null;
  inn?: string | null;
  twogis_firm_id?: string | null;
};

export type LeadDetail = Lead & {
  description?: string | null;
  warehouse?: LeadWarehouse | null;
};

export type LeadCallNote = {
  id: string;
  user_id: string | null;
  user_name: string;
  comment: string;
  created_at: string;
};

export type CollectionJob = {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  kind: "collect" | "enrich";
  requested_limit: number;
  found_count: number;
  added_count: number;
  enriched_count: number;
  error?: string | null;
};

/* ── Email outreach ───────────────────────────────────────────────── */

export type OutreachSettings = {
  configured: boolean;
  from_name: string;
  from_email: string;
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password_set: boolean;
  smtp_use_tls: boolean;
  imap_host: string;
  imap_port: number;
  imap_user: string;
  imap_password_set: boolean;
  daily_limit: number;
  sent_today: number;
  verified: boolean;
};

export type SequenceStep = {
  id?: string;
  step_order?: number;
  delay_days: number;
  subject: string;
  body: string;
};

export type SequenceStats = {
  enrolled: number;
  active: number;
  completed: number;
  replied: number;
  unsubscribed: number;
  bounced: number;
  stopped: number;
  sent_messages: number;
  opened: number;
  clicked: number;
  replies: number;
};

export type OutreachReply = {
  id: string;
  lead_id?: string | null;
  lead_company: string;
  from_email: string;
  subject: string;
  snippet: string;
  received_at?: string | null;
};

export type EmailSequence = {
  id: string;
  name: string;
  status: "active" | "paused" | "archived";
  project_id?: string | null;
  created_at: string;
  steps: SequenceStep[];
  stats: SequenceStats;
};

export type SequenceEnrollment = {
  id: string;
  lead_id: string;
  lead_company: string;
  to_email: string;
  status: string;
  current_step: number;
  next_send_at?: string | null;
  last_sent_at?: string | null;
};
