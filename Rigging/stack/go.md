# Go Best Practices

**Version:** 20260809 V2  
**Category:** Technologies
**Description:** Go language conventions and patterns for specification-driven projects

Technology reference for Go development. Framework-agnostic — applies to any Go project. This file does not change between projects.

Prerequisite: `stack/common.md`

---

## 1. Code Style and Understandability

**Rule**: Code must be understandable on its own through naming, structure, small focused units, explicit types, clear interfaces, appropriate abstractions, and tests. If a reader needs a comment to follow the mechanics, improve the code instead.

Rules:
- **Formatting is not a decision** — `gofmt` output is the only accepted formatting. Never hand-format, never argue about it, never commit unformatted code.
- **Naming** — short names for short scopes (`i`, `buf`, `err`), descriptive names for package-level identifiers. Package names are short, lowercase, single-word nouns: `parser`, not `parserutils` or `parser_helpers`. Never `util`, `common`, `base`, or `helpers`.
- **No stutter** — the package qualifies the name. `parser.New()`, not `parser.NewParser()`; `http.Client`, not `http.HTTPClient`.
- **Exported means committed** — capitalize an identifier only when callers outside the package need it. Everything else is unexported and free to change.
- **Doc comments** — every exported identifier has a comment starting with its own name: `// Decode reads TOML from r and returns …`.
- **Small focused units** — a function that needs a section comment ("// now validate…") is two functions.
- Comments state constraints the code cannot express (invariants, protocol quirks, why-not-the-obvious-way) — never restate what the next line does.

**Why**: Go deliberately removed stylistic choice so that all Go code reads the same. Fighting that costs review time and buys nothing.

---

## 2. Module Layout and Toolchain

**Rule**: One module per repository, with the toolchain version pinned in `go.mod` and `go.sum` committed.

```
myproject/
  go.mod              module github.com/owner/myproject
  go.sum              committed, never hand-edited
  cmd/myproject/      package main — one directory per binary
  internal/           application packages; import-blocked outside the module
  pkg/                only if the module is a library others import
  testdata/           fixtures; ignored by the go tool
  bin/                launcher scripts (see stack/common.md)
```

```gomod
module github.com/owner/myproject

go 1.24

require github.com/some/dep v1.4.2
```

Rules:
- **Go 1.22 is the hard floor. Verify it first and stop if it is not met.** Before writing any code, run `go version`. On anything older than 1.22, stop and report the toolchain as a blocker — do not downgrade the code to compile on it, do not work around it, do not proceed and hope. The distribution-packaged Go on Debian and Ubuntu is frequently older than this and must be replaced with the official tarball.

```sh
go version | awk '{print $3}' | sed 's/^go//' | \
  awk -F. '$1<1 || ($1==1 && $2<22) { print "go 1.22+ required, found " $0; exit 1 }'
```

- Business logic lives in `internal/`. `cmd/<name>/main.go` parses flags, wires dependencies, and calls into `internal/`; it holds no behavior worth testing.
- `pkg/` exists only when external consumers import the code. A binary-only project does not need it.
- The `go` line in `go.mod` is the minimum toolchain, and it is a real constraint — `go 1.19` fails on anything newer than 1.19 syntax and stdlib. State the version the code actually requires.
- `go.sum` is committed. `go mod tidy` runs before every commit that touches dependencies, and its output is part of the diff.
- Do not vendor unless the deployment target requires it. If vendoring, `go mod vendor` output is committed whole and never edited.

**Why**: Go's tooling assumes this layout and enforces `internal/` at compile time. A project that follows it gets dependency hygiene, import boundaries, and reproducible builds without configuration. The 1.22 floor is not stylistic: 1.22 changed loop variables to be scoped per iteration, so identical source produces different behavior on 1.21 and earlier. Code written against modern semantics and compiled by an older toolchain fails silently rather than loudly.

---

## 3. Errors Are Values

**Rule**: Return errors, do not panic. Wrap with context at each layer that adds information, and inspect with `errors.Is` / `errors.As`, never by string matching.

```go
var ErrNotFound = errors.New("not found")

func LoadConfig(path string) (*Config, error) {
    data, err := os.ReadFile(path)
    if err != nil {
        return nil, fmt.Errorf("load config %s: %w", path, err)
    }
    var cfg Config
    if err := json.Unmarshal(data, &cfg); err != nil {
        return nil, fmt.Errorf("parse config %s: %w", path, err)
    }
    return &cfg, nil
}

// Caller inspects by identity, not by text
if errors.Is(err, os.ErrNotExist) { … }

var perr *json.SyntaxError
if errors.As(err, &perr) { … }
```

