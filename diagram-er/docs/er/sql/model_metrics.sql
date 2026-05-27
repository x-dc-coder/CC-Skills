CREATE TABLE model_metrics (
    id INT PRIMARY KEY COMMENT '自增主键',
    eval_date DATE COMMENT '评估日期',
    accuracy DOUBLE COMMENT '准确率',
    precision_ DOUBLE COMMENT '精确率',
    recall DOUBLE COMMENT '召回率',
    f1 DOUBLE COMMENT 'F1分数',
    auc DOUBLE COMMENT 'AUC值'
);
