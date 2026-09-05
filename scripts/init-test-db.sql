-- Runs automatically on first Postgres container start (docker-entrypoint-initdb.d).
-- Creates a second database dedicated to the automated test suite so tests
-- never run against the same data as local manual testing.
CREATE DATABASE inventory_db_test;
