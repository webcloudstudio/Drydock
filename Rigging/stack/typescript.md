# TypeScript Best Practices

**Version:** 20260716 V2  
**Category:** Technologies
**Description:** TypeScript language conventions and patterns for specification-driven projects

Technology reference for TypeScript development. Framework-agnostic — applies to any TypeScript project. This file does not change between projects.

Prerequisite: `stack/common.md`

---

## 1. Code Style and Understandability

**Rule**: Code must be understandable on its own through naming, structure, small focused units, explicit types, clear interfaces, appropriate abstractions, and tests. If a reader needs a comment to follow the mechanics, improve the code instead.

Rules:
- **Naming** — names state intent: `loadActiveUsers()`, not `getData()`; `retryLimit`, not `n`. No abbreviations a new reader must decode.
- **Structure** — one responsibility per module; related code lives together; import graphs stay shallow and acyclic.
- **Small focused units** — functions do one thing at one level of abstraction; a function that needs a section comment ("// now validate…") is two functions.
- **Explicit types** — exported functions and values carry explicit types (§4); the signature answers "what goes in, what comes out" without reading the body.
- **Clear interfaces** — few parameters (an options object once past two or three), typed returns, no boolean flags that change what a function fundamentally does, no output-by-mutation surprises.
- **Appropriate abstractions** — introduce a layer only to remove real duplication or isolate a boundary (API client, storage, external service). No speculative generality.
- **Tests** — tests are the executable specification of behavior; a behavior worth keeping is a behavior worth a test.
- Comments state constraints the code cannot express (invariants, external quirks, why-not-the-obvious-way) — never restate what the next line does.

**Why**: Code is read far more often than written. Every hour invested in clarity is repaid at each future read, debug, and review — including by the author six months later.

---

## 2. Strict Compiler Settings

**Rule**: Enable strict compiler settings so compilation catches as many errors as reasonably possible. `strict: true` is the floor, not the ceiling.

```jsonc
// tsconfig.json
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "exactOptionalPropertyTypes": true,
    "forceConsistentCasingInFileNames": true,
    "verbatimModuleSyntax": true,
    "skipLibCheck": true
  }
}
```

Rules:
- Never disable a strict flag to silence an error — fix the type instead.
- `// @ts-ignore` and `// @ts-expect-error` require a comment explaining why; prefer `@ts-expect-error` so the suppression fails the build when it becomes stale.
- Type-check in CI (`tsc --noEmit`) even when a bundler (esbuild, Vite, swc) does the transpilation, because bundlers skip type checking.

**Why**: Every relaxed flag converts a class of compile-time errors into runtime failures. `noUncheckedIndexedAccess` alone eliminates a large family of `undefined` crashes.

---

## 3. No `any`, No Unsafe Assertions

**Rule**: Avoid `any` and avoid unsafe type assertions. Use `unknown` plus narrowing for values of uncertain type.

```typescript
// BAD — any disables checking; assertion invents a fact
function handle(data: any) { return data.items[0].name; }
const user = JSON.parse(body) as User;

// GOOD — unknown forces proof before use
function handle(data: unknown): string {
  if (!isItemList(data)) throw new Error("unexpected payload shape");
  return data.items[0]?.name ?? "";
}
```

Rules:
- `unknown`, never `any`, for values whose type is not yet established. Enforce with eslint `@typescript-eslint/no-explicit-any`.
- `as` is acceptable only for `as const` and for narrowing immediately after a runtime check has proven the type; it is never a substitute for validation.
- No non-null assertions (`!`) except where an invariant guarantees the value and a comment states that invariant.
- Double assertions (`x as unknown as T`) are prohibited.

**Why**: `any` and unchecked assertions silently propagate — one `any` parameter untypes everything it touches. `unknown` keeps the compiler honest at exactly the points where data is least trustworthy.

---

## 4. Explicit Domain Modeling

**Rule**: Model domain data explicitly. Every meaningful shape gets a named type; state that can only be one of several variants is a discriminated union, not a bag of optional fields.

