CREATE TABLE `order` (
  `id` bigint(20) NOT NULL PRIMARY KEY,
  `date` varchar(20) NOT NULL,
  `end_point_attachment` varchar(255),
  `end_point_amap` varchar(255),
  `province` varchar(50) NOT NULL,
  `city` varchar(50) NOT NULL,
  `latitude` decimal(10,6) NOT NULL,
  `longitude` decimal(10,6) NOT NULL,
  `user_type` varchar(20),
  `cargo_weight` decimal(10,2) NOT NULL
);
