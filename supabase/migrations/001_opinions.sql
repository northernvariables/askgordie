-- Opinions table: stores metadata for recorded opinion videos
create table if not exists opinions (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),

    -- Recording metadata
    device_id text not null,
    category text not null,
    duration_s integer not null,
    storage_path text not null,          -- path in Supabase Storage bucket
    thumbnail_path text,                  -- auto-generated thumbnail

    -- User (nullable — unregistered users can still record)
    user_id uuid references auth.users(id) on delete set null,

    -- Transcription
    transcript text,
    transcribed_at timestamptz,

    -- Review workflow
    status text not null default 'pending_review'
        check (status in ('pending_review', 'approved', 'rejected', 'published')),
    reviewed_by uuid references auth.users(id),
    reviewed_at timestamptz,
    review_notes text,

    -- Social media publishing
    social_push_enabled boolean not null default false,
    social_platforms jsonb not null default '[]'::jsonb,   -- ["twitter", "youtube", "tiktok"]
    social_published_at timestamptz,
    social_post_urls jsonb not null default '{}'::jsonb,   -- {"twitter": "https://...", ...}

    -- Consent
    consent_given boolean not null default true,
    consent_text text not null default 'I consent to my recording being submitted to CanadaGPT for review and potential publication.'
);

-- Indexes for admin panel queries
create index idx_opinions_status on opinions(status);
create index idx_opinions_category on opinions(category);
create index idx_opinions_created on opinions(created_at desc);
create index idx_opinions_user on opinions(user_id) where user_id is not null;

-- RLS policies
alter table opinions enable row level security;

-- Users can see their own opinions
create policy "Users can view own opinions"
    on opinions for select
    using (auth.uid() = user_id);

-- Published opinions are public
create policy "Published opinions are public"
    on opinions for select
    using (status = 'published');

-- Service role can do everything (admin panel, upload pipeline)
-- (Handled by supabase service_role key, bypasses RLS)

-- Storage bucket (run via Supabase dashboard or API)
-- insert into storage.buckets (id, name, public) values ('opinions', 'opinions', false);
