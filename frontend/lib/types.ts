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
  status: "new" | "contacted" | "qualified" | "rejected";
  source_url: string;
  source?: "yandex_maps" | "2gis" | "rusprofile" | "searxng" | "bing" | "maps_searxng" | "";
  external_id?: string;
  enriched: boolean;
  demo?: boolean;
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