Rules:
- `%w` wraps exactly one error and preserves the chain. `%v` formats and discards it — use `%v` only when the chain must deliberately not leak.
- Error strings are lowercase and carry no trailing punctuation, because they are concatenated: `"parse config x: unexpected EOF"`.
- Handle an error once. Logging it and returning it is handling it twice, and the operator sees the same failure repeated at every layer.
- `panic` is for programmer error that cannot be recovered from (an impossible switch branch, a corrupt invariant). Library code never panics on bad input; it returns an error.
- `recover` appears only at a process or request boundary that must not die, and it logs and re-fails rather than swallowing.
- Never ignore an error with `_`. If it is genuinely safe to discard, say why in a comment on that line.

**Why**: Go has no exceptions, so an unhandled error is a silently wrong result rather than a crash. Wrapping preserves the failure path; `errors.Is` keeps callers working when the message text changes.

---

## 4. Types, Interfaces, and Zero Values

**Rule**: Define interfaces where they are consumed, keep them small, and make the zero value of a type useful.

```go
// GOOD — the consumer declares what it needs
package report

type Store interface {
    Get(ctx context.Context, id string) ([]byte, error)
}

func Render(ctx context.Context, s Store, id string) ([]byte, error) { … }
```

```go
// Zero value is usable — no constructor required
type Buffer struct {
    buf []byte
}

func (b *Buffer) Write(p []byte) (int, error) {
    b.buf = append(b.buf, p...)
    return len(p), nil
}

var b Buffer   // ready to use
```

Rules:
- Accept interfaces, return concrete types. A function that returns an interface hides fields the caller may legitimately need.
- One or two methods per interface. `io.Reader` is the model; a ten-method interface is a struct wearing a disguise.
- Do not define an interface until there are two implementations, or until a test genuinely needs to substitute one. Speculative interfaces are indirection with no payoff.
- Prefer a usable zero value over a `New…` constructor. When a constructor is required, it validates and returns `(*T, error)`.
- Pointer receivers when the method mutates or the struct is large; value receivers otherwise. Do not mix receiver kinds on one type.
- No naked returns in any function long enough to need scrolling.
- `context.Context` is the first parameter of any function that does I/O, blocks, or spawns work — never stored in a struct field.

**Why**: Consumer-side interfaces mean a package can be tested and substituted without the producer knowing it exists. Useful zero values remove a whole category of "forgot to initialize" bugs.

---

## 5. Concurrency With Owned Lifetimes

**Rule**: Every goroutine has a known owner, a known stop condition, and a way to report failure. Start none that you cannot stop.

```go
func Fetch(ctx context.Context, urls []string) ([]Result, error) {
    g, ctx := errgroup.WithContext(ctx)
    results := make([]Result, len(urls))
    for i, u := range urls {
        i, u := i, u
        g.Go(func() error {
            r, err := get(ctx, u)
            if err != nil {
                return fmt.Errorf("fetch %s: %w", u, err)
            }
            results[i] = r
            return nil
        })
    }
    if err := g.Wait(); err != nil {
        return nil, err
    }
    return results, nil
}
```

Rules:
- Cancellation flows through `context.Context`. A goroutine that cannot observe `ctx.Done()` is a leak waiting for load.
- The code that starts a goroutine is responsible for waiting on it — `sync.WaitGroup`, `errgroup`, or an explicit done channel. Fire-and-forget is prohibited outside `main`.
- Channels carry ownership: the sender closes, the receiver never does. Do not close a channel from more than one place.
- Use a mutex when the data is shared state and a channel when the data is being handed off. Do not build a queue out of mutexes.
- Every build and CI run includes `go test -race`. The race detector finds what review does not.
- Do not add concurrency for speed until a benchmark shows the serial version is the bottleneck.

**Why**: Go makes starting a goroutine trivial and stopping one entirely manual. Leaks and races surface under production load, not in development.

---

## 6. Table-Driven Tests

**Rule**: Tests use the stdlib `testing` package, are table-driven where cases share a shape, and run offline with no network and no credentials.

