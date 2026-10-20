// Package persistence implements declared repository operations for generated Targets.
package persistence

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"regexp"
	"strconv"
	"strings"
)

// ErrUnknownOperation identifies a call not granted by DATABASE.md.
var ErrUnknownOperation = errors.New("undeclared persistence operation")

// Table describes a validated table declaration.
type Table struct {
	Name    string
	Columns []string
	Key     string
}

// Operation describes one declared repository method.
type Operation struct {
	ID, Table, Verb string
	Inputs, Columns []string
}

// Schema holds generated declarations; callers do not construct SQL.
type Schema struct {
	Tables     []Table
	Operations []Operation
}

// Result carries rows, generated identity, or affected-row count.
type Result struct {
	Rows  []map[string]any
	ID    any
	Count int64
}

// Database owns the connection pool and declared operation surface.
type Database struct {
	connection *sql.DB
	schema     Schema
	engine     string
}

var identifier = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)

func quote(name string) string { return `"` + name + `"` }
func quoted(names []string) string {
	parts := make([]string, len(names))
	for i, n := range names {
		parts[i] = quote(n)
	}
	return strings.Join(parts, ", ")
}

// Open connects to a DSN and validates all SQL identifiers before use.
func Open(ctx context.Context, dsn string, schema Schema) (*Database, error) {
	for _, table := range schema.Tables {
		for _, name := range append(append([]string{table.Name}, table.Columns...), table.Key) {
			if name != "" && !identifier.MatchString(name) {
				return nil, fmt.Errorf("invalid identifier %q", name)
			}
		}
	}
	for _, op := range schema.Operations {
		var table *Table
		for i := range schema.Tables {
			if schema.Tables[i].Name == op.Table {
				table = &schema.Tables[i]
				break
			}
		}
		if table == nil {
			return nil, fmt.Errorf("%s: undeclared table %s", op.ID, op.Table)
		}
		for _, name := range append(append([]string{}, op.Inputs...), op.Columns...) {
			found := false
			for _, column := range table.Columns {
				if name == column {
					found = true
				}
			}
			if !found {
				return nil, fmt.Errorf("%s: undeclared column %s", op.ID, name)
			}
		}
		switch op.Verb {
		case "get", "list", "create", "update", "delete":
		default:
			return nil, fmt.Errorf("%w: %s", ErrUnknownOperation, op.Verb)
		}
	}
	var conn *sql.DB
	var err error
	engine := "sqlite"
	if strings.HasPrefix(dsn, "postgresql://") || strings.HasPrefix(dsn, "postgres://") {
		engine = "postgres"
		conn, err = openPostgres(dsn)
	} else if strings.Contains(dsn, "://") && !strings.HasPrefix(dsn, "sqlite://") {
		return nil, fmt.Errorf("unsupported persistence DSN scheme")
	} else {
		conn, err = openSQLite(dsn)
	}
	if err != nil {
		return nil, err
	}
	if err = conn.PingContext(ctx); err != nil {
		conn.Close()
		return nil, err
	}
	return &Database{connection: conn, schema: schema, engine: engine}, nil
}

// Close releases the database pool.
func (db *Database) Close() error { return db.connection.Close() }

// ApplySchema applies generated DDL in one transaction.
func (db *Database) ApplySchema(ctx context.Context, ddl string) error {
	if db.engine == "postgres" {
		ddl = postgresSchema(ddl)
	}
	tx, err := db.connection.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err = tx.ExecContext(ctx, ddl); err != nil {
		return err
	}
	return tx.Commit()
}
func (db *Database) placeholder(n int) string {
	if db.engine == "postgres" {
		return fmt.Sprintf("$%d", n)
	}
	return "?"
}
func (db *Database) predicates(names []string, offset int) string {
	if len(names) == 0 {
		return ""
	}
	parts := make([]string, len(names))
	for i, name := range names {
		parts[i] = quote(name) + " = " + db.placeholder(offset+i+1)
	}
	return " WHERE " + strings.Join(parts, " AND ")
}

