-- =========================================================
-- SkillTwin Migration 002: Dynamic Learning System Schema
-- =========================================================

-- Enable UUID extension if not already present
create extension if not exists pgcrypto;

-- 1. LEARNING GOALS
create table if not exists learning_goals (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    learning_goal text not null,
    target_level text not null default 'Intermediate', -- Beginner, Intermediate, Expert, Interview Ready, Other
    custom_target text,
    daily_minutes integer default 30,
    current_knowledge jsonb default '[]'::jsonb,
    status text default 'ACTIVE', -- ACTIVE, COMPLETED, ARCHIVED
    metadata jsonb default '{}'::jsonb,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index if not exists idx_learning_goals_user on learning_goals(user_id);
create index if not exists idx_learning_goals_status on learning_goals(status);

-- 2. LEARNING PATHS
create table if not exists learning_paths (
    id uuid primary key default gen_random_uuid(),
    goal_id uuid not null references learning_goals(id) on delete cascade,
    user_id uuid not null references profiles(id) on delete cascade,
    title text not null,
    description text,
    target_level text not null default 'Intermediate',
    estimated_duration text,
    version integer default 1,
    status text default 'ACTIVE',
    generation_status text default 'READY', -- PENDING, PROCESSING, READY, FAILED
    generation_error text,
    progress numeric(5,2) default 0.0,
    metadata jsonb default '{}'::jsonb,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index if not exists idx_learning_paths_goal on learning_paths(goal_id);
create index if not exists idx_learning_paths_user on learning_paths(user_id);

-- 3. LEARNING SECTIONS (MODULES)
create table if not exists learning_sections (
    id uuid primary key default gen_random_uuid(),
    path_id uuid not null references learning_paths(id) on delete cascade,
    title text not null,
    description text,
    order_index integer not null,
    metadata jsonb default '{}'::jsonb,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index if not exists idx_learning_sections_path on learning_sections(path_id, order_index);

-- 4. LEARNING TOPICS (SUBTOPICS)
create table if not exists learning_topics (
    id uuid primary key default gen_random_uuid(),
    section_id uuid not null references learning_sections(id) on delete cascade,
    title text not null,
    description text,
    order_index integer not null,
    difficulty text default 'beginner', -- beginner, intermediate, advanced
    estimated_minutes integer default 25,
    prerequisites jsonb default '[]'::jsonb,
    learning_objectives jsonb default '[]'::jsonb,
    metadata jsonb default '{}'::jsonb,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index if not exists idx_learning_topics_section on learning_topics(section_id, order_index);

-- 5. TOPIC DEPENDENCIES
create table if not exists topic_dependencies (
    id uuid primary key default gen_random_uuid(),
    source_topic_id uuid not null references learning_topics(id) on delete cascade,
    target_topic_id uuid not null references learning_topics(id) on delete cascade,
    dependency_type text default 'prerequisite',
    unique(source_topic_id, target_topic_id)
);

-- 6. LEARNER TOPIC PROGRESS
create table if not exists learner_topic_progress (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    topic_id uuid not null references learning_topics(id) on delete cascade,
    status text not null default 'not_started', -- not_started, learning, completed, needs_revision
    mastery_score numeric(5,2) default 0.0,
    confidence_score numeric(5,2) default 0.0,
    revision_count integer default 0,
    time_spent_minutes integer default 0,
    attempts integer default 0,
    started_at timestamptz,
    completed_at timestamptz,
    last_accessed_at timestamptz default now(),
    next_revision_at timestamptz,
    metadata jsonb default '{}'::jsonb,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    unique(user_id, topic_id)
);

create index if not exists idx_topic_progress_user on learner_topic_progress(user_id);
create index if not exists idx_topic_progress_user_status on learner_topic_progress(user_id, status);
create index if not exists idx_topic_progress_revision on learner_topic_progress(user_id, next_revision_at);

-- 7. TOPIC QUESTIONS (PERSISTED PRACTICE POOL)
create table if not exists topic_questions (
    id uuid primary key default gen_random_uuid(),
    topic_id uuid not null references learning_topics(id) on delete cascade,
    question_type text not null, -- mcq, true_false, short_answer, scenario, code_fix, interview
    prompt text not null,
    options jsonb default '[]'::jsonb,
    correct_answer text not null,
    explanation text not null,
    difficulty text default 'medium',
    metadata jsonb default '{}'::jsonb,
    created_at timestamptz default now()
);

create index if not exists idx_topic_questions_topic on topic_questions(topic_id);

-- 8. QUESTION ATTEMPTS
create table if not exists question_attempts (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    question_id uuid not null references topic_questions(id) on delete cascade,
    topic_id uuid not null references learning_topics(id) on delete cascade,
    user_answer text not null,
    is_correct boolean not null,
    score numeric(5,2) default 0.0,
    feedback text,
    created_at timestamptz default now()
);

create index if not exists idx_question_attempts_user on question_attempts(user_id, topic_id);

-- 9. TOPIC EXPLANATIONS CACHE
create table if not exists topic_explanations_cache (
    id uuid primary key default gen_random_uuid(),
    topic_id uuid not null references learning_topics(id) on delete cascade,
    user_id uuid not null references profiles(id) on delete cascade,
    content text not null,
    prompt_version text not null default 'v1',
    created_at timestamptz default now(),
    unique(topic_id, user_id, prompt_version)
);

-- 10. TWIN METRICS (DERIVED COGNITIVE STATE)
create table if not exists twin_metrics (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade unique,
    overall_mastery numeric(5,2) default 0.0,
    current_level text default 'Beginner',
    strongest_areas jsonb default '[]'::jsonb,
    weakest_areas jsonb default '[]'::jsonb,
    concepts_at_risk jsonb default '[]'::jsonb,
    learning_velocity numeric(5,2) default 0.0,
    consistency_streak integer default 0,
    knowledge_coverage numeric(5,2) default 0.0,
    has_sufficient_data boolean default false,
    insights jsonb default '[]'::jsonb,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

-- =========================================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- =========================================================

alter table learning_goals enable row level security;
alter table learning_paths enable row level security;
alter table learning_sections enable row level security;
alter table learning_topics enable row level security;
alter table topic_dependencies enable row level security;
alter table learner_topic_progress enable row level security;
alter table topic_questions enable row level security;
alter table question_attempts enable row level security;
alter table topic_explanations_cache enable row level security;
alter table twin_metrics enable row level security;

create policy "Users manage own learning goals"
on learning_goals for all
using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "Users manage own learning paths"
on learning_paths for all
using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "Users view learning sections for their paths"
on learning_sections for select
using (exists (select 1 from learning_paths where learning_paths.id = learning_sections.path_id and learning_paths.user_id = auth.uid()));

create policy "Users view learning topics for their paths"
on learning_topics for select
using (exists (
    select 1 from learning_sections
    join learning_paths on learning_paths.id = learning_sections.path_id
    where learning_sections.id = learning_topics.section_id
    and learning_paths.user_id = auth.uid()
));

create policy "Users manage own topic progress"
on learner_topic_progress for all
using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "Users manage own question attempts"
on question_attempts for all
using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "Users manage own cached explanations"
on topic_explanations_cache for all
using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "Users manage own twin metrics"
on twin_metrics for all
using (auth.uid() = user_id) with check (auth.uid() = user_id);
