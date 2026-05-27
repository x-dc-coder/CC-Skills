CREATE TABLE sensor_data (
    id INT PRIMARY KEY COMMENT '自增主键',
    segment_id TEXT COMMENT '关联管段',
    ts TIMESTAMP COMMENT '采集时间',
    pressure_in DOUBLE COMMENT '入口压力MPa',
    pressure_out DOUBLE COMMENT '出口压力MPa',
    flow_rate DOUBLE COMMENT '流量m3/h',
    temperature DOUBLE COMMENT '温度℃',
    vibration DOUBLE COMMENT '振动强度'
);
