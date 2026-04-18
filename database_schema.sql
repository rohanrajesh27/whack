-- SQLite schema for this project
-- Run automatically by app.py if the DB is empty.

CREATE TABLE IF NOT EXISTS course (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dept TEXT NOT NULL,
  course_num TEXT NOT NULL,
  title TEXT,
  credits INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_course_dept_num ON course(dept, course_num);