// Run invokes a declared operation; values are always bound parameters.
func (db *Database) Run(ctx context.Context, table, verb string, arguments map[string]any) (Result, error) {
	result, err := db.run(ctx, table, verb, arguments)
	if err != nil {
		return result, fmt.Errorf("%s.%s: %w", table, verb, err)
	}
	return result, nil
}
func (db *Database) run(ctx context.Context, table, verb string, arguments map[string]any) (Result, error) {
	var op *Operation
	var declared Table
	for i := range db.schema.Operations {
		candidate := &db.schema.Operations[i]
		if candidate.Table == table && candidate.Verb == verb {
			op = candidate
			break
		}
	}
	if op == nil {
		return Result{}, ErrUnknownOperation
	}
	for _, candidate := range db.schema.Tables {
		if candidate.Name == table {
			declared = candidate
			break
		}
	}
	for name := range arguments {
		found := false
		for _, input := range op.Inputs {
			if name == input {
				found = true
			}
		}
		if !found {
			return Result{}, fmt.Errorf("undeclared input %s", name)
		}
	}
	if verb == "get" || verb == "update" || verb == "delete" {
		for _, input := range op.Inputs {
			if input == declared.Key {
				if _, ok := arguments[input]; !ok {
					return Result{}, fmt.Errorf("%s requires key %s", verb, input)
				}
			}
		}
	}
	if verb == "delete" && len(arguments) == 0 {
		return Result{}, errors.New("delete requires a predicate")
	}
	names := []string{}
	values := []any{}
	for _, name := range op.Inputs {
		if value, ok := arguments[name]; ok {
			names = append(names, name)
			if flag, ok := value.(bool); ok {
				if flag {
					value = int64(1)
				} else {
					value = int64(0)
				}
			}
			values = append(values, value)
		}
	}
	switch verb {
	case "get", "list":
		columns := op.Columns
		if len(columns) == 0 {
			columns = declared.Columns
		}
		query := "SELECT " + quoted(columns) + " FROM " + quote(table) + db.predicates(names, 0)
		if verb == "get" {
			query += " LIMIT 1"
		}
		rows, err := db.selectRows(ctx, query, columns, values)
		return Result{Rows: rows}, err
	case "create":
		query := "INSERT INTO " + quote(table) + " DEFAULT VALUES"
		if len(names) > 0 {
			marks := make([]string, len(names))
			for i := range names {
				marks[i] = db.placeholder(i + 1)
			}
			query = "INSERT INTO " + quote(table) + " (" + quoted(names) + ") VALUES (" + strings.Join(marks, ", ") + ")"
		}
		var id any
		if db.engine == "postgres" && declared.Key != "" {
			if err := db.connection.QueryRowContext(ctx, query+" RETURNING "+quote(declared.Key), values...).Scan(&id); err != nil {
				return Result{}, err
			}
		} else {
			result, err := db.connection.ExecContext(ctx, query, values...)
			if err != nil {
				return Result{}, err
			}
			if db.engine != "postgres" {
				if id, err = result.LastInsertId(); err != nil {
					return Result{}, err
				}
			}
		}
		if declared.Key == "" || len(op.Columns) == 0 {
			return Result{ID: id}, nil
		}
		// The declared Output row, read back so column defaults are included. A supplied key
		// wins over the engine's report: SQLite's LastInsertId is the rowid, not a text key.
		if supplied, ok := arguments[declared.Key]; ok {
			id = supplied
		}
		query = "SELECT " + quoted(op.Columns) + " FROM " + quote(table) + db.predicates([]string{declared.Key}, 0)
		rows, err := db.selectRows(ctx, query, op.Columns, []any{id})
		return Result{Rows: rows, ID: id}, err
	case "update":
		key, ok := arguments[declared.Key]
		if declared.Key == "" || !ok {
			return Result{}, errors.New("update requires primary key")
		}
		assignments := []string{}
		ordered := []any{}
		for _, name := range names {
			if name != declared.Key {
				ordered = append(ordered, values[indexOf(names, name)])
				assignments = append(assignments, quote(name)+" = "+db.placeholder(len(ordered)))
			}
		}
		if len(assignments) == 0 {
			return Result{}, errors.New("update requires at least one assigned column")
		}
		query := "UPDATE " + quote(table) + " SET " + strings.Join(assignments, ", ") + db.predicates([]string{declared.Key}, len(ordered))
		result, err := db.connection.ExecContext(ctx, query, append(ordered, key)...)
		if err != nil {
			return Result{}, err
		}
		count, err := result.RowsAffected()
		return Result{Count: count}, err
	case "delete":
		result, err := db.connection.ExecContext(ctx, "DELETE FROM "+quote(table)+db.predicates(names, 0), values...)
		if err != nil {
			return Result{}, err
		}
		count, err := result.RowsAffected()
		return Result{Count: count}, err
	}
	return Result{}, ErrUnknownOperation
}

