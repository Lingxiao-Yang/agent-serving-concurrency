CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT NOT NULL
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    amount REAL NOT NULL
);

INSERT INTO customers(customer_id, name, region) VALUES
    (1, 'Alice', 'East'),
    (2, 'Bob', 'East'),
    (3, 'Cara', 'West');

INSERT INTO orders(order_id, customer_id, amount) VALUES
    (1, 1, 120.0),
    (2, 1, 80.0),
    (3, 2, 50.0),
    (4, 3, 125.0);
