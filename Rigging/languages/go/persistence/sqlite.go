package persistence

import (
	"database/sql"
	"os"
	"path/filepath"
	"strings"

	_ "github.com/mattn/go-sqlite3"
)

func openSQLite(dsn string) (*sql.DB, error) {
	path := strings.TrimPrefix(dsn, "sqlite://")
	if path == "" {
		path = ":memory:"
	}
	if path != ":memory:" {
		if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
			return nil, err
		}
	}
	separator := "?"
	if strings.Contains(path, "?") {
		separator = "&"
	}
	db, err := sql.Open("sqlite3", path+separator+"_foreign_keys=on&_journal_mode=WAL&_busy_timeout=5000")
	if err == nil {
		db.SetMaxOpenConns(1)
	}
	return db, err
}