// selectRows runs a bound SELECT and returns each row keyed by column name.
func (db *Database) selectRows(ctx context.Context, query string, columns []string, values []any) ([]map[string]any, error) {
	rows, err := db.connection.QueryContext(ctx, query, values...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []map[string]any{}
	for rows.Next() {
		data := make([]any, len(columns))
		pointers := make([]any, len(columns))
		for i := range data {
			pointers[i] = &data[i]
		}
		if err := rows.Scan(pointers...); err != nil {
			return nil, err
		}
		row := map[string]any{}
		for i, name := range columns {
			if bytes, ok := data[i].([]byte); ok {
				row[name] = string(bytes)
			} else {
				row[name] = data[i]
			}
		}
		result = append(result, row)
	}
	return result, rows.Err()
}

// Decode maps driver values into generated row structs, preserving conversion errors.
func Decode[T any](value any) (T, error) {
	var result T
	data, err := json.Marshal(normalizeValue(value, reflect.TypeOf((*T)(nil)).Elem()))
	if err != nil {
		return result, err
	}
	err = json.Unmarshal(data, &result)
	return result, err
}

// normalizeValue handles driver numeric strings and SQLite integer booleans using the
// generated destination type, leaving text columns and conversion errors intact.
func normalizeValue(value any, target reflect.Type) any {
	if value == nil {
		return nil
	}
	if target.Kind() == reflect.Pointer {
		return normalizeValue(value, target.Elem())
	}
	if target.Kind() == reflect.Slice {
		if rows, ok := value.([]map[string]any); ok {
			result := make([]any, len(rows))
			for i, row := range rows {
				result[i] = normalizeValue(row, target.Elem())
			}
			return result
		}
	}
	if target.Kind() == reflect.Struct {
		if row, ok := value.(map[string]any); ok {
			result := map[string]any{}
			for key, item := range row {
				result[key] = item
			}
			for i := 0; i < target.NumField(); i++ {
				field := target.Field(i)
				name := strings.Split(field.Tag.Get("json"), ",")[0]
				if name == "" {
					name = field.Name
				}
				if item, exists := row[name]; exists {
					result[name] = normalizeValue(item, field.Type)
				}
			}
			return result
		}
	}
	if target.Kind() == reflect.Bool {
		if number, ok := value.(int64); ok && (number == 0 || number == 1) {
			return number == 1
		}
	}
	if text, ok := value.(string); ok {
		switch target.Kind() {
		case reflect.Float64:
			if number, err := strconv.ParseFloat(text, 64); err == nil {
				return number
			}
		case reflect.Int64:
			if number, err := strconv.ParseInt(text, 10, 64); err == nil {
				return number
			}
		}
	}
	return value
}

func indexOf(names []string, name string) int {
	for i, item := range names {
		if item == name {
			return i
		}
	}
	return -1
}
