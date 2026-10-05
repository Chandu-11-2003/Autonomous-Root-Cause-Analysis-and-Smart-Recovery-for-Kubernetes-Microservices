-- Initialize database schema for microservices
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    balance NUMERIC(10, 2) DEFAULT 1000.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    price NUMERIC(10, 2) NOT NULL,
    stock INT NOT NULL DEFAULT 100,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    total_amount NUMERIC(10, 2) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    trace_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed Initial Data
INSERT INTO users (username, email, balance) VALUES
('alice', 'alice@example.com', 500.00),
('bob', 'bob@example.com', 1200.00),
('charlie', 'charlie@example.com', 50.00)
ON CONFLICT (username) DO NOTHING;

INSERT INTO products (name, description, price, stock) VALUES
('Cloud Native Laptop', 'High performance laptop for Kubernetes development', 999.99, 25),
('Kubernetes Action Figure', 'Collectible figurine with Helm chart cape', 24.99, 150),
('Observability Mug', 'Coffee mug with RED metrics graph', 14.50, 80),
('Reliability Book', 'Comprehensive guide to Site Reliability Engineering', 45.00, 200)
ON CONFLICT DO NOTHING;
