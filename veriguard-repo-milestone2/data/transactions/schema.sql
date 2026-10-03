IF OBJECT_ID('dbo.transactions', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.transactions (
        transaction_id   NVARCHAR(20)  NOT NULL PRIMARY KEY,
        customer_id      NVARCHAR(20)  NOT NULL,
        transaction_date DATETIME2(0)  NOT NULL,
        amount           DECIMAL(18,2) NOT NULL,
        branch_id        NVARCHAR(10)  NOT NULL,
        transaction_type NVARCHAR(30)  NOT NULL,
        geography        NVARCHAR(50)  NOT NULL
    );
    CREATE INDEX ix_transactions_customer_date ON dbo.transactions (customer_id, transaction_date);
END
