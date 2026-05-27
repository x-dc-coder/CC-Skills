CREATE TABLE leak_alerts (
    id INT PRIMARY KEY COMMENT '自增主键',
    segment_id TEXT COMMENT '关联管段',
    ts TIMESTAMP COMMENT '预警时间',
    risk_score DOUBLE COMMENT '风险评分',
    risk_level TEXT COMMENT '风险等级',
    alert_type TEXT COMMENT '预警类型',
    acknowledged INT COMMENT '是否处置'
);
