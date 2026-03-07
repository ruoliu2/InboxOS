create table if not exists users (
  id text primary key,
  primary_email text unique,
  display_name text,
  avatar_url text,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create table if not exists linked_accounts (
  id text primary key,
  user_id text not null,
  provider text not null,
  provider_account_id text not null,
  provider_account_ref text,
  display_name text,
  avatar_url text,
  status text not null,
  capabilities_json text not null,
  metadata_json text not null,
  last_synced_at timestamptz,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  unique (provider, provider_account_id)
);

create table if not exists provider_credentials (
  linked_account_id text primary key,
  access_token_encrypted text not null,
  refresh_token_encrypted text,
  scope text,
  expires_at timestamptz,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create table if not exists oauth_flows (
  state text primary key,
  provider text not null,
  intent text not null,
  user_id text,
  redirect_to text not null,
  pkce_verifier text,
  requested_scopes_json text not null,
  expires_at timestamptz not null,
  consumed_at timestamptz,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create table if not exists app_sessions (
  session_id text primary key,
  user_id text not null,
  active_linked_account_id text,
  session_expires_at timestamptz not null,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create table if not exists conversations (
  id text primary key,
  user_id text not null,
  linked_account_id text not null,
  provider text not null,
  external_conversation_id text not null,
  title text not null,
  preview text not null,
  last_message_at timestamptz not null,
  source_folder text,
  status text not null,
  metadata_json text not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  unique (linked_account_id, external_conversation_id)
);

create table if not exists conversation_insights (
  conversation_id text primary key,
  summary text,
  action_items_json text not null,
  deadlines_json text not null,
  requested_items_json text not null,
  recommended_next_action text,
  action_states_json text not null,
  analyzed_at timestamptz,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create table if not exists tasks (
  id text primary key,
  user_id text not null,
  title text not null,
  status text not null,
  due_at timestamptz,
  linked_account_id text,
  conversation_id text,
  thread_id text,
  category text,
  created_at timestamptz not null,
  completed_at timestamptz,
  updated_at timestamptz not null
);

create index if not exists idx_linked_accounts_user
  on linked_accounts (user_id, created_at asc);

create index if not exists idx_oauth_flows_expires
  on oauth_flows (expires_at);

create index if not exists idx_tasks_user_created
  on tasks (user_id, created_at desc);

create index if not exists idx_tasks_user_conversation_status
  on tasks (user_id, conversation_id, status);
