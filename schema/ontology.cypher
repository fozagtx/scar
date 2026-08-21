// SCAR ontology — HydraDB OSS OpenCypher.
// MERGE every node on `id`. Relationship types are SCREAMING_SNAKE.
// This file is the human-readable source of truth; runtime writes live in
// scar/graph/queries.py.

// Labels and required properties
// Repo        {id, root, language}
// File        {id, path, language}
// Symbol      {id, qualified_name, kind}
// Session     {id, source, started_at}
// Turn        {id, role, ts, text}
// Error       {id, signature, message, tool, exit_code}
// Correction  {id, kind, text, created_at, active}
// AntiPattern {id, name, description}
// Constraint  {id, rule, active}

// Correction.kind:
//   human_instruction | human_revert | successful_retry | tool_failure_then_fix

MERGE (repo:Repo {id: $repo_id})
SET repo.root = $root, repo.language = $language

MERGE (file:File {id: $file_id})
SET file.path = $path, file.language = $language

MERGE (symbol:Symbol {id: $symbol_id})
SET symbol.qualified_name = $qualified_name, symbol.kind = $kind

MERGE (session:Session {id: $session_id})
SET session.source = $source, session.started_at = $started_at

MERGE (turn:Turn {id: $turn_id})
SET turn.role = $role, turn.ts = $ts, turn.text = $text

MERGE (error:Error {id: $error_id})
SET error.signature = $signature, error.message = $message, error.tool = $tool, error.exit_code = $exit_code

MERGE (correction:Correction {id: $correction_id})
SET correction.kind = $kind, correction.text = $text, correction.created_at = $created_at, correction.active = $active

MERGE (ap:AntiPattern {id: $antipattern_id})
SET ap.name = $name, ap.description = $description

MERGE (constraint:Constraint {id: $constraint_id})
SET constraint.rule = $rule, constraint.active = $active

// Relationships
MATCH (session:Session {id: $session_id}) MATCH (repo:Repo {id: $repo_id}) MERGE (session)-[:IN_REPO]->(repo)
MATCH (session:Session {id: $session_id}) MATCH (turn:Turn {id: $turn_id}) MERGE (session)-[:HAS_TURN]->(turn)
MATCH (turn:Turn {id: $turn_id}) MATCH (file:File {id: $file_id}) MERGE (turn)-[:TOUCHED]->(file)
MATCH (turn:Turn {id: $turn_id}) MATCH (symbol:Symbol {id: $symbol_id}) MERGE (turn)-[:MENTIONS]->(symbol)
MATCH (turn:Turn {id: $turn_id}) MATCH (error:Error {id: $error_id}) MERGE (turn)-[:EMITTED]->(error)
MATCH (error:Error {id: $error_id}) MATCH (file:File {id: $file_id}) MERGE (error)-[:IN_FILE]->(file)
MATCH (error:Error {id: $error_id}) MATCH (symbol:Symbol {id: $symbol_id}) MERGE (error)-[:ON_SYMBOL]->(symbol)
MATCH (a:Error {id: $from_id}) MATCH (b:Error {id: $to_id}) MERGE (a)-[:SAME_AS]->(b)
MATCH (a:Error {id: $from_id}) MATCH (b:Error {id: $to_id}) MERGE (a)-[:LED_TO]->(b)
MATCH (correction:Correction {id: $correction_id}) MATCH (error:Error {id: $error_id}) MERGE (correction)-[:FIXES]->(error)
MATCH (correction:Correction {id: $correction_id}) MATCH (turn:Turn {id: $turn_id}) MERGE (correction)-[:STATED_IN]->(turn)
MATCH (newer:Correction {id: $newer_id}) MATCH (older:Correction {id: $older_id}) MERGE (newer)-[:SUPERSEDES]->(older)
MATCH (error:Error {id: $error_id}) MATCH (ap:AntiPattern {id: $antipattern_id}) MERGE (error)-[:INSTANCE_OF]->(ap)
MATCH (ap:AntiPattern {id: $antipattern_id}) MATCH (repo:Repo {id: $repo_id}) MERGE (ap)-[:FORBIDDEN_IN]->(repo)
MATCH (a:File {id: $from_id}) MATCH (b:File {id: $to_id}) MERGE (a)-[:IMPORTS]->(b)
MATCH (a:Symbol {id: $from_id}) MATCH (b:Symbol {id: $to_id}) MERGE (a)-[:CALLS]->(b)

// Recall: active Correction that FIXES an Error on this file, its IMPORTS
// neighborhood (1-2 hops), or a CALLS neighborhood of the current symbol.
// If newer-[:SUPERSEDES]->older, return only newer. If nothing matches, abstain.

MATCH (e:Error)-[:IN_FILE]->(f:File {path: $path})
MATCH (c:Correction)-[:FIXES]->(e)
RETURN c.id AS id, c.text AS text, c.active AS active, e.signature AS signature

MATCH (f:File {path: $path})-[:IMPORTS*1..2]-(n:File)
MATCH (e:Error)-[:IN_FILE]->(n)
MATCH (c:Correction)-[:FIXES]->(e)
RETURN c.id AS id, n.path AS path

MATCH (s:Symbol {qualified_name: $symbol})-[:CALLS*1..2]-(t:Symbol)
MATCH (e:Error)-[:ON_SYMBOL]->(t)
MATCH (c:Correction)-[:FIXES]->(e)
RETURN c.id AS id, t.qualified_name AS qualified_name

MATCH (newer:Correction)-[:SUPERSEDES]->(older:Correction)
RETURN newer.id AS newer_id, older.id AS older_id

// Blast radius: files that IMPORTS* a file which emitted the same signature.
MATCH (e:Error {id: $error_id})
MATCH (same:Error {signature: e.signature})-[:IN_FILE]->(origin:File)
MATCH (importer:File)-[:IMPORTS*1..8]->(origin)
RETURN DISTINCT importer.path AS path, origin.path AS origin_path
