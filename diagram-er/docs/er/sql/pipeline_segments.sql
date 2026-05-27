CREATE TABLE pipeline_segments (
    segment_id TEXT PRIMARY KEY COMMENT '管段编号',
    name TEXT COMMENT '管段名称',
    length_km REAL COMMENT '管段长度km',
    diameter_mm INT COMMENT '管径mm',
    region TEXT COMMENT '所属区域',
    lat_start REAL COMMENT '起点纬度',
    lon_start REAL COMMENT '起点经度',
    lat_end REAL COMMENT '终点纬度',
    lon_end REAL COMMENT '终点经度'
);
