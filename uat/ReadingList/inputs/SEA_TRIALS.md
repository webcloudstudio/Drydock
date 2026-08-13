# Sea Trials: ReadingList

## Policy

| Consequence | On FAIL | On INCONCLUSIVE |
|---|---|---|
| blocks  | fail   | attest |
| scores  | score  | score  |
| attests | report | report |

## st-001: Test suite passes
Type: technical
Required: yes
Criterion: The application shall provide a POSIX-compatible bin/test.sh that exits zero when every automated test passes.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: ubiquitous

## st-002: A book can be added
Type: behavioral
Required: yes
Criterion: When a reader submits a title and an author, the application shall store the book and show it in the list.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: event

## st-003: Books appear in the order added
Type: behavioral
Required: yes
Criterion: The application shall present books in the order they were added.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: ubiquitous

## st-004: A book can be removed
Type: behavioral
Required: yes
Criterion: When a reader removes a book, the application shall omit it from the list on the next read.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: event

## st-005: Empty fields are rejected
Type: behavioral
Required: yes
Criterion: If a submission carries an empty title or an empty author, then the application shall reject it and report the reason.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: unwanted

## st-006: Every behavior is covered by a test
Type: technical
Required: yes
Criterion: The application shall carry automated tests for adding a book, listing books in the order added, removing a book, rejecting an empty title or author, marking a book as read, and displaying whether each book is unread or read.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: ubiquitous

## st-007: A book can be marked as read
Type: behavioral
Required: yes
Criterion: When a reader marks a book as read, the application shall store the change and show that book as read instead of unread on the next view.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: event
