CREATE TABLE `depot` (
  `id` bigint(20) NOT NULL PRIMARY KEY,
  `name` varchar(100) NOT NULL,
  `province` varchar(50) NOT NULL,
  `city` varchar(50) NOT NULL,
  `latitude` decimal(10,6) NOT NULL,
  `longitude` decimal(10,6) NOT NULL
);
