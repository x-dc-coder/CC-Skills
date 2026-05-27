CREATE TABLE user_account_information (
    user_account_id INT PRIMARY KEY COMMENT '用户账户唯一标识编号',
    user_full_name VARCHAR(50) NOT NULL COMMENT '用户完整真实姓名',
    user_email_address VARCHAR(100) COMMENT '用户电子邮箱通讯地址',
    user_mobile_phone_number VARCHAR(20) COMMENT '用户移动电话号码',
    user_account_registration_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '用户账户注册创建时间戳'
);
