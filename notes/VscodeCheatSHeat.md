# VS Code Workflow

## Core window toggles
- Toggle Primary Side Bar: `Ctrl+B`
- Toggle Panel: `Ctrl+J`
- Toggle Terminal: `Ctrl+\``
- New Terminal: `Ctrl+Shift+\``
- Command Palette: `Ctrl+Shift+P`

## Personal test and terminal bindings
- Toggle Terminal: `Ctrl+Alt+T`
- Run all tests: `Ctrl+Alt+A`
- Run tests in the current file: `Ctrl+Alt+F`
- Run the test at the cursor: `Ctrl+Alt+R`
- Debug the test at the cursor: `Ctrl+Alt+D`

## Focus major views
- Explorer: `Ctrl+Shift+E`
- Search: `Ctrl+Shift+F`
- Source Control: `Ctrl+Shift+G`
- Run and Debug: `Ctrl+Shift+D`
- Extensions: `Ctrl+Shift+X`

## Fast navigation
- Quick Open file: `Ctrl+P`
- Go to line: `Ctrl+G`
- Go to symbol in current file: `Ctrl+Shift+O`
- Go to symbol in workspace: `Ctrl+T`
- Find all references: `Shift+F12`
- Navigate back: `Alt+Left`
- Navigate forward: `Alt+Right`

## Explorer / Outline
- Focus Explorer: `Ctrl+Shift+E`
- In Explorer or Outline:
  - Expand node: `Right`
  - Collapse node: `Left`
- Move: `Up` / `Down`
- Filter current tree: use Command Palette, then `Filter`
- Outline is best for Markdown headings and code symbols
- Breadcrumbs are best for path + symbol navigation at the top of the editor

## Copy / paste
- Editor text on Windows: `Ctrl+C` / `Ctrl+V`
- Integrated terminal on Windows: `Ctrl+C` / `Ctrl+V`
- Safer terminal copy/paste habit: `Ctrl+Shift+C` / `Ctrl+Shift+V` if you bind them
- In shell workflows, `Ctrl+C` may still be used as interrupt, so explicit terminal bindings are cleaner

## Recommended habits
- Use `Ctrl+P` instead of browsing for files
- Use `Ctrl+Shift+O` instead of browsing Outline
- Use `Alt+Left` / `Alt+Right` as your jump list
- Keep `explorer.autoReveal = false` so the tree stops jumping around
- Use a multi-root workspace for the 3 directories you visit constantly

## Learn next
- Open Settings: `Ctrl+,`
- Open Keyboard Shortcuts: `Ctrl+K Ctrl+S`
- Open Problems: `Ctrl+Shift+M`
- Use `F12` for a definition and `Shift+F12` for every reference to it

## Codex chat composer
- Send: `Enter` or `Ctrl+Enter`
- Insert a new line: `Shift+Enter`
- A setting that enables Codex in WSL reloads VS Code. Save editor files before changing it; the Codex pane can lose recent chat UI state during the reload.
