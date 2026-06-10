# Source-tree convenience launcher — no business logic.
# Locates the repository root and runs: python -m drydock
param([Parameter(ValueFromRemainingArguments=$true)]$Args)
$RepoDir = Split-Path -Parent $PSScriptRoot
Push-Location $RepoDir
try {
    & python -m drydock @Args
} finally {
    Pop-Location
}