```typescript
export interface Order {
  id: string;
  customerId: string;
  lines: OrderLine[];
  status: OrderStatus;
}

// Discriminated union — illegal states are unrepresentable
export type OrderStatus =
  | { kind: "draft" }
  | { kind: "submitted"; submittedAt: Date }
  | { kind: "shipped"; submittedAt: Date; trackingId: string };

function describe(status: OrderStatus): string {
  switch (status.kind) {
    case "draft": return "Draft";
    case "submitted": return `Submitted ${status.submittedAt.toISOString()}`;
    case "shipped": return `Shipped (${status.trackingId})`;
  }
}
```

Rules:
- Public functions and exported values carry explicit types — do not rely on inference across module boundaries.
- No implicit or ambiguous shapes: no `Record<string, any>`, no positional tuples for domain data, no reuse of one loose interface for several distinct concepts.
- Prefer union types over optional-field combinations that allow impossible states.
- Exhaustive `switch` over union discriminants; the compiler then flags any new variant that a handler misses.

**Why**: Named, precise types are executable documentation. Discriminated unions move "this combination can never happen" from tribal knowledge into the compiler.

---

## 5. Validate Data at System Boundaries

**Rule**: Validate all data entering the process — HTTP payloads, environment variables, file contents, message queues — with a runtime schema (e.g. zod) that derives the static type. Inside the boundary, trust the types.

```typescript
import { z } from "zod";

const UserSchema = z.object({
  id: z.string().uuid(),
  email: z.string().email(),
  roles: z.array(z.string()),
});
export type User = z.infer<typeof UserSchema>;   // single source of truth

// Boundary: parse, don't assert
const user: User = UserSchema.parse(await res.json());

// Environment config validated once at startup — crash early
// (secret hygiene and .env.example discipline: stack/env_variables_and_secrets.md)
const ConfigSchema = z.object({
  PORT: z.coerce.number().default(5001),
  DATABASE_URL: z.string().min(1),
});
export const config = ConfigSchema.parse(process.env);
```

Rules:
- One schema per external shape; the TypeScript type is derived from it (`z.infer`), never written twice.
- Validate at the edge, once. Interior code takes typed values and does not re-check.
- Malformed input fails loudly with a useful error, not a downstream `undefined`.

**Why**: The compiler cannot see across the network. `as User` on a fetch result is a guess; `UserSchema.parse` is a guarantee, and it makes the static types true at runtime.

---

## 6. Generated Types

**Rule**: Where a machine-readable contract exists — OpenAPI spec, GraphQL schema, database schema, protobuf — generate the TypeScript types from it instead of writing them by hand.

```bash
# Examples — pick the generator matching the contract
npx openapi-typescript api/openapi.yaml -o src/generated/api.d.ts
npx graphql-codegen --config codegen.yml
npx prisma generate        # DB client + row types from schema.prisma
```

Rules:
- Generated output lives under `src/generated/` and is never edited by hand.
- Regeneration is a scripted step (`bin/` script or package script) and runs in CI so drift between contract and types fails the build.
- Hand-written domain types may wrap or narrow generated types; they do not duplicate them.

**Why**: Hand-copied types drift from the contract silently; generated types make the contract the single source of truth and turn API changes into compile errors.

---

## Summary Checklist

- [ ] Code understandable through naming, structure, small units, explicit types, clear interfaces, appropriate abstractions, and tests
- [ ] `strict: true` plus `noUncheckedIndexedAccess` and companion flags; `tsc --noEmit` in CI
- [ ] No `any` (use `unknown` + narrowing); no unsafe `as` assertions; no undocumented `!`
- [ ] Domain data modeled with named types; variant state as discriminated unions; exhaustive switches
- [ ] All external data validated at the boundary with runtime schemas; types derived from schemas
- [ ] Types generated from machine-readable contracts (OpenAPI/GraphQL/DB) where they exist; generated code never hand-edited
