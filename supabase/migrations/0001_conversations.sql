create table if not exists conversations (
    id uuid primary key,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    semantic_version text not null default '2.0.0',
    graph_version text not null default '1'
);

create table if not exists messages (
    id bigint generated always as identity primary key,
    conversation_id uuid not null references conversations(id) on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    created_at timestamptz not null default now()
);

create table if not exists conversation_facts (
    conversation_id uuid primary key references conversations(id) on delete cascade,
    resolved_metric text,
    filters jsonb not null default '{}'::jsonb,
    selected_relations jsonb not null default '[]'::jsonb,
    last_sql_hash text,
    result_digest text,
    expires_at timestamptz not null
);

create index if not exists conversations_expires_at_idx on conversations (expires_at);
create index if not exists messages_conversation_created_idx on messages (conversation_id, created_at);

-- Apply with a server-side migration role. The backend service key stays server-only.