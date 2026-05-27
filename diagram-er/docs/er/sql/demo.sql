CREATE TABLE users (
    id INT PRIMARY KEY COMMENT '用户ID',
    username VARCHAR(50) NOT NULL COMMENT '用户名',
    email VARCHAR(100) COMMENT '邮箱地址',
    phone VARCHAR(20) COMMENT '手机号',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
);

CREATE TABLE products (
    id INT PRIMARY KEY COMMENT '商品ID',
    name VARCHAR(100) NOT NULL COMMENT '商品名称',
    price DECIMAL(10,2) COMMENT '单价',
    stock INT COMMENT '库存数量',
    category VARCHAR(50) COMMENT '分类'
);

CREATE TABLE orders (
    id INT PRIMARY KEY COMMENT '订单ID',
    user_id INT COMMENT '用户ID',
    total_amount DECIMAL(12,2) COMMENT '订单金额',
    status VARCHAR(20) COMMENT '订单状态',
    created_at TIMESTAMP COMMENT '创建时间'
);

CREATE TABLE order_items (
    id INT PRIMARY KEY COMMENT '明细ID',
    order_id INT COMMENT '订单ID',
    product_id INT COMMENT '商品ID',
    quantity INT COMMENT '数量',
    unit_price DECIMAL(10,2) COMMENT '单价'
);
