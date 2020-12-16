-- Calculates the combined pyhsical size used by all Member Audit tables in MB (for MySQL)
SELECT SUM(SIZE_MB)
FROM
(
    SELECT table_name, round(((data_length + index_length) / 1024 / 1024), 2) as SIZE_MB
    FROM information_schema.TABLES
    WHERE table_schema = DATABASE()
    AND table_name LIKE "memberaudit_%"
) as temp;