```go
func TestParseDuration(t *testing.T) {
    tests := []struct {
        name    string
        input   string
        want    time.Duration
        wantErr bool
    }{
        {name: "seconds", input: "30s", want: 30 * time.Second},
        {name: "hours", input: "2h", want: 2 * time.Hour},
        {name: "malformed", input: "2x", wantErr: true},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got, err := ParseDuration(tt.input)
            if (err != nil) != tt.wantErr {
                t.Fatalf("ParseDuration(%q) error = %v, wantErr %v", tt.input, err, tt.wantErr)
            }
            if got != tt.want {
                t.Errorf("ParseDuration(%q) = %v, want %v", tt.input, got, tt.want)
            }
        })
    }
}
```

Rules:
- Subtests via `t.Run` so a single case can be run with `-run TestParseDuration/malformed`.
- Failure messages state input, actual, and expected. `t.Errorf("got %v, want %v", got, want)` is the minimum; a bare `t.Fail()` is useless in CI output.
- `t.Fatalf` when the test cannot continue, `t.Errorf` when it can and more failures are informative.
- Fixtures live in `testdata/`. Golden files are regenerated by a `-update` flag, and the regenerated diff is reviewed, not rubber-stamped.
- `t.TempDir()` and `t.Cleanup()` for filesystem work — never write into the package directory or `/tmp` by hand.
- No network, no credentials, no wall-clock sleeps. Inject a clock or a fake transport instead.
- Benchmarks (`func BenchmarkX(b *testing.B)`) accompany any claim about performance.

**Why**: Table-driven tests make adding the twentieth case free, which is what keeps edge cases getting written down instead of argued about.

---

## 7. Build, Lint, and Verify

**Rule**: The same commands gate locally and in CI, and they all pass before a commit.

```bash
gofmt -l .                       # must print nothing
go vet ./...
go build ./...
go test -race -cover ./...
```

```bash
# Static, dependency-free binary for containers and scratch images
CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o bin/myproject ./cmd/myproject
```

Rules:
- `gofmt -l .` printing any filename fails the build. This is not negotiable and needs no discussion.
- `go vet ./...` is the floor. Add `staticcheck` or `golangci-lint` when the project justifies it, with the configuration committed.
- `CGO_ENABLED=0` unless a dependency genuinely needs cgo; it is the difference between a portable static binary and one that fails on a different libc.
- `-trimpath` keeps build paths out of the binary so builds are reproducible across machines.
- Pin tool versions with `go run <tool>@<version>` rather than assuming what is installed. An unpinned linter changes its mind between machines.
- Wrap the sequence in a `bin/` script (see `stack/common.md`) so there is one command to run and one place to change it.

**Why**: Go's toolchain ships almost everything needed. The remaining risk is drift between what a developer runs and what CI runs, which one scripted entry point removes.

---

## 8. Dependencies

**Rule**: The standard library first. Add a dependency only when it removes real work, and pin it.

Rules:
- Check the stdlib before searching: `net/http` is a production server, `encoding/json` is a production codec, `database/sql` is a production database layer, `log/slog` is structured logging. Frameworks are frequently unnecessary.
- Every dependency is an exact version in `go.mod`. Never `@latest` in committed configuration.
- `go mod tidy` after any dependency change; the resulting `go.mod` and `go.sum` are committed together.
- Evaluate a candidate on maintenance, transitive dependency count, and licence before importing it. A one-function dependency is usually a one-function file.
- Deprecated or archived upstream is a defect to schedule, not a warning to silence.

**Why**: Every dependency is code the project owns the consequences of but not the maintenance of. Go's stdlib is unusually complete, which makes "do I need this?" a real question.

---

## Summary Checklist

- [ ] `gofmt` clean; package and identifier names idiomatic; no stutter; exported identifiers documented
- [ ] One module; logic in `internal/`; thin `cmd/<name>/main.go`; `go.sum` committed; `go` directive states the real minimum
- [ ] Errors returned and wrapped with `%w`; inspected with `errors.Is`/`errors.As`; handled once; no ignored errors
- [ ] Interfaces defined at the consumer, one or two methods; concrete return types; useful zero values; `context.Context` first parameter
- [ ] Every goroutine has an owner, a cancellation path, and a wait; `go test -race` in every run
- [ ] Table-driven subtests with informative failures; fixtures in `testdata/`; offline and deterministic
- [ ] `gofmt -l .`, `go vet`, `go build`, `go test -race -cover` all gate locally and in CI via one `bin/` script
- [ ] Standard library preferred; dependencies pinned and tidied; each one justified
